"""
Главный модуль для запуска всех компонентов системы модерации постов.
"""

import asyncio
import logging
import signal
import sys

import config_moderation as config
from database import Database
from telethon_listener import TelethonListener
from gpt_worker import GPTWorker
from moderation_bot import ModerationBot
from logger_setup import setup_logging

logger = logging.getLogger(__name__)


class Application:
    """Главный класс приложения, управляющий всеми компонентами."""

    def __init__(self):
        """Инициализация приложения."""
        self.db = Database(config.DATABASE_PATH)
        self.telethon_listener: TelethonListener | None = None
        self.gpt_worker: GPTWorker | None = None
        self.moderation_bot: ModerationBot | None = None
        self.running = False

    async def start(self) -> None:
        """Запустить все компоненты."""
        logger.info("Запуск приложения...")

        try:
            # Запускаем Telethon слушатель (в фоне)
            logger.info("Запуск Telethon слушателя...")
            self.telethon_listener = TelethonListener(self.db)
            asyncio.create_task(self.telethon_listener.run_forever())

            # Запускаем GPT воркер (в фоне)
            logger.info("Запуск GPT воркера...")
            self.gpt_worker = GPTWorker(self.db)
            asyncio.create_task(self.gpt_worker.process_loop(interval=5.0))

            # Запускаем бота модерации (в фоне)
            logger.info("Запуск бота модерации...")
            self.moderation_bot = ModerationBot(self.db)
            await self.moderation_bot.start()

            self.running = True
            logger.info("Все компоненты запущены успешно")

        except Exception as e:
            logger.error("Ошибка при запуске компонентов: %s", e, exc_info=True)
            await self.stop()
            raise

    async def stop(self) -> None:
        """Остановить все компоненты."""
        logger.info("Остановка приложения...")
        self.running = False

        try:
            if self.gpt_worker:
                self.gpt_worker.stop()

            if self.moderation_bot:
                await self.moderation_bot.stop()

            if self.telethon_listener:
                await self.telethon_listener.stop()

            logger.info("Все компоненты остановлены")
        except Exception as e:
            logger.error("Ошибка при остановке компонентов: %s", e, exc_info=True)

    async def run(self) -> None:
        """Запустить приложение и работать до получения сигнала остановки."""
        await self.start()

        try:
            # Работаем бесконечно, пока не получим сигнал остановки
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Получен сигнал KeyboardInterrupt")
        finally:
            await self.stop()


def main() -> None:
    """Точка входа в приложение."""
    # Настраиваем логирование
    setup_logging()

    logger.info("=" * 60)
    logger.info("Запуск системы модерации постов")
    logger.info("=" * 60)

    # Проверяем конфигурацию
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Не задан TELEGRAM_BOT_TOKEN в config_moderation.py")
        sys.exit(1)

    if not config.OPENAI_API_KEY or config.OPENAI_API_KEY == "sk-your-api-key-here":
        logger.error("Не задан OPENAI_API_KEY в config_moderation.py")
        sys.exit(1)

    if not config.MODERATOR_IDS or config.MODERATOR_IDS == [123456789]:
        logger.error("Не заданы MODERATOR_IDS в config_moderation.py")
        sys.exit(1)

    if not config.SOURCE_CHANNEL_IDS or config.SOURCE_CHANNEL_IDS == ["@channel1"]:
        logger.error("Не заданы SOURCE_CHANNEL_IDS в config_moderation.py")
        sys.exit(1)

    if not config.TARGET_CHANNEL_IDS or config.TARGET_CHANNEL_IDS == ["@targetchannel1"]:
        logger.error("Не заданы TARGET_CHANNEL_IDS в config_moderation.py")
        sys.exit(1)

    # Создаём и запускаем приложение
    app = Application()

    # Обработчик сигналов для корректной остановки
    def signal_handler(signum, frame):
        logger.info("Получен сигнал %s", signum)
        asyncio.create_task(app.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(app.run())
    except Exception as e:
        logger.error("Критическая ошибка: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

