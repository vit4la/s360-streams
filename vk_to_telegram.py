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
from pathlib import Path
from typing import Any, Dict, List

import requests

# ==========================
# CONFIG — ЗАПОЛНИТЬ ПЕРЕД ЗАПУСКОМ
# ==========================

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

# Токен VK с правами wall, groups
# В боевой среде лучше хранить его в переменной окружения или .env
# Если токен задан в .env или переменной окружения, используем его
# Иначе можно задать напрямую здесь (для обратной совместимости)
VK_TOKEN = os.getenv("VK_TOKEN") or "VK_ACCESS_TOKEN"  # Замените на реальный токен если нет в .env

# Версия VK API
VK_API_VERSION = "5.199"

# ID группы VK (без минуса), например 123456789
# Для tennisprimesport это 212808533
VK_GROUP_ID = 212808533

# Сколько последних постов запрашивать за один заход
POSTS_LIMIT = 20

# Telegram
# В боевой среде лучше хранить его в переменной окружения или .env
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "-4999682913"))

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

def get_vk_posts() -> List[Dict[str, Any]]:
    """Получить последние посты со стены группы VK."""
    url = "https://api.vk.com/method/wall.get"
    params = {
        "access_token": VK_TOKEN,
        "v": VK_API_VERSION,
        "owner_id": -VK_GROUP_ID,  # у групп в owner_id минус
        "count": POSTS_LIMIT,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"VK API error: {data['error']}")

    items = data.get("response", {}).get("items", [])
    logging.info("Получено %s пост(ов) из VK.", len(items))
    return items


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

    Критерии:
    - есть хотя бы одно видео-вложение;
    - в тексте есть одно из ключевых слов по турнирам/ассоциациям
      ИЛИ в тексте хотя бы 2 флага и знак '-' между ними.
    """
    has_video = any(a.get("type") == "video" for a in attachments)
    if not has_video:
        return False

    lower_text = text.lower()

    # Проверка ключевых слов
    for kw in TOURNAMENT_KEYWORDS:
        if kw.lower() in lower_text:
            return True

    # Проверка шаблона с флагами и тире
    flags_count = count_flag_emojis(text)
    if flags_count >= 2 and "-" in text:
        return True

    return False


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

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"

    media: List[Dict[str, Any]] = []
    for idx, photo_url in enumerate(photos):
        item: Dict[str, Any] = {
            "type": "photo",
            "media": photo_url,
        }
        # Подпись и parse_mode — только для первой
        if idx == 0:
            item["caption"] = caption
            item["parse_mode"] = parse_mode
        media.append(item)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "media": media,
    }

    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    logging.info("Отправлена медиагруппа из %s фото в Telegram.", len(photos))


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


def get_first_video_link(attachments: List[Dict[str, Any]]) -> str | None:
    """Получить прямую ссылку на первое видео из вложений."""
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


def build_post_caption(text: str, video_link: str | None = None) -> str:
    """Формирование подписи для Telegram.

    По требованиям берём текст поста почти как есть,
    но вырезаем служебные хвосты вида:
    - "Наш Telegram - t.me/primetennis"
    - "✅ Поддержать группу: ..."
    - "tips.tips/000457857"
    А также при наличии добавляем в конец прямую ссылку на видео.
    """
    raw = (text or "").strip()
    if not raw:
        return "Теннисная трансляция"

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

    # Добавляем ссылку на видео отдельной строкой
    if video_link:
        if caption:
            caption = f"{caption}\n\nВидео: {video_link}"
        else:
            caption = f"Видео: {video_link}"

    if not caption:
        return "Теннисная трансляция"
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

        if not is_broadcast_post(text, attachments):
            continue

        photos = extract_video_preview_urls(attachments)
        if not photos:
            logging.info("Пост %s пропущен: не удалось получить превью видео.", post_id)
            continue

        video_link = get_first_video_link(attachments)
        caption = build_post_caption(text, video_link)

        try:
            send_telegram_media_group(photos, caption)
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
    # Пробуем загрузить из .env еще раз (на случай если файл изменился)
    vk_token = os.getenv("VK_TOKEN") or VK_TOKEN
    if not vk_token or vk_token == "VK_ACCESS_TOKEN":
        logging.error("Не задан VK_TOKEN. Добавьте VK_TOKEN в .env файл или задайте в vk_to_telegram.py")
        return
    # Используем токен из переменной или из файла
    global VK_TOKEN
    VK_TOKEN = vk_token
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "TELEGRAM_BOT_TOKEN":
        logging.error("Не задан TELEGRAM_BOT_TOKEN. Откройте vk_to_telegram.py и заполните CONFIG.")
        return

    # Проверяем, запущен ли скрипт как сервис (через systemd)
    # Если да, работаем в цикле. Если нет (запуск вручную), выполняем один раз
    import os
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


