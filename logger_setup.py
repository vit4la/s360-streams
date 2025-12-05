"""
Настройка системы логирования с ротацией файлов.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config_moderation as config


def setup_logging() -> None:
    """Настроить систему логирования."""
    # Создаём директорию для логов, если её нет
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(exist_ok=True)

    # Путь к файлу лога
    log_file = log_dir / config.LOG_FILE

    # Настраиваем формат логов
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Получаем уровень логирования из конфига
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    # Настраиваем root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Удаляем существующие обработчики
    root_logger.handlers.clear()

    # Обработчик для файла с ротацией
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Добавляем обработчики
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.info("Система логирования инициализирована: %s", log_file)


