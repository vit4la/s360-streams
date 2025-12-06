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
import requests

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
        final_image_url = draft.get("final_image_url")
        image_query = draft.get("image_query")

        # Кнопки действий
        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{draft_id}"),
                InlineKeyboardButton("✏️ Править", callback_data=f"edit:{draft_id}"),
                InlineKeyboardButton("🚫 Отклонить", callback_data=f"reject:{draft_id}"),
            ]
        ]
        
        # Добавляем кнопку "Другая картинка", если есть image_query
        if image_query:
            keyboard.append([
                InlineKeyboardButton("♻️ Другая картинка", callback_data=f"change_image:{draft_id}")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)

        sent_to = set()

        for moderator_id in config.MODERATOR_IDS:
            try:
                # Если есть стилизованная картинка, отправляем её с текстом
                if final_image_url:
                    try:
                        await self.app.bot.send_photo(
                            chat_id=moderator_id,
                            photo=final_image_url,  # Сервис уже возвращает полный URL
                            caption=message_text,
                            parse_mode="Markdown",
                            reply_markup=reply_markup,
                        )
                    except Exception as photo_error:
                        # Если не удалось отправить фото, отправляем только текст
                        logger.warning("Не удалось отправить фото, отправляем только текст: %s", photo_error)
                        await self.app.bot.send_message(
                            chat_id=moderator_id,
                            text=message_text,
                            parse_mode="Markdown",
                            reply_markup=reply_markup,
                        )
                else:
                    # Нет картинки - отправляем только текст
                    await self.app.bot.send_message(
                        chat_id=moderator_id,
                        text=message_text,
                        parse_mode="Markdown",
                        reply_markup=reply_markup,
                    )
                
                sent_to.add(moderator_id)
                logger.info("Черновик отправлен модератору: draft_id=%s, moderator_id=%s, has_image=%s", 
                           draft_id, moderator_id, bool(final_image_url))
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
        logger.info("Получен callback: user_id=%s, data=%s", user_id, data)
        parts = data.split(":")
        action = parts[0]
        logger.debug("Действие: %s, части: %s", action, parts)

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
        elif action == "publish_source_photo":
            draft_id = int(parts[1])
            await self._handle_publish_source_photo(query, draft_id)
        elif action == "publish_custom_photo":
            draft_id = int(parts[1])
            await self._handle_publish_custom_photo(query, draft_id)
        elif action == "change_image":
            draft_id = int(parts[1])
            await self._handle_change_image(query, draft_id)
        elif action == "select_image":
            draft_id = int(parts[1])
            image_index = int(parts[2])
            await self._handle_select_image(query, draft_id, image_index)
        elif action == "select_image_for_publish":
            draft_id = int(parts[1])
            image_index = int(parts[2])
            logger.info("Обработка select_image_for_publish: draft_id=%s, image_index=%s", draft_id, image_index)
            await self._handle_select_image_for_publish(query, draft_id, image_index)
        elif action == "select_image":
            draft_id = int(parts[1])
            image_index = int(parts[2])
            logger.info("Обработка select_image: draft_id=%s, image_index=%s", draft_id, image_index)
            await self._handle_select_image(query, draft_id, image_index)
        else:
            logger.warning("Неизвестное действие в callback: %s, data=%s", action, data)
            await query.edit_message_text(f"❌ Неизвестное действие: {action}")
            await query.answer(f"Неизвестное действие: {action}")

    async def _handle_approve(
        self, query, draft_id: int, draft: Dict
    ) -> None:
        """Обработать нажатие 'Опубликовать'."""
        user_id = query.from_user.id

        # Если один целевой канал, сразу переходим к выбору картинки
        if len(config.TARGET_CHANNEL_IDS) == 1:
            target_channel = config.TARGET_CHANNEL_IDS[0]
            self.publishing_states[user_id] = (draft_id, [target_channel])
            
            # Если есть стилизованная картинка, сразу публикуем
            if draft.get("final_image_url"):
                await self._publish_draft(draft_id, [target_channel])
                await query.edit_message_text("✅ Пост опубликован!")
                return
            
            # Если нет стилизованной картинки, но есть картинки из Pexels - показываем для выбора
            import json
            pexels_images_json = draft.get("pexels_images_json")
            if pexels_images_json:
                try:
                    pexels_images = json.loads(pexels_images_json)
                    if pexels_images and len(pexels_images) > 0:
                        await query.edit_message_text("📸 Выберите картинку для публикации:")
                        # Показываем картинки для выбора
                        for idx, pexels_img in enumerate(pexels_images):
                            keyboard = [[
                                InlineKeyboardButton(
                                    "✅ Выбрать эту",
                                    callback_data=f"select_image_for_publish:{draft_id}:{idx}"
                                )
                            ]]
                            try:
                                await self.app.bot.send_photo(
                                    chat_id=query.from_user.id,
                                    photo=pexels_img["url"],
                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                )
                            except Exception as e:
                                logger.error("Ошибка при отправке картинки: %s", e)
                        return
                except json.JSONDecodeError:
                    pass
            
            # Если нет картинок из Pexels, показываем стандартные варианты
            source_photo_file_id = draft.get("photo_file_id")
            
            keyboard = []
            if source_photo_file_id:
                keyboard.append([
                    InlineKeyboardButton("🖼️ С исходной картинкой", callback_data=f"publish_source_photo:{draft_id}")
                ])
            keyboard.append([
                InlineKeyboardButton("📸 Прикрепить свою", callback_data=f"publish_custom_photo:{draft_id}"),
                InlineKeyboardButton("Без картинки", callback_data=f"publish_no_photo:{draft_id}")
            ])
            
            await query.edit_message_text(
                "📸 Выберите вариант публикации:",
                reply_markup=InlineKeyboardMarkup(keyboard),
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

        # Проверяем есть ли исходная картинка
        draft = self.db.get_draft_post(draft_id)
        source_photo_file_id = draft.get("photo_file_id") if draft else None
        
        keyboard = []
        if source_photo_file_id:
            keyboard.append([
                InlineKeyboardButton("🖼️ С исходной картинкой", callback_data=f"publish_source_photo:{draft_id}")
            ])
        keyboard.append([
            InlineKeyboardButton("📸 Прикрепить свою", callback_data=f"publish_custom_photo:{draft_id}"),
            InlineKeyboardButton("Без картинки", callback_data=f"publish_no_photo:{draft_id}")
        ])

        await query.edit_message_text(
            "📸 Выберите вариант публикации:",
            reply_markup=InlineKeyboardMarkup(keyboard),
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

        # Проверяем есть ли исходная картинка
        draft = self.db.get_draft_post(draft_id)
        source_photo_file_id = draft.get("photo_file_id") if draft else None
        
        keyboard = []
        if source_photo_file_id:
            keyboard.append([
                InlineKeyboardButton("🖼️ С исходной картинкой", callback_data=f"publish_source_photo:{draft_id}")
            ])
        keyboard.append([
            InlineKeyboardButton("📸 Прикрепить свою", callback_data=f"publish_custom_photo:{draft_id}"),
            InlineKeyboardButton("Без картинки", callback_data=f"publish_no_photo:{draft_id}")
        ])
        
        await query.edit_message_text(
            "📸 Выберите вариант публикации:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_publish_source_photo(self, query, draft_id: int) -> None:
        """Опубликовать с исходной картинкой."""
        user_id = query.from_user.id
        
        if user_id not in self.publishing_states:
            await query.edit_message_text("❌ Ошибка: состояние потеряно.")
            return

        draft = self.db.get_draft_post(draft_id)
        if not draft:
            await query.edit_message_text("❌ Черновик не найден.")
            return

        # Получаем file_id картинки из исходного поста
        # Пробуем переслать сообщение из исходного канала в личку оператора, чтобы получить file_id
        source_channel_id = draft.get("channel_id")
        source_message_id = draft.get("message_id")
        
        if not source_channel_id or not source_message_id:
            await query.edit_message_text("❌ Не удалось определить исходный пост.")
            return

        photo_file_id = None
        
        try:
            # Пересылаем сообщение в личку оператора, чтобы получить file_id
            # Это работает даже если бот не админ в канале, если канал публичный
            forwarded = await self.app.bot.forward_message(
                chat_id=user_id,
                from_chat_id=source_channel_id,
                message_id=source_message_id,
            )
            
            # Извлекаем file_id картинки из пересланного сообщения
            if forwarded.photo:
                photo_file_id = forwarded.photo[-1].file_id
            elif forwarded.document and forwarded.document.mime_type and forwarded.document.mime_type.startswith("image/"):
                photo_file_id = forwarded.document.file_id
            
            # Удаляем пересланное сообщение
            try:
                await self.app.bot.delete_message(chat_id=user_id, message_id=forwarded.message_id)
            except Exception:
                pass  # Игнорируем ошибку удаления
                
        except Exception as e:
            logger.error("Ошибка при получении картинки из исходного поста: %s", e, exc_info=True)
            await query.edit_message_text(
                "❌ Не удалось получить картинку из исходного поста.\n"
                "Возможные причины:\n"
                "• Канал приватный и бот не имеет доступа\n"
                "• В исходном посте нет картинки\n\n"
                "Попробуйте прикрепить картинку вручную."
            )
            return
        
        if not photo_file_id:
            await query.edit_message_text("❌ У исходного поста нет картинки. Попробуйте прикрепить картинку вручную.")
            return

        _, selected_channels = self.publishing_states[user_id]
        await self._publish_draft(draft_id, selected_channels, photo_file_id=photo_file_id, user_id=user_id)
        
        # Очищаем состояние
        del self.publishing_states[user_id]
        
        await query.edit_message_text("✅ Пост опубликован с исходной картинкой!")

    async def _handle_publish_custom_photo(self, query, draft_id: int) -> None:
        """Перейти в режим ожидания своей картинки."""
        user_id = query.from_user.id
        
        if user_id not in self.publishing_states:
            await query.edit_message_text("❌ Ошибка: состояние потеряно.")
            return

        await query.edit_message_text(
            "📸 Отправьте картинку одним сообщением.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Отмена", callback_data=f"publish_no_photo:{draft_id}")
            ]]),
        )

    async def _handle_publish_no_photo(self, query, draft_id: int) -> None:
        """Опубликовать без картинки."""
        user_id = query.from_user.id
        
        if user_id not in self.publishing_states:
            await query.edit_message_text("❌ Ошибка: состояние потеряно.")
            return

        _, selected_channels = self.publishing_states[user_id]
        await self._publish_draft(draft_id, selected_channels, photo_file_id=None, user_id=user_id)
        
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

    async def _handle_change_image(self, query, draft_id: int) -> None:
        """Обработать нажатие 'Другая картинка' - показать 3 новые картинки для выбора."""
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            await query.edit_message_text("❌ Черновик не найден.")
            return

        image_query = draft.get("image_query")
        if not image_query:
            await query.edit_message_text("❌ Запрос для поиска картинки не найден.")
            return

        await query.edit_message_text("🔄 Ищу новые картинки...")

        # Запрос к Pexels API
        pexels_images = self._search_pexels_images(image_query)
        if not pexels_images or len(pexels_images) == 0:
            await query.edit_message_text("❌ Не удалось найти картинки. Попробуйте позже.")
            return

        # Сохраняем картинки в БД
        import json
        pexels_images_json = json.dumps(pexels_images, ensure_ascii=False)
        self.db.update_draft_post(draft_id, pexels_images_json=pexels_images_json)

        # Показываем исходные картинки из Pexels для выбора (без стилизации)
        await query.edit_message_text(
            f"📸 Найдено {len(pexels_images)} картинок. Выберите одну:"
        )

        # Отправляем каждую исходную картинку с кнопкой выбора
        for idx, pexels_img in enumerate(pexels_images):
            keyboard = [[
                InlineKeyboardButton(
                    "✅ Выбрать эту",
                    callback_data=f"select_image:{draft_id}:{idx}"
                )
            ]]

            try:
                await self.app.bot.send_photo(
                    chat_id=query.from_user.id,
                    photo=pexels_img["url"],  # Исходная картинка из Pexels
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception as e:
                logger.error("Ошибка при отправке картинки для выбора: %s", e)

    async def _handle_select_image(self, query, draft_id: int, image_index: int) -> None:
        """Обработать выбор картинки оператором."""
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            await query.edit_message_text("❌ Черновик не найден.")
            return

        # Получаем картинки из БД или из Pexels
        import json
        pexels_images = None
        pexels_images_json = draft.get("pexels_images_json")
        if pexels_images_json:
            try:
                pexels_images = json.loads(pexels_images_json)
            except json.JSONDecodeError:
                logger.warning("Не удалось распарсить pexels_images_json для черновика: draft_id=%s", draft_id)
        
        # Если картинок нет в БД, запрашиваем заново
        if not pexels_images:
            image_query = draft.get("image_query")
            if not image_query:
                await query.edit_message_text("❌ Запрос для поиска картинки не найден.")
                return
            pexels_images = self._search_pexels_images(image_query)
            if pexels_images:
                pexels_images_json = json.dumps(pexels_images, ensure_ascii=False)
                self.db.update_draft_post(draft_id, pexels_images_json=pexels_images_json)

        if not pexels_images or image_index >= len(pexels_images):
            await query.edit_message_text("❌ Картинка не найдена.")
            return

        # Стилизуем выбранную картинку
        await query.edit_message_text("🎨 Стилизую картинку...")
        selected_image_url = pexels_images[image_index]["url"]
        final_url = self._render_image(selected_image_url, draft["title"])

        if not final_url:
            await query.edit_message_text("❌ Не удалось стилизовать картинку.")
            return

        # Обновляем final_image_url в БД
        self.db.update_draft_post(draft_id, final_image_url=final_url)

        # Показываем обновлённый черновик
        updated_draft = self.db.get_draft_post(draft_id)
        message_text = self._format_draft_message(updated_draft)

        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{draft_id}"),
                InlineKeyboardButton("✏️ Править", callback_data=f"edit:{draft_id}"),
                InlineKeyboardButton("🚫 Отклонить", callback_data=f"reject:{draft_id}"),
            ]
        ]
        if updated_draft.get("image_query"):
            keyboard.append([
                InlineKeyboardButton("♻️ Другая картинка", callback_data=f"change_image:{draft_id}")
            ])

        try:
            await query.edit_message_caption(
                caption=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except:
            # Если не получилось обновить caption, отправляем новое сообщение
            await self.app.bot.send_photo(
                chat_id=query.from_user.id,
                photo=final_url,  # Сервис уже возвращает полный URL
                caption=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        await query.answer("✅ Картинка обновлена!")

    async def _handle_select_image_for_publish(
        self, query, draft_id: int, image_index: int
    ) -> None:
        """Обработать выбор картинки для публикации (стилизует и сразу публикует)."""
        logger.info("_handle_select_image_for_publish: draft_id=%s, image_index=%s", draft_id, image_index)
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            logger.error("Черновик не найден: draft_id=%s", draft_id)
            await query.edit_message_text("❌ Черновик не найден.")
            return

        # Получаем картинки из БД
        import json
        pexels_images = None
        # Используем правильный доступ к полям (sqlite3.Row или dict)
        pexels_images_json = draft.get("pexels_images_json") if isinstance(draft, dict) else (draft["pexels_images_json"] if "pexels_images_json" in draft.keys() else None)
        logger.debug("pexels_images_json: %s", pexels_images_json[:100] if pexels_images_json else None)
        if pexels_images_json:
            try:
                pexels_images = json.loads(pexels_images_json)
                logger.info("Загружено картинок из Pexels: %s", len(pexels_images))
            except json.JSONDecodeError as e:
                logger.error("Ошибка парсинга pexels_images_json: %s", e)
                pass

        if not pexels_images or image_index >= len(pexels_images):
            logger.error("Картинка не найдена: image_index=%s, всего картинок=%s", image_index, len(pexels_images) if pexels_images else 0)
            await query.edit_message_text("❌ Картинка не найдена.")
            return

        # Стилизуем выбранную картинку
        await query.edit_message_text("🎨 Стилизую картинку...")
        selected_image_url = pexels_images[image_index]["url"]
        logger.info("Выбрана картинка: %s", selected_image_url)
        title = draft.get("title") if isinstance(draft, dict) else draft["title"]
        final_url = self._render_image(selected_image_url, title)

        if not final_url:
            logger.error("Не удалось стилизовать картинку: %s", selected_image_url)
            await query.edit_message_text("❌ Не удалось стилизовать картинку.")
            return

        logger.info("Картинка стилизована: %s", final_url)
        # Обновляем final_image_url в БД
        self.db.update_draft_post(draft_id, final_image_url=final_url)

        # Публикуем черновик
        user_id = query.from_user.id
        if user_id in self.publishing_states:
            _, target_channels = self.publishing_states[user_id]
            await self._publish_draft(draft_id, target_channels)
            await query.edit_message_text("✅ Пост опубликован!")
            del self.publishing_states[user_id]
        else:
            await query.edit_message_text("❌ Ошибка: состояние публикации не найдено.")

    def _search_pexels_images(self, query: str) -> Optional[List[Dict[str, str]]]:
        """Поиск картинок через Pexels API (синхронная функция).

        Args:
            query: Поисковый запрос

        Returns:
            Список словарей с URL картинок или None при ошибке
        """
        if not query:
            return None

        url = config.PEXELS_API_URL
        headers = {
            "Authorization": config.PEXELS_API_KEY
        }
        params = {
            "query": query,
            "per_page": config.PEXELS_PER_PAGE,
            "orientation": "landscape"
        }

        try:
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
                return None

            image_urls = []
            for photo in photos:
                src = photo.get("src", {})
                url = src.get("large") or src.get("landscape") or src.get("medium")
                if url:
                    image_urls.append({
                        "url": url,
                        "photographer": photo.get("photographer", "Unknown"),
                        "id": photo.get("id")
                    })

            return image_urls

        except Exception as e:
            logger.error("Ошибка при запросе к Pexels API: %s", e)
            return None

    def _render_image(self, image_url: str, title: str) -> Optional[str]:
        """Вызвать сервис стилизации изображения (синхронная функция).

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
            resp = requests.post(service_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            final_url = data.get("final_image_url")
            return final_url

        except Exception as e:
            logger.error("Ошибка при запросе к сервису стилизации: %s", e)
            return None

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
            photo_file_id: file_id фото из исходного поста (опционально, используется только если нет final_image_url)
            user_id: ID пользователя (для логирования)
        """
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            logger.error("Черновик не найден для публикации: draft_id=%s", draft_id)
            return

        title = draft["title"]
        body = draft["body"]
        hashtags = draft["hashtags"]
        final_image_url = draft.get("final_image_url")

        # Формируем текст поста
        post_text = f"{title}\n\n{body}\n\n{hashtags}"

        # Определяем, какую картинку использовать
        # Приоритет: final_image_url > photo_file_id
        image_to_use = None
        if final_image_url:
            image_to_use = final_image_url  # Сервис уже возвращает полный URL
        elif photo_file_id:
            image_to_use = photo_file_id

        # Публикуем в каждый канал
        published_count = 0
        errors = []

        for channel_id in target_channels:
            try:
                if image_to_use:
                    # Отправляем с фото
                    # Если это URL (стилизованная картинка), используем URL
                    # Если это file_id (исходная картинка), используем file_id
                    if image_to_use.startswith("http://") or image_to_use.startswith("https://"):
                        message = await self.app.bot.send_photo(
                            chat_id=channel_id,
                            photo=image_to_use,
                            caption=post_text,
                        )
                    else:
                        # Это file_id
                        message = await self.app.bot.send_photo(
                            chat_id=channel_id,
                            photo=image_to_use,
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
                # Продолжаем публикацию в другие каналы, даже если один не удался
                continue

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
            try:
                if self.app.updater and self.app.updater.running:
                    await self.app.updater.stop()
            except Exception as e:
                logger.debug("Ошибка при остановке updater: %s", e)
            
            try:
                await self.app.stop()
            except Exception as e:
                logger.debug("Ошибка при остановке app: %s", e)
            
            try:
                await self.app.shutdown()
            except Exception as e:
                logger.debug("Ошибка при shutdown app: %s", e)

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

