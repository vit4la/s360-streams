"""
Воркер для обработки исходных постов через GPT.
Берёт посты со статусом 'new', отправляет в GPT, создаёт черновики для модерации.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List
from pathlib import Path

import openai
from openai import OpenAI
import httpx
import requests

import config_moderation as config
from database import Database

logger = logging.getLogger(__name__)


class GPTWorker:
    """Класс для обработки постов через GPT."""

    def __init__(self, db: Database):
        """Инициализация воркера.

        Args:
            db: Экземпляр Database для работы с БД
        """
        self.db = db
        
        # Настройка клиента OpenAI с прокси, если указан
        client_kwargs = {"api_key": config.OPENAI_API_KEY}
        
        if config.OPENAI_PROXY:
            # Используем переменные окружения для прокси
            # Если прокси в формате http://, конвертируем в socks5:// если нужно
            import os
            proxy_url = config.OPENAI_PROXY
            
            # Если прокси начинается с http://, но это SOCKS5, меняем на socks5://
            if proxy_url.startswith("http://"):
                # Заменяем http:// на socks5:// для SOCKS5 прокси
                proxy_url = proxy_url.replace("http://", "socks5://", 1)
                logger.info("Конвертирован HTTP прокси в SOCKS5: %s", proxy_url)
            
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
            logger.info("Прокси установлен через переменные окружения: %s", proxy_url)
        else:
            logger.info("OpenAI клиент настроен без прокси")
        
        self.client = OpenAI(**client_kwargs)
        self.running = False
        
        # Создаём директорию для стилизованных изображений, если её нет
        config.RENDERED_IMAGES_DIR.mkdir(exist_ok=True)

    def _call_gpt(self, text: str) -> Optional[Dict[str, Any]]:
        """Вызвать GPT API для обработки текста.

        Args:
            text: Текст поста для обработки

        Returns:
            Словарь с полями title, body, hashtags или None при ошибке
        """
        prompt = f"{config.GPT_PROMPT}\n\nТекст поста:\n{text}"

        for attempt in range(config.GPT_MAX_RETRIES):
            try:
                logger.debug("Запрос к GPT (попытка %s/%s): модель=%s", 
                            attempt + 1, config.GPT_MAX_RETRIES, config.OPENAI_MODEL)

                response = self.client.chat.completions.create(
                    model=config.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": "Ты редактор спортивных новостей по теннису."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                logger.debug("Получен ответ от GPT: %s", content)

                # Парсим JSON
                result = json.loads(content)

                # Проверяем наличие обязательных полей
                if "title" not in result or "body" not in result or "hashtags" not in result:
                    logger.error("GPT вернул неполный ответ: %s", result)
                    return None

                # Преобразуем хэштеги в строку, если они в виде списка
                hashtags = result["hashtags"]
                if isinstance(hashtags, list):
                    hashtags_str = " ".join(hashtags)
                else:
                    hashtags_str = str(hashtags)

                # Получаем image_query (может отсутствовать в старых ответах GPT)
                image_query = result.get("image_query", "")

                return {
                    "title": result["title"],
                    "body": result["body"],
                    "hashtags": hashtags_str,
                    "image_query": image_query,
                    "raw_response": content,
                }

            except json.JSONDecodeError as e:
                logger.error("Ошибка парсинга JSON от GPT: %s, ответ: %s", e, content)
                if attempt < config.GPT_MAX_RETRIES - 1:
                    delay = config.GPT_RETRY_DELAYS[attempt] if attempt < len(config.GPT_RETRY_DELAYS) else 4
                    logger.info("Повтор через %s секунд...", delay)
                    time.sleep(delay)
                else:
                    return None

            except openai.RateLimitError as e:
                logger.warning("Rate limit от OpenAI (попытка %s/%s): %s", 
                             attempt + 1, config.GPT_MAX_RETRIES, e)
                if attempt < config.GPT_MAX_RETRIES - 1:
                    delay = config.GPT_RETRY_DELAYS[attempt] if attempt < len(config.GPT_RETRY_DELAYS) else 4
                    logger.info("Повтор через %s секунд...", delay)
                    time.sleep(delay)
                else:
                    logger.error("Превышено максимальное количество попыток из-за rate limit")
                    return None

            except openai.APIError as e:
                logger.error("Ошибка API OpenAI (попытка %s/%s): %s", 
                           attempt + 1, config.GPT_MAX_RETRIES, e)
                if attempt < config.GPT_MAX_RETRIES - 1:
                    delay = config.GPT_RETRY_DELAYS[attempt] if attempt < len(config.GPT_RETRY_DELAYS) else 4
                    logger.info("Повтор через %s секунд...", delay)
                    time.sleep(delay)
                else:
                    return None

            except Exception as e:
                logger.error("Неожиданная ошибка при вызове GPT (попытка %s/%s): %s", 
                           attempt + 1, config.GPT_MAX_RETRIES, e, exc_info=True)
                if attempt < config.GPT_MAX_RETRIES - 1:
                    delay = config.GPT_RETRY_DELAYS[attempt] if attempt < len(config.GPT_RETRY_DELAYS) else 4
                    logger.info("Повтор через %s секунд...", delay)
                    time.sleep(delay)
                else:
                    return None

        return None

    def _search_pexels_images(self, query: str, page: int = None) -> Optional[List[Dict[str, str]]]:
        """Поиск картинок через Pexels API.

        Args:
            query: Поисковый запрос (например: "tennis match WTA indoor")
            page: Номер страницы (1-80, если None - используется случайная страница для разнообразия)

        Returns:
            Список словарей с URL картинок или None при ошибке
        """
        if not query:
            logger.warning("Пустой запрос для поиска картинок")
            return None

        # Если page не указан, используем случайную страницу для разнообразия картинок
        if page is None:
            import random
            page = random.randint(1, 10)  # Случайная страница от 1 до 10
            logger.info("Используется случайная страница для разнообразия: page=%s", page)

        url = config.PEXELS_API_URL
        headers = {
            "Authorization": config.PEXELS_API_KEY
        }
        # Ограничиваем page от 1 до 80 (максимум для Pexels API)
        page = max(1, min(page, 80))
        params = {
            "query": query,
            "per_page": config.PEXELS_PER_PAGE,
            "orientation": "landscape",
            "page": page
        }

        try:
            logger.info("Запрос к Pexels API: query=%s, page=%s", query, page)
            # Используем httpx вместо requests для лучшей поддержки SOCKS5
            import httpx
            proxy_url = None
            if config.OPENAI_PROXY:
                proxy_url = config.OPENAI_PROXY
                if proxy_url.startswith("http://"):
                    proxy_url = proxy_url.replace("http://", "socks5://", 1)
            
            with httpx.Client(proxy=proxy_url, timeout=10.0) as client:
                resp = client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()

            photos = data.get("photos", [])
            if not photos:
                logger.warning("Pexels API вернул пустой результат для запроса: %s", query)
                return None

            # Извлекаем URL картинок (приоритет: large > landscape > medium)
            image_urls = []
            for photo in photos:
                src = photo.get("src", {})
                # Берём large или landscape, если есть
                url = src.get("large") or src.get("landscape") or src.get("medium")
                if url:
                    image_urls.append({
                        "url": url,
                        "photographer": photo.get("photographer", "Unknown"),
                        "id": photo.get("id")
                    })

            logger.info("Pexels API вернул %s картинок для запроса: %s", len(image_urls), query)
            return image_urls

        except requests.exceptions.RequestException as e:
            logger.error("Ошибка при запросе к Pexels API: %s", e)
            return None
        except Exception as e:
            logger.error("Неожиданная ошибка при работе с Pexels API: %s", e, exc_info=True)
            return None

    def _render_image(self, image_url: str, title: str) -> Optional[str]:
        """Вызвать сервис стилизации изображения.

        Args:
            image_url: URL исходной картинки
            title: Заголовок новости

        Returns:
            URL стилизованной картинки или None при ошибке
        """
        service_url = f"{config.IMAGE_RENDER_SERVICE_URL}/render"
        payload = {
            "image_url": image_url,
            "title": title,
            "template": "default"
        }

        try:
            logger.info("Запрос к сервису стилизации: image_url=%s", image_url[:100])
            resp = requests.post(service_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            final_url = data.get("final_image_url")
            if not final_url:
                logger.error("Сервис стилизации не вернул final_image_url")
                return None

            logger.info("Картинка стилизована: %s", final_url)
            return final_url

        except requests.exceptions.RequestException as e:
            logger.error("Ошибка при запросе к сервису стилизации: %s", e)
            return None
        except Exception as e:
            logger.error("Неожиданная ошибка при работе с сервисом стилизации: %s", e, exc_info=True)
            return None

    def _process_post(self, post: Dict[str, Any]) -> None:
        """Обработать один пост через GPT.

        Args:
            post: Словарь с данными поста из БД
        """
        post_id = post["id"]
        text = post["text_original"]

        logger.info("Обработка поста через GPT: post_id=%s, text_preview=%.100s...", 
                   post_id, text)

        # Вызываем GPT
        result = self._call_gpt(text)

        if not result:
            logger.error("Не удалось обработать пост через GPT: post_id=%s", post_id)
            # Можно пометить пост как failed или оставить new для повторной попытки
            return

        # Ищем картинки через Pexels API (без стилизации - стилизация будет после выбора оператором)
        image_query = result.get("image_query", "")
        final_image_url = None
        pexels_images_json = None

        if image_query:
            pexels_images = self._search_pexels_images(image_query)
            if pexels_images and len(pexels_images) > 0:
                # Сохраняем картинки в JSON для выбора оператором
                import json
                pexels_images_json = json.dumps(pexels_images, ensure_ascii=False)
                logger.info("Найдено %s картинок в Pexels для поста: post_id=%s", len(pexels_images), post_id)
            else:
                logger.warning("Не найдены картинки в Pexels для запроса: %s", image_query)
        else:
            logger.debug("GPT не вернул image_query для поста: post_id=%s", post_id)

        # Создаём черновик
        try:
            draft_id = self.db.add_draft_post(
                source_post_id=post_id,
                title=result["title"],
                body=result["body"],
                hashtags=result["hashtags"],
                gpt_response_raw=result["raw_response"],
                image_query=image_query,
                final_image_url=final_image_url,
                pexels_images_json=pexels_images_json,
            )

            # Отмечаем исходный пост как обработанный
            self.db.mark_source_post_processed(post_id)

            logger.info(
                "Пост обработан и создан черновик: post_id=%s, draft_id=%s, "
                "title=%.50s..., image_url=%s",
                post_id,
                draft_id,
                result["title"],
                "да" if final_image_url else "нет",
            )
        except Exception as e:
            logger.error("Ошибка при создании черновика: post_id=%s, error=%s", 
                        post_id, e, exc_info=True)

    async def process_loop(self, interval: float = 5.0) -> None:
        """Основной цикл обработки постов.

        Args:
            interval: Интервал между проверками новых постов (секунды)
        """
        self.running = True
        logger.info("GPT воркер запущен (интервал проверки: %s сек)", interval)

        while self.running:
            try:
                # Получаем новые посты
                new_posts = self.db.get_new_source_posts()

                if new_posts:
                    logger.info("Найдено новых постов для обработки: %s", len(new_posts))
                    for post in new_posts:
                        # Обрабатываем синхронно (GPT API синхронный)
                        self._process_post(post)
                        # Небольшая задержка между постами, чтобы не перегружать API
                        await asyncio.sleep(1)
                else:
                    logger.debug("Новых постов для обработки нет")

                # Ждём перед следующей проверкой
                await asyncio.sleep(interval)

            except Exception as e:
                logger.error("Ошибка в цикле обработки GPT: %s", e, exc_info=True)
                await asyncio.sleep(interval)

    def stop(self) -> None:
        """Остановить воркер."""
        logger.info("Остановка GPT воркера...")
        self.running = False


async def main():
    """Тестовая функция для запуска воркера."""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db = Database(config.DATABASE_PATH)
    worker = GPTWorker(db)

    try:
        await worker.process_loop(interval=5.0)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
        worker.stop()
    except Exception as e:
        logger.error("Критическая ошибка: %s", e, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())


