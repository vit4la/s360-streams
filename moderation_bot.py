"""
Бот для модерации черновиков постов.
Операторы получают черновики, могут их одобрить, отредактировать или отклонить.
"""

import asyncio
import logging
import re
from typing import Dict, Optional, Set, List
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config_moderation as config
from database import Database

logger = logging.getLogger(__name__)


class ModerationBot:
    """Класс для бота модерации."""

    def __init__(self, db: Database):
        """Инициализация бота.

        Args:
            db: Экземпляр Database для работы с БД
        """
        self.db = db
        self.app: Optional[Application] = None
        self.running = False
        
        # Состояния операторов: {user_id: draft_id} - какой черновик сейчас редактируется
        self.editing_states: Dict[int, int] = {}
        
        # Состояния публикации: {user_id: (draft_id, selected_channels)} - ожидание картинки
        self.publishing_states: Dict[int, tuple] = {}
        
        # Отправленные черновики: {draft_id: Set[user_id]} - кому уже отправлен
        self.sent_drafts: Dict[int, Set[int]] = {}

    def _is_moderator(self, user_id: int) -> bool:
        """Проверить, является ли пользователь модератором.

        Args:
            user_id: ID пользователя

        Returns:
            True, если пользователь модератор
        """
        return user_id in config.MODERATOR_IDS

    def _format_draft_message(self, draft: Dict) -> str:
        """Форматировать сообщение с черновиком для оператора.

        Args:
            draft: Словарь с данными черновика

        Returns:
            Отформатированное сообщение
        """
        # Ссылка на оригинал (если есть username канала)
        channel_id = draft["channel_id"]
        message_id = draft["message_id"]
        
        if channel_id.startswith("@"):
            source_link = f"https://t.me/{channel_id[1:]}/{message_id}"
            source_info = f"Источник: {channel_id} / [Ссылка]({source_link})"
        else:
            source_info = f"Источник: {channel_id} (ID: {message_id})"

        # Оригинальный текст (обрезаем до 400 символов)
        original_text = draft["text_original"]
        if len(original_text) > config.ORIGINAL_TEXT_PREVIEW_LENGTH:
            original_preview = (
                original_text[:config.ORIGINAL_TEXT_PREVIEW_LENGTH] + "..."
            )
        else:
            original_preview = original_text

        # Вариант GPT
        title = draft["title"]
        body = draft["body"]
        hashtags = draft["hashtags"]

        message = f"""*{source_info}*

*Оригинал:*
{original_preview}

*Вариант GPT:*
*{title}*

{body}

{hashtags}"""

        return message

    def _parse_hashtags_from_text(self, text: str) -> tuple[str, str]:
        """Парсить хэштеги из текста оператора.

        Args:
            text: Текст от оператора

        Returns:
            Кортеж (текст_без_хэштегов, хэштеги_строка)
        """
        # Ищем все хэштеги в тексте
        hashtag_pattern = r'#\w+'
        hashtags = re.findall(hashtag_pattern, text)
        hashtags_str = " ".join(hashtags) if hashtags else ""

        # Удаляем хэштеги из текста
        text_without_hashtags = re.sub(hashtag_pattern, "", text).strip()

        return text_without_hashtags, hashtags_str

    def _parse_title_and_body(self, text: str) -> tuple[str, str]:
        """Парсить заголовок и тело из текста оператора.

        Предполагаем, что первая строка - заголовок, остальное - тело.

        Args:
            text: Текст от оператора

        Returns:
            Кортеж (заголовок, тело)
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        
        if not lines:
            return "", ""
        
        # Первая строка - заголовок
        title = lines[0]
        
        # Остальное - тело
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        
        return title, body

    async def _send_draft_to_moderators(self, draft: Dict) -> None:
        """Отправить черновик всем модераторам.

        Args:
            draft: Словарь с данными черновика
        """
        draft_id = draft["id"]
        message_text = self._format_draft_message(draft)

        # Кнопки действий
        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{draft_id}"),
                InlineKeyboardButton("✏️ Править", callback_data=f"edit:{draft_id}"),
                InlineKeyboardButton("🚫 Отклонить", callback_data=f"reject:{draft_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        sent_to = set()

        for moderator_id in config.MODERATOR_IDS:
            try:
                await self.app.bot.send_message(
                    chat_id=moderator_id,
                    text=message_text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
                sent_to.add(moderator_id)
                logger.info("Черновик отправлен модератору: draft_id=%s, moderator_id=%s", 
                           draft_id, moderator_id)
            except Exception as e:
                logger.error(
                    "Ошибка при отправке черновика модератору: draft_id=%s, "
                    "moderator_id=%s, error=%s",
                    draft_id,
                    moderator_id,
                    e,
                )

        # Сохраняем, кому отправлен черновик
        if sent_to:
            self.sent_drafts[draft_id] = sent_to

    async def _check_and_send_new_drafts(self) -> None:
        """Проверить новые черновики и отправить их модераторам."""
        pending_drafts = self.db.get_pending_draft_posts()

        for draft in pending_drafts:
            draft_id = draft["id"]
            
            # Если черновик уже отправлен всем модераторам, пропускаем
            if draft_id in self.sent_drafts:
                sent_to = self.sent_drafts[draft_id]
                if sent_to == set(config.MODERATOR_IDS):
                    continue

            # Отправляем черновик
            await self._send_draft_to_moderators(draft)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start."""
        user_id = update.effective_user.id

        if not self._is_moderator(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return

        await update.message.reply_text(
            "👋 Привет! Я бот для модерации постов.\n\n"
            "Я автоматически отправляю новые черновики на модерацию.\n"
            "Используйте кнопки под каждым черновиком для действий."
        )

        # Проверяем и отправляем новые черновики
        await self._check_and_send_new_drafts()

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик callback-запросов от inline-кнопок."""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id

        if not self._is_moderator(user_id):
            await query.edit_message_text("❌ У вас нет доступа к этому боту.")
            return

        data = query.data
        parts = data.split(":")
        action = parts[0]

        if action == "approve":
            draft_id = int(parts[1])
            draft = self.db.get_draft_post(draft_id)
            if not draft:
                await query.edit_message_text("❌ Черновик не найден.")
                return
            await self._handle_approve(query, draft_id, draft)
        elif action == "edit":
            draft_id = int(parts[1])
            draft = self.db.get_draft_post(draft_id)
            if not draft:
                await query.edit_message_text("❌ Черновик не найден.")
                return
            await self._handle_edit(query, draft_id, draft)
        elif action == "reject":
            draft_id = int(parts[1])
            await self._handle_reject(query, draft_id)
        elif action == "select_channel":
            draft_id = int(parts[1])
            channel_id = parts[2]
            await self._handle_channel_selection(query, draft_id, channel_id)
        elif action == "select_multiple":
            draft_id = int(parts[1])
            await self._handle_multiple_channel_selection(query, draft_id)
        elif action == "toggle_channel":
            draft_id = int(parts[1])
            channel_id = parts[2]
            await self._handle_toggle_channel(query, draft_id, channel_id)
        elif action == "publish_channels_done":
            draft_id = int(parts[1])
            await self._handle_publish_channels_done(query, draft_id)
        elif action == "publish_no_photo":
            draft_id = int(parts[1])
            await self._handle_publish_no_photo(query, draft_id)
        else:
            await query.edit_message_text("❌ Неизвестное действие.")

    async def _handle_approve(
        self, query, draft_id: int, draft: Dict
    ) -> None:
        """Обработать нажатие 'Опубликовать'."""
        user_id = query.from_user.id

        # Если один целевой канал, сразу переходим к выбору картинки
        if len(config.TARGET_CHANNEL_IDS) == 1:
            target_channel = config.TARGET_CHANNEL_IDS[0]
            self.publishing_states[user_id] = (draft_id, [target_channel])
            await query.edit_message_text(
                "📸 Если нужно, отправьте картинку одним сообщением.\n"
                "Если картинка не нужна — нажмите 'Без картинки'.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Без картинки", callback_data=f"publish_no_photo:{draft_id}")
                ]]),
            )
            return

        # Если несколько каналов, показываем выбор
        keyboard = []
        for channel_id in config.TARGET_CHANNEL_IDS:
            channel_name = channel_id if isinstance(channel_id, str) else str(channel_id)
            keyboard.append([
                InlineKeyboardButton(
                    f"📢 {channel_name}",
                    callback_data=f"select_channel:{draft_id}:{channel_id}"
                )
            ])

        # Кнопка для выбора нескольких каналов
        keyboard.append([
            InlineKeyboardButton(
                "📢 Выбрать несколько",
                callback_data=f"select_multiple:{draft_id}"
            )
        ])

        await query.edit_message_text(
            "📢 Выберите целевой канал(ы) для публикации:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_channel_selection(
        self, query, draft_id: int, channel_id: str
    ) -> None:
        """Обработать выбор одного канала."""
        user_id = query.from_user.id
        self.publishing_states[user_id] = (draft_id, [channel_id])

        await query.edit_message_text(
            "📸 Если нужно, отправьте картинку одним сообщением.\n"
            "Если картинка не нужна — нажмите 'Без картинки'.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Без картинки", callback_data=f"publish_no_photo:{draft_id}")
            ]]),
        )

    async def _handle_multiple_channel_selection(
        self, query, draft_id: int
    ) -> None:
        """Обработать выбор нескольких каналов."""
        user_id = query.from_user.id
        
        # Создаём чекбоксы для выбора каналов
        keyboard = []
        for channel_id in config.TARGET_CHANNEL_IDS:
            channel_name = channel_id if isinstance(channel_id, str) else str(channel_id)
            keyboard.append([
                InlineKeyboardButton(
                    f"☐ {channel_name}",
                    callback_data=f"toggle_channel:{draft_id}:{channel_id}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                "✅ Готово",
                callback_data=f"publish_channels_done:{draft_id}"
            )
        ])

        # Сохраняем состояние выбора каналов
        if user_id not in self.publishing_states:
            self.publishing_states[user_id] = (draft_id, [])

        await query.edit_message_text(
            "📢 Выберите каналы для публикации (можно несколько):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_toggle_channel(
        self, query, draft_id: int, channel_id: str
    ) -> None:
        """Переключить выбор канала."""
        user_id = query.from_user.id
        
        if user_id not in self.publishing_states:
            self.publishing_states[user_id] = (draft_id, [])

        _, selected_channels = self.publishing_states[user_id]
        
        if channel_id in selected_channels:
            selected_channels.remove(channel_id)
        else:
            selected_channels.append(channel_id)

        # Обновляем кнопки
        keyboard = []
        for ch_id in config.TARGET_CHANNEL_IDS:
            channel_name = ch_id if isinstance(ch_id, str) else str(ch_id)
            is_selected = ch_id in selected_channels
            prefix = "☑" if is_selected else "☐"
            keyboard.append([
                InlineKeyboardButton(
                    f"{prefix} {channel_name}",
                    callback_data=f"toggle_channel:{draft_id}:{ch_id}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                "✅ Готово",
                callback_data=f"publish_channels_done:{draft_id}"
            )
        ])

        await query.edit_message_text(
            "📢 Выберите каналы для публикации (можно несколько):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_publish_channels_done(self, query, draft_id: int) -> None:
        """Завершить выбор каналов и перейти к выбору картинки."""
        user_id = query.from_user.id
        
        if user_id not in self.publishing_states:
            await query.edit_message_text("❌ Ошибка: состояние потеряно.")
            return

        _, selected_channels = self.publishing_states[user_id]
        
        if not selected_channels:
            await query.edit_message_text("❌ Выберите хотя бы один канал.")
            return

        await query.edit_message_text(
            "📸 Если нужно, отправьте картинку одним сообщением.\n"
            "Если картинка не нужна — нажмите 'Без картинки'.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Без картинки", callback_data=f"publish_no_photo:{draft_id}")
            ]]),
        )

    async def _handle_publish_no_photo(self, query, draft_id: int) -> None:
        """Опубликовать без картинки."""
        user_id = query.from_user.id
        
        if user_id not in self.publishing_states:
            await query.edit_message_text("❌ Ошибка: состояние потеряно.")
            return

        _, selected_channels = self.publishing_states[user_id]
        await self._publish_draft(draft_id, selected_channels, photo=None, user_id=user_id)
        
        # Очищаем состояние
        del self.publishing_states[user_id]
        
        await query.edit_message_text("✅ Пост опубликован!")

    async def _handle_edit(self, query, draft_id: int, draft: Dict) -> None:
        """Обработать нажатие 'Править'."""
        user_id = query.from_user.id
        self.editing_states[user_id] = draft_id

        await query.edit_message_text(
            "✏️ Пришлите новый текст (заголовок + тело + хэштеги) одним сообщением.\n\n"
            "Формат:\n"
            "Первая строка — заголовок\n"
            "Остальные строки — текст\n"
            "Хэштеги можно указать в любом месте текста (начинаются с #)"
        )

    async def _handle_reject(self, query, draft_id: int) -> None:
        """Обработать нажатие 'Отклонить'."""
        self.db.mark_draft_rejected(draft_id)
        await query.edit_message_text("🚫 Черновик отклонён.")

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик текстовых сообщений и фото."""
        user_id = update.effective_user.id

        if not self._is_moderator(user_id):
            return

        # Проверяем, находится ли пользователь в режиме редактирования
        if user_id in self.editing_states:
            draft_id = self.editing_states[user_id]
            await self._handle_edit_text(update, draft_id)
            return

        # Проверяем, находится ли пользователь в режиме публикации (ожидание фото)
        if user_id in self.publishing_states:
            draft_id, selected_channels = self.publishing_states[user_id]
            
            # Проверяем, есть ли фото
            if update.message.photo:
                photo = update.message.photo[-1]  # Берём самое большое фото
                photo_file_id = photo.file_id
                await self._publish_draft(
                    draft_id, selected_channels, photo_file_id=photo_file_id, user_id=user_id
                )
                
                # Очищаем состояние
                del self.publishing_states[user_id]
                
                await update.message.reply_text("✅ Пост опубликован с картинкой!")
            else:
                await update.message.reply_text(
                    "📸 Отправьте картинку или нажмите 'Без картинки' в предыдущем сообщении."
                )
            return

        # Если это не ответ на действие, проверяем новые черновики
        await self._check_and_send_new_drafts()

    async def _handle_edit_text(self, update: Update, draft_id: int) -> None:
        """Обработать редактирование текста оператором."""
        user_id = update.effective_user.id
        text = update.message.text

        if not text:
            await update.message.reply_text("❌ Отправьте текстовое сообщение.")
            return

        # Парсим хэштеги
        text_without_hashtags, hashtags_str = self._parse_hashtags_from_text(text)

        # Парсим заголовок и тело
        title, body = self._parse_title_and_body(text_without_hashtags)

        if not title:
            await update.message.reply_text(
                "❌ Не удалось определить заголовок. "
                "Убедитесь, что первая строка — это заголовок."
            )
            return

        # Обновляем черновик
        self.db.update_draft_post(
            draft_id=draft_id,
            title=title,
            body=body,
            hashtags=hashtags_str,
        )

        # Получаем обновлённый черновик
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            await update.message.reply_text("❌ Ошибка: черновик не найден.")
            return

        # Показываем превью с теми же кнопками
        message_text = self._format_draft_message(draft)
        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{draft_id}"),
                InlineKeyboardButton("✏️ Править", callback_data=f"edit:{draft_id}"),
                InlineKeyboardButton("🚫 Отклонить", callback_data=f"reject:{draft_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "✅ Текст обновлён. Превью:",
            reply_markup=reply_markup,
        )
        await update.message.reply_text(
            message_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

        # Очищаем состояние редактирования (но можно редактировать снова)
        # Не удаляем, чтобы можно было редактировать несколько раз

    async def _publish_draft(
        self,
        draft_id: int,
        target_channels: List[str],
        photo_file_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> None:
        """Опубликовать черновик в целевые каналы.

        Args:
            draft_id: ID черновика
            target_channels: Список ID целевых каналов
            photo_file_id: file_id фото (опционально)
            user_id: ID пользователя (для логирования)
        """
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            logger.error("Черновик не найден для публикации: draft_id=%s", draft_id)
            return

        title = draft["title"]
        body = draft["body"]
        hashtags = draft["hashtags"]

        # Формируем текст поста
        post_text = f"{title}\n\n{body}\n\n{hashtags}"

        # Публикуем в каждый канал
        published_count = 0
        errors = []

        for channel_id in target_channels:
            try:
                if photo_file_id:
                    # Отправляем с фото
                    message = await self.app.bot.send_photo(
                        chat_id=channel_id,
                        photo=photo_file_id,
                        caption=post_text,
                    )
                else:
                    # Отправляем текстовое сообщение
                    message = await self.app.bot.send_message(
                        chat_id=channel_id,
                        text=post_text,
                    )

                # Сохраняем информацию о публикации (только для первого успешного канала)
                # Если нужно сохранять для всех каналов, можно изменить логику
                if published_count == 0:
                    self.db.mark_draft_published(
                        draft_id=draft_id,
                        target_chat_id=str(channel_id),
                        target_message_id=message.message_id,
                    )

                published_count += 1
                logger.info(
                    "Пост опубликован: draft_id=%s, channel_id=%s, message_id=%s",
                    draft_id,
                    channel_id,
                    message.message_id,
                )

            except Exception as e:
                error_msg = f"Канал {channel_id}: {str(e)}"
                errors.append(error_msg)
                logger.error(
                    "Ошибка при публикации в канал: draft_id=%s, channel_id=%s, error=%s",
                    draft_id,
                    channel_id,
                    e,
                    exc_info=True,
                )

        # Логируем результат
        if published_count > 0:
            logger.info(
                "Публикация завершена: draft_id=%s, опубликовано=%s/%s, ошибок=%s",
                draft_id,
                published_count,
                len(target_channels),
                len(errors),
            )

        if errors and user_id:
            error_text = "\n".join(errors)
            try:
                await self.app.bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Ошибки при публикации:\n{error_text}",
                )
            except Exception:
                pass

    async def auto_send_loop(self, interval: float = 10.0) -> None:
        """Автоматически проверять и отправлять новые черновики модераторам.

        Args:
            interval: Интервал между проверками (секунды)
        """
        self.running = True
        logger.info("Автоматическая отправка черновиков запущена (интервал: %s сек)", interval)

        while self.running:
            try:
                await self._check_and_send_new_drafts()
            except Exception as e:
                logger.error("Ошибка при автоматической отправке черновиков: %s", e, exc_info=True)

            await asyncio.sleep(interval)

    async def start(self) -> None:
        """Запустить бота."""
        logger.info("Запуск бота модерации...")

        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

        # Регистрируем обработчики
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))
        self.app.add_handler(MessageHandler(filters.ALL, self.message_handler))

        # Запускаем бота
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        logger.info("Бот модерации запущен")

        # Запускаем автоматическую отправку черновиков
        asyncio.create_task(self.auto_send_loop(interval=10.0))

    async def stop(self) -> None:
        """Остановить бота."""
        logger.info("Остановка бота модерации...")
        self.running = False

        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

        logger.info("Бот модерации остановлен")


async def main():
    """Тестовая функция для запуска бота."""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db = Database(config.DATABASE_PATH)
    bot = ModerationBot(db)

    try:
        await bot.start()
        # Работаем бесконечно
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
        await bot.stop()
    except Exception as e:
        logger.error("Критическая ошибка: %s", e, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())

