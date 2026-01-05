"""
Модуль для чтения постов из исходных Telegram-каналов через Telethon.
Работает как юзер-бот, подписанный на нужные каналы.
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from telethon import TelegramClient, events
from telethon.tl.types import Message, Channel, Chat

import config_moderation as config
from database import Database

logger = logging.getLogger(__name__)


class TelethonListener:
    """Класс для прослушивания новых сообщений из исходных каналов."""

    def __init__(self, db: Database):
        """Инициализация слушателя.

        Args:
            db: Экземпляр Database для сохранения постов
        """
        self.db = db
        self.client: Optional[TelegramClient] = None
        self.source_channels: List[str] = config.SOURCE_CHANNEL_IDS

    async def start(self) -> None:
        """Запустить клиент Telethon и начать прослушивание."""
        logger.info("Запуск Telethon клиента...")

        self.client = TelegramClient(
            config.TELEGRAM_SESSION_FILE,
            config.TELEGRAM_API_ID,
            config.TELEGRAM_API_HASH,
        )

        await self.client.start(phone=config.TELEGRAM_PHONE)

        # Проверяем, что мы подписаны на все исходные каналы
        await self._check_channels()

        # Регистрируем обработчик новых сообщений
        @self.client.on(events.NewMessage(chats=self.source_channels))
        async def handler(event: events.NewMessage.Event) -> None:
            await self._handle_new_message(event)

        logger.info("Telethon клиент запущен и слушает каналы: %s", self.source_channels)

    async def _check_channels(self) -> None:
        """Проверить доступность исходных каналов."""
        if not self.client:
            return

        logger.info("Проверка доступности исходных каналов...")
        for channel_id in self.source_channels:
            try:
                entity = await self.client.get_entity(channel_id)
                if isinstance(entity, (Channel, Chat)):
                    title = getattr(entity, "title", channel_id)
                    logger.info("Канал доступен: %s (%s)", title, channel_id)
                else:
                    logger.warning("Не удалось получить информацию о канале: %s", channel_id)
            except Exception as e:
                logger.error("Ошибка при проверке канала %s: %s", channel_id, e)

    async def _handle_new_message(self, event: events.NewMessage.Event) -> None:
        """Обработать новое сообщение из канала.

        Args:
            event: Событие нового сообщения
        """
        if not isinstance(event.message, Message):
            return

        message = event.message
        chat = await event.get_chat()

        # Получаем ID канала
        if hasattr(chat, "id"):
            channel_id = str(chat.id)
        else:
            channel_id = str(chat.id) if hasattr(chat, "id") else "unknown"

        # Получаем username канала, если есть
        channel_username = getattr(chat, "username", None)
        if channel_username:
            channel_id = f"@{channel_username}"

        message_id = message.id

        # Получаем текст поста
        text = message.message or ""
        if not text and message.raw_text:
            text = message.raw_text

        # Если текста нет, пропускаем (это может быть медиа без подписи)
        if not text.strip():
            logger.debug("Пропущено сообщение без текста: channel_id=%s, message_id=%s", 
                        channel_id, message_id)
            return

        # Скачиваем картинку из поста (если есть) и сохраняем на сервер
        photo_file_path = None
        if message.photo or (message.document and message.document.mime_type and message.document.mime_type.startswith("image/")):
            try:
                from pathlib import Path
                import uuid
                
                # Создаем директорию для сохранения оригинальных фото
                photos_dir = Path(__file__).parent / "source_photos"
                photos_dir.mkdir(exist_ok=True)
                
                # Скачиваем фото через Telethon
                photo_filename = f"source_{uuid.uuid4().hex}.jpg"
                photo_file_path = photos_dir / photo_filename
                
                logger.info("Скачивание фото из поста: channel_id=%s, message_id=%s", channel_id, message_id)
                await self.client.download_media(message, file=str(photo_file_path))
                
                # Формируем URL для доступа к фото (через сервис стилизации или напрямую)
                # Пока сохраняем путь, потом можно будет использовать через HTTP
                base_url = config.IMAGE_RENDER_SERVICE_URL.rstrip("/") if hasattr(config, 'IMAGE_RENDER_SERVICE_URL') else "http://localhost:8000"
                photo_url = f"{base_url}/source_photos/{photo_filename}"
                
                # Проверяем, что файл действительно сохранен
                if photo_file_path.exists():
                    logger.info("Фото успешно сохранено: %s, размер: %s байт, URL: %s", 
                               photo_file_path, photo_file_path.stat().st_size, photo_url)
                    # Сохраняем URL в photo_file_id (переиспользуем поле)
                    photo_file_id = photo_url
                else:
                    logger.error("Файл не был сохранен: %s", photo_file_path)
                    photo_file_id = None
            except Exception as e:
                logger.error("Ошибка при скачивании фото из поста: %s", e, exc_info=True)
                photo_file_id = None
        else:
            photo_file_id = None

        # Дата сообщения
        post_date = message.date if message.date else datetime.now()

        # Сохраняем в БД
        try:
            post_id = self.db.add_source_post(
                channel_id=channel_id,
                message_id=message_id,
                text_original=text,
                date=post_date,
                photo_file_id=photo_file_id,
            )

            if post_id:
                logger.info(
                    "Новый пост сохранён: channel_id=%s, message_id=%s, post_id=%s, "
                    "text_preview=%.100s...",
                    channel_id,
                    message_id,
                    post_id,
                    text,
                )
            else:
                logger.debug("Пост уже существует (дубль): channel_id=%s, message_id=%s", 
                            channel_id, message_id)
        except Exception as e:
            logger.error(
                "Ошибка при сохранении поста: channel_id=%s, message_id=%s, error=%s",
                channel_id,
                message_id,
                e,
                exc_info=True,
            )

    async def stop(self) -> None:
        """Остановить клиент Telethon."""
        if self.client:
            logger.info("Остановка Telethon клиента...")
            await self.client.disconnect()
            logger.info("Telethon клиент остановлен")

    async def run_forever(self) -> None:
        """Запустить клиент и работать бесконечно."""
        await self.start()
        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        finally:
            await self.stop()


async def main():
    """Тестовая функция для запуска слушателя."""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db = Database(config.DATABASE_PATH)
    listener = TelethonListener(db)

    try:
        await listener.run_forever()
    except Exception as e:
        logger.error("Критическая ошибка: %s", e, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())


