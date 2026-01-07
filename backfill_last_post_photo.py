#!/usr/bin/env python3
"""
Скрипт для отладки: пытается скачать фото для ПОСЛЕДНЕГО поста из source_posts
через Telethon и сохранить URL в поле photo_file_id.

Шаги:
1. Берёт последний пост из таблицы source_posts (ORDER BY created_at DESC LIMIT 1)
2. Подключается к Telegram через Telethon (та же сессия, что и у telethon_listener)
3. Получает исходное сообщение по channel_id и message_id
4. Если в сообщении есть медиа, скачивает его в /root/s360-streams/source_photos/
5. Формирует URL вида: IMAGE_RENDER_SERVICE_URL/source_photos/<filename>
6. Обновляет photo_file_id в БД
"""

import asyncio
import logging
import sqlite3
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import Message

import config_moderation as config


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_last_post_photo")

DB_PATH = config.DATABASE_PATH
SOURCE_PHOTOS_DIR = Path("/root/s360-streams/source_photos")
SOURCE_PHOTOS_DIR.mkdir(exist_ok=True)


def get_last_source_post():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, channel_id, message_id, photo_file_id, created_at
        FROM source_posts
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    conn.close()
    return row


def update_photo_file_id(post_id: int, photo_url: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE source_posts SET photo_file_id = ? WHERE id = ?",
        (photo_url, post_id),
    )
    conn.commit()
    conn.close()


async def backfill_photo() -> None:
    row = get_last_source_post()
    if not row:
        logger.error("В БД нет записей в source_posts")
        return

    post_id = row["id"]
    channel_id = row["channel_id"]
    message_id = int(row["message_id"])
    old_photo = row["photo_file_id"]

    logger.info(
        "Последний пост: id=%s, channel_id=%s, message_id=%s, photo_file_id=%s",
        post_id,
        channel_id,
        message_id,
        old_photo,
    )

    client = TelegramClient(
        config.TELEGRAM_SESSION_FILE,
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )

    await client.start(phone=config.TELEGRAM_PHONE)

    try:
        msg: Message = await client.get_messages(channel_id, ids=message_id)
        if not msg:
            logger.error("Не удалось получить сообщение из канала")
            return

        has_photo = bool(msg.photo)
        has_doc = bool(msg.document)
        has_media = bool(msg.media)
        logger.info(
            "Сообщение: has_photo=%s, has_document=%s, has_media=%s, media_type=%s",
            has_photo,
            has_doc,
            has_media,
            type(msg.media).__name__ if msg.media else "None",
        )

        if not has_media:
            logger.error("В сообщении нет медиа, нечего скачивать")
            return

        filename = f"backfill_post_{post_id}.jpg"
        target_path = SOURCE_PHOTOS_DIR / filename
        logger.info("Скачиваю медиа в файл: %s", target_path)

        downloaded_path = await client.download_media(msg, file=str(target_path))
        logger.info("download_media вернул путь: %s", downloaded_path)

        final_path = Path(downloaded_path) if downloaded_path else target_path
        if not final_path.exists():
            logger.error("Файл не найден после скачивания: %s", final_path)
            return

        logger.info(
            "Файл сохранён: %s, размер=%s байт",
            final_path,
            final_path.stat().st_size,
        )

        base_url = config.IMAGE_RENDER_SERVICE_URL.rstrip("/")
        photo_url = f"{base_url}/source_photos/{final_path.name}"
        logger.info("photo_url=%s", photo_url)

        update_photo_file_id(post_id, photo_url)
        logger.info("photo_file_id обновлён в БД для post_id=%s", post_id)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(backfill_photo())


