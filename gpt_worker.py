"""
Воркер для обработки исходных постов через GPT.
Берёт посты со статусом 'new', отправляет в GPT, создаёт черновики для модерации.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional

import openai
from openai import OpenAI
import httpx

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
            # Используем httpx с прокси
            # httpx требует прокси в формате словаря или строки для всех протоколов
            http_client = httpx.Client(
                proxies={
                    "http://": config.OPENAI_PROXY,
                    "https://": config.OPENAI_PROXY,
                },
                timeout=60.0,
            )
            client_kwargs["http_client"] = http_client
            logger.info("OpenAI клиент настроен с прокси: %s", config.OPENAI_PROXY)
        else:
            logger.info("OpenAI клиент настроен без прокси")
        
        self.client = OpenAI(**client_kwargs)
        self.running = False

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

                return {
                    "title": result["title"],
                    "body": result["body"],
                    "hashtags": hashtags_str,
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

        # Создаём черновик
        try:
            draft_id = self.db.add_draft_post(
                source_post_id=post_id,
                title=result["title"],
                body=result["body"],
                hashtags=result["hashtags"],
                gpt_response_raw=result["raw_response"],
            )

            # Отмечаем исходный пост как обработанный
            self.db.mark_source_post_processed(post_id)

            logger.info(
                "Пост обработан и создан черновик: post_id=%s, draft_id=%s, "
                "title=%.50s...",
                post_id,
                draft_id,
                result["title"],
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


