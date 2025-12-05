#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы системы.
Получает последние посты из каналов и добавляет их в БД для обработки.
"""

import asyncio
import logging
from datetime import datetime

from telethon import TelegramClient
from telethon.tl.types import Message

import config_moderation as config
from database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def fetch_and_add_posts():
    """Получить последние посты из каналов и добавить в БД."""
    db = Database(config.DATABASE_PATH)
    
    # Подключаемся к Telethon
    client = TelegramClient(
        config.TELEGRAM_SESSION_FILE,
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    
    await client.start(phone=config.TELEGRAM_PHONE)
    
    logger.info("Подключение к каналам...")
    
    for channel_id in config.SOURCE_CHANNEL_IDS:
        try:
            logger.info(f"Получаем посты из канала: {channel_id}")
            entity = await client.get_entity(channel_id)
            
            # Получаем последние 3 поста
            messages = await client.get_messages(entity, limit=3)
            
            added_count = 0
            for message in messages:
                if not isinstance(message, Message):
                    continue
                
                # Получаем текст
                text = message.message or ""
                if not text.strip():
                    logger.info(f"Пропущен пост без текста: message_id={message.id}")
                    continue
                
                # Получаем ID канала
                if hasattr(entity, "username") and entity.username:
                    channel_username = f"@{entity.username}"
                else:
                    channel_username = str(entity.id)
                
                # Добавляем в БД
                post_id = db.add_source_post(
                    channel_id=channel_username,
                    message_id=message.id,
                    text_original=text,
                    date=message.date if message.date else datetime.now(),
                )
                
                if post_id:
                    added_count += 1
                    logger.info(
                        f"✅ Добавлен пост: channel={channel_username}, "
                        f"message_id={message.id}, post_id={post_id}, "
                        f"text_preview={text[:50]}..."
                    )
                else:
                    logger.info(
                        f"⚠️ Пост уже существует: channel={channel_username}, "
                        f"message_id={message.id}"
                    )
            
            logger.info(f"Из канала {channel_id} добавлено новых постов: {added_count}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке канала {channel_id}: {e}", exc_info=True)
    
    await client.disconnect()
    
    # Проверяем что посты добавлены
    new_posts = db.get_new_source_posts()
    logger.info(f"\n📊 Итого новых постов для обработки: {len(new_posts)}")
    
    if new_posts:
        logger.info("Список новых постов:")
        for post in new_posts:
            logger.info(
                f"  - Post ID: {post['id']}, Channel: {post['channel_id']}, "
                f"Text: {post['text_original'][:60]}..."
            )
    
    # Проверяем черновики
    drafts = db.get_pending_draft_posts()
    logger.info(f"\n📝 Черновиков на модерации: {len(drafts)}")
    
    if drafts:
        logger.info("Последние черновики:")
        for draft in drafts[:3]:
            logger.info(
                f"  - Draft ID: {draft['id']}, Title: {draft['title'][:50]}..."
            )


if __name__ == "__main__":
    asyncio.run(fetch_and_add_posts())

