#!/usr/bin/env python3
"""
Скрипт: VK -> Telegram (трансляции тенниса)

Функции:
- раз в N минут опрашивает стену VK-группы;
- выбирает только посты с трансляциями по набору ключевых слов;
- берёт вложения video, вытаскивает превью-картинки;
- отправляет в Telegram как медиагруппу (альбом) с общей подписью;
- запоминает последний отправленный post_id, чтобы не было дублей.

Перед запуском обязательно заполните настройки в блоке CONFIG ниже.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import requests

# ==========================
# CONFIG — ЗАПОЛНИТЬ ПЕРЕД ЗАПУСКОМ
# ==========================

import os

# Загружаем переменные из .env файла, если он существует
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                # Убираем кавычки если есть
                value = value.strip('"\'')
                # Устанавливаем переменную окружения только если она еще не установлена
                if key not in os.environ:
                    os.environ[key] = value

# Токены VK с правами wall, groups.
# ВАЖНО: чтобы не зависеть от кривого .env на сервере, здесь жёстко зашиваем
# рабочий user‑токен как основной.
VK_TOKEN = "d165ed0dd165ed0dd165ed0dddd25853dbdd165d165ed0db84a1c02d67d4a7083b2f985"  # Рабочий user‑токен (основной)
VK_TOKEN_2 = "vk1.a.FPDg_piW9vaMtIrZaYdu4RLwn8MafVdULEVrqjUNUOcFG6QuW696NRH6hMi4AQ1uSC5J7_Pu_bfuuLiY3zXaB9WhJ79YLunyXZb65p6HaUU45xnHOyqJzLtj6l88QOMYcNtuKY5_tOE40NuHXM_iikja-6GeJoPotE2nBpaEsbNhBKOmbb7hotN3btfEZoVXo0cKeZ1Bej6ALG7EVmPtcg"  # Community Token (может не читать wall.get)

# Версия VK API
VK_API_VERSION = "5.199"

# ID группы VK (без минуса), например 123456789
# Новая группа: club235512260 (вы — админ, из неё и парсим)
VK_GROUP_ID = 235512260

# Сколько последних постов запрашивать за один заход
POSTS_LIMIT = 20

# Telegram
# В боевой среде лучше хранить его в переменной окружения или .env
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")
# chat_id может быть числом (для групп) или строкой (username типа @S360streams)
_telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "@S360streams")
try:
    TELEGRAM_CHAT_ID = int(_telegram_chat_id)  # Если это число, преобразуем
except ValueError:
    TELEGRAM_CHAT_ID = _telegram_chat_id  # Если строка (username), оставляем как есть

# Файл для хранения состояния (последний отправленный post_id)
STATE_FILE = Path("vk_last_post_state.json")

# Логгирование
LOG_LEVEL = logging.INFO


def setup_logging() -> None:
    """Настройка простого логгера."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


# ==========================
# ФУНКЦИИ РАБОТЫ С СОСТОЯНИЕМ
# ==========================

def load_state() -> Dict[str, Any]:
    """Загрузка состояния из файла.

    Формат:
    {
        "last_post_id": int,
        "initialized": bool
    }
    """
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("Не удалось прочитать файл состояния, создаём новый.")
    return {"last_post_id": 0, "initialized": False}


def save_state(state: Dict[str, Any]) -> None:
    """Сохранение состояния в файл."""
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logging.exception("Не удалось сохранить файл состояния.")


# ==========================
# VK API
# ==========================

def get_vk_posts_via_api(token: str = None) -> List[Dict[str, Any]]:
    """Получить посты через VK API напрямую (wall.get).
    
    Это самый быстрый и надежный способ для открытых групп.
    """
    if token is None:
        # Не берём токен из окружения, чтобы не уткнуться в старый/битый .env на сервере
        token = VK_TOKEN
    
    if not token or token == "VK_ACCESS_TOKEN" or token == "":
        return []
    
    try:
        url = "https://api.vk.com/method/wall.get"
        params = {
            "access_token": token,
            "v": VK_API_VERSION,
            "owner_id": -VK_GROUP_ID,
            "count": POSTS_LIMIT,
            "extended": 1,  # Получаем расширенную информацию о вложениях
        }
        
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if "error" in data:
            error = data["error"]
            error_code = error.get("error_code", "?")
            error_msg = error.get("error_msg", "Unknown error")
            logging.warning("VK API ошибка %s: %s", error_code, error_msg)
            return []
        
        items = data.get("response", {}).get("items", [])
        if not items:
            return []
        
        # Преобразуем формат VK API в наш формат
        posts = []
        for item in items:
            post_id = item.get("id")
            text = item.get("text", "")
            attachments = item.get("attachments", [])
            
            # Преобразуем attachments в наш формат
            formatted_attachments = []
            for att in attachments:
                att_type = att.get("type")
                if att_type == "video":
                    video = att.get("video", {})
                    formatted_attachments.append({
                        "type": "video",
                        "video": video
                    })
            
            posts.append({
                "id": post_id,
                "text": text,
                "attachments": formatted_attachments
            })
        
        logging.info("Получено %s пост(ов) через VK API.", len(posts))
        return posts
        
    except Exception as e:
        logging.debug("VK API не сработал: %s", e)
        return []


def get_vk_posts() -> List[Dict[str, Any]]:
    """Получить последние посты со стены группы VK только через VK API.

    ВАЖНО: никаких cookies, Selenium и RSS — только wall.get с рабочими токенами.
    """
    logging.info("Пробую VK API (первый токен)...")
    vk_token_1 = VK_TOKEN
    if vk_token_1:
        posts = get_vk_posts_via_api(vk_token_1)
        if posts:
            logging.info("✅ Успешно получены посты через VK API (первый токен).")
            return posts

    logging.info("Первый токен не сработал, пробую VK API (второй токен)...")
    vk_token_2 = VK_TOKEN_2
    if vk_token_2:
        posts = get_vk_posts_via_api(vk_token_2)
        if posts:
            logging.info("✅ Успешно получены посты через VK API (второй токен).")
            return posts

    logging.error("Не удалось получить посты через VK API (оба токена не сработали).")
    return []


def get_vk_posts_scraping() -> List[Dict[str, Any]]:
    """
    Fallback: получить посты через RSS фид VK (без API).
    VK предоставляет RSS фиды для публичных групп.
    """
    try:
        # Пробуем RSS фид VK (работает для публичных групп)
        # Определяем домен группы из VK_GROUP_ID/URL
        group_domain = f"club{VK_GROUP_ID}"
        rss_url = f"https://vk.com/rss.php?domain={group_domain}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        resp = requests.get(rss_url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        # Парсим RSS XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        
        posts = []
        # RSS формат: channel -> item
        items = root.findall(".//item")
        
        for item in items[:POSTS_LIMIT]:
            try:
                # Извлекаем данные из RSS
                title = item.find("title")
                description = item.find("description")
                link = item.find("link")
                
                if link is not None and link.text:
                    # Извлекаем post_id из ссылки вида https://vk.com/tennisprimesport?w=wall-212808533_12345
                    link_text = link.text
                    post_id_match = re.search(r'wall-(\d+)_(\d+)', link_text)
                    if post_id_match:
                        post_id = int(post_id_match.group(2))
                        text = (title.text if title is not None else "") + " " + (description.text if description is not None else "")
                        
                        posts.append({
                            "id": post_id,
                            "text": text.strip(),
                            "attachments": []  # RSS не содержит информацию о вложениях
                        })
            except Exception as e:
                logging.debug("Ошибка при парсинге RSS item: %s", e)
                continue
        
        if posts:
            logging.info("Получено %s пост(ов) через RSS фид VK.", len(posts))
            return posts
        else:
            logging.warning("RSS фид пуст или недоступен. Группа может быть закрытой.")
            return []
        
    except Exception as e:
        logging.error("Ошибка при получении RSS фида VK: %s", e)
        logging.warning("Веб-скрапинг VK ограничен - VK использует JavaScript для загрузки постов.")
        logging.warning("Рекомендуется использовать API с правильным токеном.")
        return []


# ==========================
# ФИЛЬТРАЦИЯ ТРАНСЛЯЦИЙ
# ==========================

TOURNAMENT_KEYWORDS = [
    "WTA",
    "ATP",
    "Ролан Гаррос",
    "Roland Garros",
    "Открытый чемпионат Австралии",
    "Australian Open",
    "Открытый чемпионат США",
    "US Open",
    "Уимблдон",
    "Wimbledon",
]


def count_flag_emojis(text: str) -> int:
    """Подсчёт флаг-эмодзи в тексте (две региональные буквы подряд)."""
    count = 0
    i = 0
    while i < len(text) - 1:
        ch1 = ord(text[i])
        ch2 = ord(text[i + 1])
        # Диапазон региональных индикаторов флагов
        if 0x1F1E6 <= ch1 <= 0x1F1FF and 0x1F1E6 <= ch2 <= 0x1F1FF:
            count += 1
            i += 2
        else:
            i += 1
    return count


def is_broadcast_post(text: str, attachments: List[Dict[str, Any]]) -> bool:
    """Определение, является ли пост трансляцией.

    УПРОЩЁННАЯ ВЕРСИЯ:
    Сейчас для новой группы club235512260 шлём **любой** новый пост в Telegram,
    без обязательного видео и ключевых слов, чтобы сервис просто снова работал.
    При необходимости фильтрацию можно ужесточить позже.
    """
    return True


# ==========================
# TELEGRAM API
# ==========================

def send_telegram_media_group(
    photos: List[str],
    caption: str,
    parse_mode: str = "HTML",
) -> None:
    """Отправка альбома (медиагруппы) в Telegram.

    В photos ожидается список URL картинок.
    Подпись ставится только к первой картинке.
    """
    if not photos:
        logging.warning("Пустой список фото для отправки в Telegram.")
        return

    # Используем токен из переменной окружения или глобальной константы
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
    chat_id_env = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id_env:
        # Если из .env - пытаемся преобразовать в число, если не получается - оставляем строкой
        try:
            chat_id = int(chat_id_env)
        except ValueError:
            chat_id = chat_id_env  # username типа @S360streams
    else:
        chat_id = TELEGRAM_CHAT_ID  # Используем из конфига (может быть число или строка)

    # Логируем chat_id для отладки
    logging.info("Отправка в Telegram: chat_id=%s, фото=%s", chat_id, len(photos))

    # Ограничиваем длину caption (Telegram лимит: 1024 символа)
    if len(caption) > 1024:
        caption = caption[:1021] + "..."
        logging.warning("Подпись обрезана до 1024 символов.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"

    media: List[Dict[str, Any]] = []
    for idx, photo_url in enumerate(photos):
        # Проверяем, что URL не пустой
        if not photo_url or not isinstance(photo_url, str):
            logging.warning("Пропущен невалидный URL фото: %s", photo_url)
            continue
            
        item: Dict[str, Any] = {
            "type": "photo",
            "media": photo_url,
        }
        # Подпись и parse_mode — только для первой
        if idx == 0:
            item["caption"] = caption
            item["parse_mode"] = parse_mode
        media.append(item)

    # Если после фильтрации не осталось валидных фото, выходим
    if not media:
        logging.error("Нет валидных фото для отправки в Telegram.")
        return

    payload = {
        "chat_id": chat_id,  # Telegram API принимает chat_id как число или строку (username типа @S360streams)
        "media": media,
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        logging.info("Отправлена медиагруппа из %s фото в Telegram.", len(media))
    except requests.exceptions.HTTPError as e:
        # Детальное логирование ошибки от Telegram API
        error_detail = ""
        try:
            error_json = resp.json()
            error_detail = f" | Telegram API ответ: {error_json}"
        except:
            error_detail = f" | Ответ сервера: {resp.text[:500]}"
        logging.error("Ошибка Telegram API при отправке медиагруппы: %s%s", str(e), error_detail)
        # Логируем также payload для отладки (без токена)
        logging.error("Payload для отладки: chat_id=%s, media_count=%s, caption_len=%s, first_photo_url=%s", 
                     chat_id, len(media), len(caption), photos[0][:100] if photos else "нет")
        raise


def send_telegram_message(
    text: str,
    parse_mode: str = "HTML",
) -> None:
    """Отправка обычного текстового сообщения в Telegram (используем, если нет видео/картинок)."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
    chat_id_env = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id_env:
        try:
            chat_id = int(chat_id_env)
        except ValueError:
            chat_id = chat_id_env
    else:
        chat_id = TELEGRAM_CHAT_ID

    logging.info("Отправка текстового сообщения в Telegram: chat_id=%s", chat_id)

    if len(text) > 4096:
        text = text[:4093] + "..."
        logging.warning("Текст сообщения обрезан до 4096 символов.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        logging.info("Отправлено текстовое сообщение в Telegram.")
    except requests.exceptions.HTTPError as e:
        error_detail = ""
        try:
            error_json = resp.json()
            error_detail = f" | Telegram API ответ: {error_json}"
        except:
            error_detail = f" | Ответ сервера: {resp.text[:500]}"
        logging.error("Ошибка Telegram API при отправке сообщения: %s%s", str(e), error_detail)
        raise


# ==========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================

def extract_video_preview_urls(attachments: List[Dict[str, Any]]) -> List[str]:
    """Извлечь URL превью-картинок из видео-вложений VK.

    Логика:
    - берём вложения типа 'video';
    - из объекта video выбираем либо массив image (ищем самый большой размер),
      либо first_frame_* поля, если они есть.
    """
    result: List[str] = []
    for a in attachments:
        if a.get("type") != "video":
            continue

        video = a.get("video") or {}

        # Вариант 1: поле image — список разных размеров
        images = video.get("image") or []
        if isinstance(images, list) and images:
            # выбираем картинку с максимальной шириной
            best = max(images, key=lambda img: img.get("width", 0))
            url = best.get("url")
            if url:
                result.append(url)
                continue

        # Вариант 2: first_frame_* поля
        for key in ("first_frame_800", "first_frame_640", "first_frame_320", "first_frame"):
            url = video.get(key)
            if isinstance(url, str) and url:
                result.append(url)
                break

    return result


def extract_links_from_text(text: str) -> List[str]:
    """Извлечь все URL-ссылки из текста поста (трансляции, YouTube, Twitch и т.д.)."""
    if not text:
        return []
    
    # Регулярное выражение для поиска URL
    url_pattern = re.compile(
        r'https?://'  # http:// или https://
        r'(?:[-\w.])+'  # домен
        r'(?::[0-9]+)?'  # опциональный порт
        r'(?:/(?:[\w/_.])*)?'  # путь
        r'(?:\?(?:[\w&=%.])*)?'  # query параметры
        r'(?:#(?:[\w.])*)?',  # fragment
        re.IGNORECASE
    )
    
    links = url_pattern.findall(text)
    return links


def get_first_video_link(attachments: List[Dict[str, Any]]) -> str | None:
    """Получить прямую ссылку на первое видео из вложений VK."""
    for a in attachments:
        if a.get("type") != "video":
            continue
        video = a.get("video") or {}
        owner_id = video.get("owner_id")
        video_id = video.get("id")
        if owner_id is None or video_id is None:
            continue
        return f"https://vk.com/video{owner_id}_{video_id}"
    return None


def build_post_caption(text: str, video_link: str | None = None, stream_links: List[str] | None = None) -> str:
    """Формирование подписи для Telegram.

    По требованиям берём текст поста почти как есть,
    но вырезаем служебные хвосты вида:
    - "Наш Telegram - t.me/primetennis"
    - "✅ Поддержать группу: ..."
    - "tips.tips/000457857"
    А также при наличии добавляем в конец прямую ссылку на видео.
    В начало добавляем заголовок "⚡️Новая трансляция от Прайм Теннис".
    """
    # Добавляем заголовок в начало
    header = "⚡️Новая трансляция от Прайм Теннис"
    
    raw = (text or "").strip()
    if not raw:
        # Если текста нет, всё равно отправляем заголовок (может быть пост только с картинкой/видео)
        caption = header
        if video_link:
            caption = f"{caption}\n\nВидео: {video_link}"
        logging.debug("build_post_caption: текст поста пустой, возвращаю только заголовок")
        return caption

    lines = [line.rstrip() for line in raw.splitlines()]
    cleaned_lines: List[str] = []

    for line in lines:
        low = line.lower()

        # жёсткие исключения по подстрокам
        if "наш telegram - t.me/primetennis".lower() in low:
            continue
        if "t.me/primetennis".lower() in low:
            continue
        if "поддержать группу" in low:
            continue
        if "tips.tips/000457857" in low:
            continue

        cleaned_lines.append(line)

    caption = "\n".join(cleaned_lines).strip()

    # Добавляем ссылки на трансляции
    links_to_add = []
    if video_link:
        links_to_add.append(f"Видео VK: {video_link}")
    if stream_links:
        for link in stream_links:
            # Определяем тип ссылки для красивого отображения
            if "youtube.com" in link or "youtu.be" in link:
                links_to_add.append(f"🎥 YouTube: {link}")
            elif "twitch.tv" in link:
                links_to_add.append(f"🎮 Twitch: {link}")
            else:
                links_to_add.append(f"🔗 Трансляция: {link}")
    
    if links_to_add:
        links_text = "\n".join(links_to_add)
        if caption:
            caption = f"{caption}\n\n{links_text}"
        else:
            caption = links_text

    # Добавляем заголовок в начало
    if caption:
        caption = f"{header}\n\n{caption}"
    else:
        caption = header
        if links_to_add:
            caption = f"{caption}\n\n{links_text}"

    return caption


# ==========================
# ОСНОВНАЯ ЛОГИКА
# ==========================

def process_posts() -> None:
    """Основной цикл обработки новых постов VK."""
    state = load_state()
    last_id = int(state.get("last_post_id", 0))
    initialized = bool(state.get("initialized", False))

    posts = get_vk_posts()
    if not posts:
        logging.info("Новых постов в VK не найдено.")
        return

    # Первый запуск: просто запоминаем максимальный id и ничего не шлём
    if not initialized:
        max_id = max(p["id"] for p in posts)
        state["last_post_id"] = max_id
        state["initialized"] = True
        save_state(state)
        logging.info(
            "Первый запуск: инициализировали last_post_id=%s, отправка постов не выполнялась.",
            max_id,
        )
        return

    # Идём от старых к новым, чтобы в ТГ хронология была нормальной
    posts_sorted = sorted(posts, key=lambda p: p["id"])

    new_last_id = last_id
    for post in posts_sorted:
        post_id = int(post["id"])
        if post_id <= last_id:
            continue

        text = post.get("text", "") or ""
        attachments = post.get("attachments") or []

        # Логируем что получили из API
        logging.info("Пост %s: текст = '%s' (длина %s), вложений = %s", post_id, text[:100], len(text), len(attachments))

        if not is_broadcast_post(text, attachments):
            logging.info("Пост %s пропущен фильтром is_broadcast_post", post_id)
            continue

        # Извлекаем ссылки на трансляции из текста поста
        stream_links = extract_links_from_text(text)
        logging.info("Пост %s: найдено ссылок в тексте: %s", post_id, len(stream_links))
        if stream_links:
            logging.info("Пост %s: ссылки: %s", post_id, stream_links[:3])  # Показываем первые 3
        
        photos = extract_video_preview_urls(attachments)
        video_link = get_first_video_link(attachments)
        caption = build_post_caption(text, video_link, stream_links)
        
        # Логируем что получилось в caption
        logging.info("Пост %s: caption = '%s' (длина %s символов), фото = %s", post_id, caption[:150], len(caption), len(photos) if photos else 0)

        try:
            if photos:
                # Есть превью — шлём медиагруппу
                logging.debug(
                    "Пост %s: найдено %s превью, первое URL: %s",
                    post_id,
                    len(photos),
                    photos[0][:100] if photos else "нет",
                )
                send_telegram_media_group(photos, caption)
            else:
                # Нет видео/картинок — шлём просто текст
                logging.info(
                    "Пост %s: превью видео не найдено, отправляем текстовое сообщение без медиа.",
                    post_id,
                )
                send_telegram_message(caption)
        except Exception:
            # По требованиям — просто логируем и двигаемся дальше
            logging.exception("Ошибка при отправке поста %s в Telegram.", post_id)
            continue

        new_last_id = max(new_last_id, post_id)
        logging.info("Пост %s успешно отправлен в Telegram.", post_id)

    # Обновляем состояние, если были новые отправленные посты
    if new_last_id > last_id:
        state["last_post_id"] = new_last_id
        save_state(state)
        logging.info("Обновлён last_post_id до %s.", new_last_id)


def main() -> None:
    setup_logging()

    # Простая проверка заполненности конфигурации
    # Для надёжности опираемся на жёстко заданный VK_TOKEN, а не на .env
    vk_token = VK_TOKEN
    if not vk_token:
        logging.error("Не задан VK_TOKEN в vk_to_telegram.py")
        return
    
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
    if not telegram_token or telegram_token == "TELEGRAM_BOT_TOKEN":
        logging.error("Не задан TELEGRAM_BOT_TOKEN. Добавьте TELEGRAM_BOT_TOKEN в .env файл или задайте в vk_to_telegram.py")
        return

    # Проверяем, запущен ли скрипт как сервис (через systemd)
    # Если да, работаем в цикле. Если нет (запуск вручную), выполняем один раз
    is_service = os.getenv("SYSTEMD_SERVICE", "0") == "1"
    
    if is_service:
        # Режим сервиса: работаем в цикле
        import time
        CHECK_INTERVAL = 15 * 60  # 15 минут в секундах
        
        logging.info("Запуск в режиме сервиса. Интервал проверки: %s минут", CHECK_INTERVAL // 60)
        
        while True:
            try:
                process_posts()
            except Exception:
                # По требованиям: просто логируем, без доп. уведомлений
                logging.exception("Необработанная ошибка при обработке постов.")
            
            # Ждем перед следующей проверкой
            logging.debug("Ожидание %s секунд до следующей проверки...", CHECK_INTERVAL)
            time.sleep(CHECK_INTERVAL)
    else:
        # Режим одноразового запуска (для cron или ручного запуска)
        try:
            process_posts()
        except Exception:
            # По требованиям: просто логируем, без доп. уведомлений
            logging.exception("Необработанная ошибка при обработке постов.")


if __name__ == "__main__":
    main()


