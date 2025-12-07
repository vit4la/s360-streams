"""
Бот для модерации черновиков постов.
Операторы получают черновики, могут их одобрить, отредактировать или отклонить.
"""

import asyncio
import logging
import os
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

        # Вариант GPT - теперь body содержит HTML-текст
        body = draft["body"]
        
        # Проверяем, содержит ли body HTML-теги (новый формат) или это старый формат
        has_html_tags = (
            "<b>" in body or "</b>" in body or
            "<i>" in body or "</i>" in body or
            "<u>" in body or "</u>" in body or
            "<s>" in body or "</s>" in body or
            "<a " in body or "</a>" in body
        )
        
        if has_html_tags:
            # Новый формат - HTML (используем HTML для всего сообщения)
            # Экранируем HTML-спецсимволы в original_preview и source_info
            import html
            escaped_source = html.escape(source_info)
            escaped_original = html.escape(original_preview)
            message = f"""<b>{escaped_source}</b>

<b>Оригинал:</b>
{escaped_original}

<b>Вариант GPT:</b>
{body}"""
        else:
            # Старый формат - Markdown (для обратной совместимости)
            title = draft.get("title", "")
            hashtags = draft.get("hashtags", "")
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
        
        # Логируем для отладки
        body = draft.get("body", "")
        logger.info("_send_draft_to_moderators: draft_id=%s, body содержит эмоджи 🎾: %s, body (first 200): %s", 
                   draft_id, "🎾" in body, body[:200])
        logger.info("_send_draft_to_moderators: message_text содержит эмоджи 🎾: %s, message_text (first 200): %s", 
                   "🎾" in message_text, message_text[:200])

        # Кнопки действий
        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{draft_id}"),
                InlineKeyboardButton("✏️ Править", callback_data=f"edit:{draft_id}"),
                InlineKeyboardButton("🚫 Отклонить", callback_data=f"reject:{draft_id}"),
            ],
            [
                InlineKeyboardButton("🎨 В стиле Симпсонов", callback_data=f"generate_simpsons:{draft_id}"),
            ]
        ]
        
        # Кнопка "Другая картинка" больше не нужна в основном сообщении
        # Она будет доступна только при выборе картинок для публикации
        
        reply_markup = InlineKeyboardMarkup(keyboard)

        sent_to = set()

        for moderator_id in config.MODERATOR_IDS:
            try:
                # Определяем parse_mode на основе body (не message_text, т.к. message_text может содержать Markdown-разметку)
                body = draft["body"]
                has_html_tags = (
                    "<b>" in body or "</b>" in body or
                    "<i>" in body or "</i>" in body or
                    "<u>" in body or "</u>" in body or
                    "<s>" in body or "</s>" in body or
                    "<a " in body or "</a>" in body
                )
                parse_mode = "HTML" if has_html_tags else "Markdown"
                
                # Если есть стилизованная картинка, отправляем её с текстом
                if final_image_url:
                    try:
                        await self.app.bot.send_photo(
                            chat_id=moderator_id,
                            photo=final_image_url,  # Сервис уже возвращает полный URL
                            caption=message_text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup,
                        )
                    except Exception as photo_error:
                        # Если не удалось отправить фото, отправляем только текст
                        logger.warning("Не удалось отправить фото, отправляем только текст: %s", photo_error)
                        await self.app.bot.send_message(
                            chat_id=moderator_id,
                            text=message_text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup,
                        )
                else:
                    # Нет картинки - отправляем только текст
                    await self.app.bot.send_message(
                        chat_id=moderator_id,
                        text=message_text,
                        parse_mode=parse_mode,
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
        all_pending = self.db.get_pending_draft_posts()
        logger.info("_check_and_send_new_drafts: найдено всего черновиков pending_moderation: %s", len(all_pending))
        
        # Ограничиваем отправку до 1 поста за раз для тестирования
        # Чтобы не было путаницы с несколькими постами одновременно
        MAX_DRAFTS_PER_CHECK = 1
        pending_drafts = all_pending[:MAX_DRAFTS_PER_CHECK]
        
        if pending_drafts:
            logger.info("Найдено %s новых черновиков, отправляю первый (лимит: %s)", 
                       len(all_pending), MAX_DRAFTS_PER_CHECK)
        else:
            logger.info("Нет черновиков для отправки (всего pending: %s)", len(all_pending))

        for draft in pending_drafts:
            draft_id = draft["id"]
            logger.info("Обрабатываю черновик draft_id=%s", draft_id)
            
            # Если черновик уже отправлен всем модераторам, пропускаем
            if draft_id in self.sent_drafts:
                sent_to = self.sent_drafts[draft_id]
                logger.info("Черновик draft_id=%s уже отправлен модераторам: %s", draft_id, sent_to)
                if sent_to == set(config.MODERATOR_IDS):
                    logger.info("Черновик draft_id=%s уже отправлен ВСЕМ модераторам, пропускаю", draft_id)
                    continue
            
            # ВРЕМЕННО: не пропускаем старые черновики для тестирования
            # Пропускаем старые черновики (созданные более 7 дней назад)
            # Это предотвращает отправку очень старых черновиков при перезапуске
            import datetime
            created_at_str = draft.get("created_at")
            if created_at_str:
                try:
                    # Парсим дату создания (формат: YYYY-MM-DD HH:MM:SS)
                    created_at = datetime.datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
                    now = datetime.datetime.now()
                    age_hours = (now - created_at).total_seconds() / 3600
                    logger.info("Черновик draft_id=%s, возраст: %.1f часов", draft_id, age_hours)
                    # Увеличили лимит до 7 дней (168 часов) для тестирования
                    if age_hours > 168:
                        logger.info("Пропускаем очень старый черновик: draft_id=%s, возраст=%.1f часов", draft_id, age_hours)
                        continue
                except Exception as e:
                    logger.warning("Ошибка при парсинге даты создания черновика: %s", e)

            # Отправляем черновик
            logger.info("Отправляю черновик draft_id=%s модераторам", draft_id)
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
        logger.info("=== CALLBACK HANDLER ВЫЗВАН ===")
        logger.info("update type: %s", type(update))
        logger.info("update: %s", update)
        
        query = update.callback_query
        if not query:
            logger.warning("query is None в callback_handler")
            logger.warning("update.callback_query: %s", update.callback_query)
            return
        
        logger.info("query.data = %s", query.data)
        logger.info("query.from_user.id = %s", query.from_user.id)
        logger.info("query.message.message_id = %s", query.message.message_id if query.message else "None")
        
        try:
            await query.answer()
            logger.info("query.answer() выполнен успешно")
        except Exception as e:
            logger.error("Ошибка при query.answer(): %s", e, exc_info=True)

        user_id = query.from_user.id
        logger.info("user_id = %s", user_id)

        if not self._is_moderator(user_id):
            logger.warning("Пользователь %s не является модератором", user_id)
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
        elif action == "more_images_for_publish":
            draft_id = int(parts[1])
            await self._handle_show_images_for_publish(query, draft_id)
        elif action == "select_image":
            draft_id = int(parts[1])
            image_index = int(parts[2])
            await self._handle_select_image(query, draft_id, image_index)
        elif action == "select_image_for_publish":
            # Это может быть либо выбор картинки для публикации (без индекса), либо выбор конкретной картинки (с индексом)
            if len(parts) == 2:
                # Просто запрос на показ картинок
                draft_id = int(parts[1])
                await self._handle_show_images_for_publish(query, draft_id)
            elif len(parts) == 3:
                # Выбор конкретной картинки
                draft_id = int(parts[1])
                image_index = int(parts[2])
                logger.info("Обработка select_image_for_publish: draft_id=%s, image_index=%s", draft_id, image_index)
                await self._handle_select_image_for_publish(query, draft_id, image_index)
        elif action == "generate_simpsons":
            draft_id = int(parts[1])
            draft = self.db.get_draft_post(draft_id)
            if not draft:
                await query.edit_message_text("❌ Черновик не найден.")
                return
            await self._handle_generate_simpsons(query, draft_id, draft)
        elif action == "sel_img_pub":
            # Старый формат для обратной совместимости
            draft_id = int(parts[1])
            image_index = int(parts[2])
            logger.info("Обработка sel_img_pub: draft_id=%s, image_index=%s", draft_id, image_index)
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
        """Обработать нажатие 'Опубликовать' - показать варианты выбора картинки или сразу опубликовать."""
        user_id = query.from_user.id

        # Проверяем, есть ли уже готовое изображение (например, сгенерированное в стиле Симпсонов)
        final_image_url = draft.get("final_image_url")
        
        # Если есть final_image_url, публикуем сразу
        if final_image_url:
            logger.info("_handle_approve: Найдено final_image_url, публикуем сразу без выбора картинки")
            # Сохраняем состояние публикации
            if len(config.TARGET_CHANNEL_IDS) == 1:
                target_channel = config.TARGET_CHANNEL_IDS[0]
                self.publishing_states[user_id] = (draft_id, [target_channel])
                # Публикуем сразу
                await self._publish_draft(draft_id, [target_channel], user_id=user_id)
                # Очищаем состояние
                if user_id in self.publishing_states:
                    del self.publishing_states[user_id]
                try:
                    if query.message.photo:
                        await query.edit_message_caption(caption="✅ Пост опубликован!")
                    else:
                        await query.edit_message_text("✅ Пост опубликован!")
                except:
                    await self.app.bot.send_message(chat_id=user_id, text="✅ Пост опубликован!")
                return
            else:
                # Если несколько каналов, показываем выбор каналов
                self.publishing_states[user_id] = (draft_id, [])
                keyboard_channels = []
                for channel_id in config.TARGET_CHANNEL_IDS:
                    channel_name = channel_id if isinstance(channel_id, str) else str(channel_id)
                    keyboard_channels.append([
                        InlineKeyboardButton(
                            f"📢 {channel_name}",
                            callback_data=f"select_channel:{draft_id}:{channel_id}"
                        )
                    ])
                keyboard_channels.append([
                    InlineKeyboardButton(
                        "📢 Выбрать несколько",
                        callback_data=f"select_multiple:{draft_id}"
                    )
                ])
                try:
                    if query.message.photo:
                        await query.edit_message_caption(
                            caption="📢 Выберите канал(ы) для публикации:",
                            reply_markup=InlineKeyboardMarkup(keyboard_channels)
                        )
                    else:
                        await query.edit_message_text(
                            "📢 Выберите канал(ы) для публикации:",
                            reply_markup=InlineKeyboardMarkup(keyboard_channels)
                        )
                except:
                    await self.app.bot.send_message(
                        chat_id=user_id,
                        text="📢 Выберите канал(ы) для публикации:",
                        reply_markup=InlineKeyboardMarkup(keyboard_channels)
                    )
                return

        # Сохраняем состояние публикации
        if len(config.TARGET_CHANNEL_IDS) == 1:
            target_channel = config.TARGET_CHANNEL_IDS[0]
            self.publishing_states[user_id] = (draft_id, [target_channel])
        else:
            # Если несколько каналов, нужно выбрать каналы (это уже реализовано в другом месте)
            # Пока используем первый канал
            target_channel = config.TARGET_CHANNEL_IDS[0]
            self.publishing_states[user_id] = (draft_id, [target_channel])
        
        # Показываем варианты публикации
        source_photo_file_id = draft.get("photo_file_id")
        image_query = draft.get("image_query")
        
        # Логируем для отладки - ВСЕ поля черновика
        logger.info("_handle_approve: draft_id=%s", draft_id)
        logger.info("_handle_approve: draft keys: %s", list(draft.keys()))
        logger.info("_handle_approve: image_query=%s (type: %s)", image_query, type(image_query))
        logger.info("_handle_approve: source_photo_file_id=%s", source_photo_file_id)
        logger.info("_handle_approve: full draft: %s", draft)
        
        keyboard = []
        
        # Кнопка "Выбрать картинку" - ВСЕГДА показываем (если нет image_query, сгенерируем при нажатии)
        keyboard.append([
            InlineKeyboardButton("🖼️ Выбрать картинку", callback_data=f"select_image_for_publish:{draft_id}")
        ])
        logger.info("_handle_approve: Добавляю кнопку 'Выбрать картинку' для draft_id=%s (image_query=%s)", draft_id, image_query)
        
        # Кнопка "Без картинки"
        keyboard.append([
            InlineKeyboardButton("🚫 Без картинки", callback_data=f"publish_no_photo:{draft_id}")
        ])
        
        # Кнопка "Вставить свою" - всегда доступна
        keyboard.append([
            InlineKeyboardButton("📤 Вставить свою", callback_data=f"publish_custom_photo:{draft_id}")
        ])
        
        # Кнопка "Использовать фото из поста" - только если есть
        if source_photo_file_id:
            keyboard.append([
                InlineKeyboardButton("📷 Использовать фото из поста", callback_data=f"publish_source_photo:{draft_id}")
            ])
        
        await query.edit_message_text(
            "Выберите вариант публикации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Если один канал - завершаем, варианты публикации уже показаны
        if len(config.TARGET_CHANNEL_IDS) == 1:
            return

        # Если несколько каналов, показываем выбор каналов ОТДЕЛЬНЫМ сообщением
        keyboard_channels = []
        for channel_id in config.TARGET_CHANNEL_IDS:
            channel_name = channel_id if isinstance(channel_id, str) else str(channel_id)
            keyboard_channels.append([
                InlineKeyboardButton(
                    f"📢 {channel_name}",
                    callback_data=f"select_channel:{draft_id}:{channel_id}"
                )
            ])

        # Кнопка для выбора нескольких каналов
        keyboard_channels.append([
            InlineKeyboardButton(
                "📢 Выбрать несколько",
                callback_data=f"select_multiple:{draft_id}"
            )
        ])

        # Отправляем выбор каналов ОТДЕЛЬНЫМ сообщением, не перезаписывая варианты публикации
        await self.app.bot.send_message(
            chat_id=query.from_user.id,
            text="📢 Выберите целевой канал(ы) для публикации:",
            reply_markup=InlineKeyboardMarkup(keyboard_channels),
        )

    async def _handle_channel_selection(
        self, query, draft_id: int, channel_id: str
    ) -> None:
        """Обработать выбор одного канала."""
        user_id = query.from_user.id
        self.publishing_states[user_id] = (draft_id, [channel_id])

        # Проверяем есть ли исходная картинка
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            await query.edit_message_text("❌ Черновик не найден.")
            return
        
        # Проверяем, есть ли уже готовое изображение (например, сгенерированное в стиле Симпсонов)
        final_image_url = draft.get("final_image_url")
        
        # Если есть final_image_url, публикуем сразу
        if final_image_url:
            logger.info("_handle_channel_selection: Найдено final_image_url, публикуем сразу")
            await self._publish_draft(draft_id, [channel_id], user_id=user_id)
            # Очищаем состояние
            if user_id in self.publishing_states:
                del self.publishing_states[user_id]
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption="✅ Пост опубликован!")
                else:
                    await query.edit_message_text("✅ Пост опубликован!")
            except:
                await self.app.bot.send_message(chat_id=user_id, text="✅ Пост опубликован!")
            return
            
        source_photo_file_id = draft.get("photo_file_id")
        
        keyboard = []
        
        # Кнопка "Выбрать картинку" - ВСЕГДА показываем
        keyboard.append([
            InlineKeyboardButton("🖼️ Выбрать картинку", callback_data=f"select_image_for_publish:{draft_id}")
        ])
        
        # Кнопка "Без картинки"
        keyboard.append([
            InlineKeyboardButton("🚫 Без картинки", callback_data=f"publish_no_photo:{draft_id}")
        ])
        
        # Кнопка "Вставить свою" - всегда доступна
        keyboard.append([
            InlineKeyboardButton("📤 Вставить свою", callback_data=f"publish_custom_photo:{draft_id}")
        ])
        
        # Кнопка "Использовать фото из поста" - только если есть
        if source_photo_file_id:
            keyboard.append([
                InlineKeyboardButton("📷 Использовать фото из поста", callback_data=f"publish_source_photo:{draft_id}")
            ])

        await query.edit_message_text(
            "Выберите вариант публикации:",
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
        if not draft:
            await query.edit_message_text("❌ Черновик не найден.")
            return
        
        # Проверяем, есть ли уже готовое изображение (например, сгенерированное в стиле Симпсонов)
        final_image_url = draft.get("final_image_url")
        
        # Если есть final_image_url, публикуем сразу
        if final_image_url:
            logger.info("_handle_publish_channels_done: Найдено final_image_url, публикуем сразу")
            await self._publish_draft(draft_id, selected_channels, user_id=user_id)
            # Очищаем состояние
            if user_id in self.publishing_states:
                del self.publishing_states[user_id]
            await query.edit_message_text("✅ Пост опубликован!")
            return
        
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
        
        # Проверяем, есть ли состояние публикации
        if user_id not in self.publishing_states:
            # Если состояния нет, создаем его (используем первый канал по умолчанию)
            if len(config.TARGET_CHANNEL_IDS) == 1:
                target_channel = config.TARGET_CHANNEL_IDS[0]
                self.publishing_states[user_id] = (draft_id, [target_channel])
                logger.info("Создано состояние публикации для user_id=%s, draft_id=%s", user_id, draft_id)
            else:
                await query.edit_message_text("❌ Ошибка: состояние потеряно. Нажмите 'Опубликовать' снова.")
                return

        await query.edit_message_text(
            "📸 Отправьте картинку одним сообщением.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Отмена", callback_data=f"publish_no_photo:{draft_id}")
            ]]),
        )
        logger.info("Ожидание фото от user_id=%s для draft_id=%s", user_id, draft_id)

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

    async def _handle_generate_simpsons(self, query, draft_id: int, draft: Dict) -> None:
        """Обработать нажатие 'В стиле Симпсонов' - сгенерировать изображение через DALL-E."""
        try:
            # Показываем сообщение о генерации
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption="🎨 Генерирую изображение в стиле Симпсонов... Это может занять до минуты.")
                else:
                    await query.edit_message_text("🎨 Генерирую изображение в стиле Симпсонов... Это может занять до минуты.")
            except:
                await query.answer("🎨 Генерирую изображение...")
            
            # Получаем оригинальный текст новости из source_posts
            original_text = draft.get("text_original", "")
            if not original_text:
                # Fallback на body, если text_original нет
                original_text = draft.get("body", "") or draft.get("title", "")
            
            if not original_text:
                await query.edit_message_text("❌ Не удалось получить текст новости для генерации.")
                return
            
            # Генерируем изображение (синхронная функция в отдельном потоке)
            loop = asyncio.get_event_loop()
            image_url = await loop.run_in_executor(
                None, 
                self._generate_simpsons_image, 
                original_text
            )
            
            if not image_url:
                try:
                    if query.message.photo:
                        await query.edit_message_caption(caption="❌ Не удалось сгенерировать изображение. Попробуйте позже.")
                    else:
                        await query.edit_message_text("❌ Не удалось сгенерировать изображение. Попробуйте позже.")
                except:
                    await self.app.bot.send_message(chat_id=query.from_user.id, text="❌ Не удалось сгенерировать изображение.")
                return
            
            # Сохраняем final_image_url в БД
            self.db.update_draft_post(draft_id, final_image_url=image_url)
            
            # Показываем сгенерированное изображение
            updated_draft = self.db.get_draft_post(draft_id)
            message_text = self._format_draft_message(updated_draft)
            
            # Определяем parse_mode
            body = updated_draft.get("body", "")
            has_html_tags = (
                "<b>" in body or "</b>" in body or
                "<i>" in body or "</i>" in body or
                "<u>" in body or "</u>" in body
            )
            parse_mode = "HTML" if has_html_tags else None
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{draft_id}"),
                    InlineKeyboardButton("✏️ Править", callback_data=f"edit:{draft_id}"),
                    InlineKeyboardButton("🚫 Отклонить", callback_data=f"reject:{draft_id}"),
                ]
            ]
            
            # Отправляем изображение с текстом
            # Скачиваем изображение и отправляем как файл (как в _publish_draft)
            try:
                import httpx
                from io import BytesIO
                
                # Скачиваем изображение по URL
                logger.info("Скачивание сгенерированного изображения: %s", image_url)
                proxy_url = None
                if config.OPENAI_PROXY:
                    proxy_url = config.OPENAI_PROXY
                    if proxy_url.startswith("http://"):
                        proxy_url = proxy_url.replace("http://", "socks5://", 1)
                
                with httpx.Client(proxy=proxy_url, timeout=30.0) as client:
                    resp = client.get(image_url)
                    resp.raise_for_status()
                    image_data = BytesIO(resp.content)
                    image_data.name = "image.jpg"  # Нужно для Telegram API
                
                # Отправляем как файл
                await self.app.bot.send_photo(
                    chat_id=query.from_user.id,
                    photo=image_data,
                    caption=message_text,
                    parse_mode=parse_mode,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                logger.info("Сгенерированное изображение успешно отправлено в бот")
                
                # Удаляем старое сообщение
                try:
                    await query.message.delete()
                except:
                    pass
            except Exception as e:
                logger.error("Ошибка при отправке сгенерированного изображения: %s", e, exc_info=True)
                try:
                    if query.message.photo:
                        await query.edit_message_caption(caption=f"✅ Изображение сгенерировано, но произошла ошибка при отправке: {str(e)}")
                    else:
                        await query.edit_message_text(f"✅ Изображение сгенерировано, но произошла ошибка при отправке: {str(e)}")
                except:
                    await self.app.bot.send_message(chat_id=query.from_user.id, text=f"✅ Изображение сгенерировано, но произошла ошибка при отправке: {str(e)}")
                
        except Exception as e:
            logger.error("Ошибка при генерации изображения в стиле Симпсонов: %s", e, exc_info=True)
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=f"❌ Ошибка: {str(e)}")
                else:
                    await query.edit_message_text(f"❌ Ошибка: {str(e)}")
            except:
                await self.app.bot.send_message(chat_id=query.from_user.id, text=f"❌ Ошибка: {str(e)}")

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик текстовых сообщений и фото."""
        if not update.message:
            return
            
        user_id = update.effective_user.id
        
        # Проверяем все возможные способы получения фото
        has_photo = bool(update.message.photo)
        has_document = bool(update.message.document)
        photo_file_id = None
        
        # Если фото есть в стандартном формате
        if update.message.photo:
            photo = update.message.photo[-1]  # Берём самое большое фото
            photo_file_id = photo.file_id
        # Если фото отправлено как документ (например, PNG/JPG файл)
        elif update.message.document:
            doc = update.message.document
            # Проверяем, что это изображение
            if doc.mime_type and doc.mime_type.startswith('image/'):
                photo_file_id = doc.file_id
                has_photo = True
                logger.info("Фото получено как документ: mime_type=%s, file_id=%s", doc.mime_type, photo_file_id)
        
        logger.info("message_handler вызван: user_id=%s, есть фото=%s (photo=%s, document=%s), есть текст=%s", 
                   user_id, has_photo, bool(update.message.photo), bool(update.message.document), bool(update.message.text))

        if not self._is_moderator(user_id):
            logger.debug("Пользователь %s не является модератором", user_id)
            return

        # Проверяем, находится ли пользователь в режиме редактирования
        if user_id in self.editing_states:
            draft_id = self.editing_states[user_id]
            logger.info("Пользователь %s в режиме редактирования, draft_id=%s", user_id, draft_id)
            # Редактирование работает только с текстом
            if update.message.text:
                await self._handle_edit_text(update, draft_id)
            else:
                await update.message.reply_text("✏️ Отправьте текст для редактирования.")
            return

        # Проверяем, находится ли пользователь в режиме публикации (ожидание фото)
        logger.info("Проверка publishing_states для user_id=%s: %s", user_id, user_id in self.publishing_states)
        logger.info("Текущие publishing_states: %s", self.publishing_states)
        if user_id in self.publishing_states:
            draft_id, selected_channels = self.publishing_states[user_id]
            logger.info("Получено сообщение от user_id=%s в режиме публикации, draft_id=%s, есть фото: %s", 
                       user_id, draft_id, has_photo)
            
            # Проверяем, есть ли фото (в любом формате)
            if has_photo and photo_file_id:
                logger.info("Получено фото от user_id=%s, file_id=%s, обрабатываю и стилизую draft_id=%s", 
                           user_id, photo_file_id, draft_id)
                
                try:
                    # Получаем черновик для заголовка
                    draft = self.db.get_draft_post(draft_id)
                    if not draft:
                        await update.message.reply_text("❌ Черновик не найден.")
                        del self.publishing_states[user_id]
                        return
                    
                    title = draft.get("title", "")
                    if not title:
                        # Извлекаем заголовок из body (HTML)
                        body = draft.get("body", "")
                        import re
                        title_match = re.search(r'<b>(.*?)</b>', body, re.DOTALL)
                        if title_match:
                            title = re.sub(r'^[🎾🏆⭐📊🔥💥⏱🟢❄️]+', '', title_match.group(1)).strip()
                    
                    # Скачиваем фото и сохраняем во временную папку
                    await update.message.reply_text("🎨 Скачиваю и стилизую картинку...")
                    
                    # Скачиваем файл
                    file = await self.app.bot.get_file(photo_file_id)
                    from io import BytesIO
                    from pathlib import Path
                    import uuid
                    import os
                    
                    file_data = BytesIO()
                    await file.download_to_memory(file_data)
                    file_data.seek(0)
                    
                    # Сохраняем во временную папку
                    temp_dir = Path(__file__).parent / "temp_uploads"
                    temp_dir.mkdir(exist_ok=True)
                    temp_filename = f"temp_{uuid.uuid4().hex}.jpg"
                    temp_filepath = temp_dir / temp_filename
                    
                    with open(temp_filepath, "wb") as f:
                        f.write(file_data.read())
                    
                    # Получаем URL для временного файла
                    # Используем тот же базовый URL, что и для стилизованных изображений
                    base_url = config.IMAGE_RENDER_SERVICE_URL.rstrip("/")
                    temp_image_url = f"{base_url}/temp/{temp_filename}"
                    
                    # Но сначала нужно добавить endpoint в сервис стилизации для отдачи временных файлов
                    # Пока используем прямой путь к файлу через локальный сервер
                    # Или лучше - загрузить файл напрямую в сервис стилизации
                    # Для простоты - используем локальный путь и добавляем endpoint в сервис
                    
                    # Временно: используем прямой путь к файлу (если сервис на том же сервере)
                    # Или загружаем файл в сервис стилизации через multipart/form-data
                    # Но проще - добавить endpoint /temp/<filename> в сервис стилизации
                    
                    # Пока используем обходной путь: сохраняем в rendered_images с префиксом temp_
                    # и удаляем после стилизации
                    rendered_dir = Path(__file__).parent / "rendered_images"
                    rendered_dir.mkdir(exist_ok=True)
                    temp_rendered_filename = f"temp_{uuid.uuid4().hex}.jpg"
                    temp_rendered_filepath = rendered_dir / temp_rendered_filename
                    
                    # Копируем файл в rendered_images
                    with open(temp_rendered_filepath, "wb") as f:
                        file_data.seek(0)
                        f.write(file_data.read())
                    
                    # Получаем URL
                    temp_image_url = f"{base_url}/rendered/{temp_rendered_filename}"
                    
                    # Стилизуем картинку
                    final_image_url = self._render_image(temp_image_url, title)
                    
                    # Удаляем временный файл
                    try:
                        temp_rendered_filepath.unlink()
                        temp_filepath.unlink()
                    except Exception as cleanup_error:
                        logger.warning("Не удалось удалить временный файл: %s", cleanup_error)
                    
                    if not final_image_url:
                        await update.message.reply_text("❌ Не удалось стилизовать картинку. Публикую без стилизации.")
                        # Публикуем с исходным фото
                        await self._publish_draft(
                            draft_id, selected_channels, photo_file_id=photo_file_id, user_id=user_id
                        )
                    else:
                        # Сохраняем final_image_url в БД
                        self.db.update_draft_post(draft_id, final_image_url=final_image_url)
                        logger.info("Сохранен final_image_url для draft_id=%s: %s", draft_id, final_image_url)
                        
                        # Публикуем с стилизованной картинкой
                        await self._publish_draft(
                            draft_id, selected_channels, user_id=user_id
                        )
                    
                    # Очищаем состояние
                    del self.publishing_states[user_id]
                    logger.info("Публикация завершена, состояние удалено для user_id=%s", user_id)
                    
                    await update.message.reply_text("✅ Пост опубликован с картинкой!")
                except Exception as e:
                    logger.error("Ошибка при обработке и публикации фото: %s", e, exc_info=True)
                    await update.message.reply_text(f"❌ Ошибка при обработке фото: {str(e)}")
                    # Очищаем состояние даже при ошибке
                    if user_id in self.publishing_states:
                        del self.publishing_states[user_id]
            else:
                logger.warning("Получено сообщение без фото от user_id=%s в режиме публикации, тип: %s", 
                             user_id, type(update.message).__name__)
                await update.message.reply_text(
                    "📸 Отправьте картинку (фото) или нажмите 'Без картинки' в предыдущем сообщении."
                )
            return
        
        # Если пользователь не в режиме редактирования или публикации, игнорируем сообщение
        logger.debug("Сообщение от user_id=%s не обработано (не в режиме редактирования/публикации)", user_id)

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
            ],
            [
                InlineKeyboardButton("🎨 В стиле Симпсонов", callback_data=f"generate_simpsons:{draft_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "✅ Текст обновлён. Превью:",
            reply_markup=reply_markup,
        )
        # Определяем parse_mode на основе body
        body = draft["body"]
        has_html_tags = (
            "<b>" in body or "</b>" in body or
            "<i>" in body or "</i>" in body or
            "<u>" in body or "</u>" in body or
            "<s>" in body or "</s>" in body or
            "<a " in body or "</a>" in body
        )
        parse_mode = "HTML" if has_html_tags else "Markdown"
        
        await update.message.reply_text(
            message_text,
            parse_mode=parse_mode,
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

        # Используем случайную страницу для получения других картинок
        import random
        random_page = random.randint(1, 10)  # Случайная страница от 1 до 10
        logger.info("Поиск картинок для 'Другая картинка': query=%s, page=%s", image_query, random_page)
        
        # Запрос к Pexels API с случайной страницей
        pexels_images = self._search_pexels_images(image_query, page=random_page)
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
            ],
            [
                InlineKeyboardButton("🎨 В стиле Симпсонов", callback_data=f"generate_simpsons:{draft_id}"),
            ]
        ]
        if updated_draft.get("image_query"):
            keyboard.append([
                InlineKeyboardButton("♻️ Другая картинка", callback_data=f"change_image:{draft_id}")
            ])

        # Определяем parse_mode на основе body
        body = updated_draft["body"]
        has_html_tags = (
            "<b>" in body or "</b>" in body or
            "<i>" in body or "</i>" in body or
            "<u>" in body or "</u>" in body or
            "<s>" in body or "</s>" in body or
            "<a " in body or "</a>" in body
        )
        parse_mode = "HTML" if has_html_tags else "Markdown"
        
        try:
            await query.edit_message_caption(
                caption=message_text,
                parse_mode=parse_mode,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except:
            # Если не получилось обновить caption, отправляем новое сообщение
            await self.app.bot.send_photo(
                chat_id=query.from_user.id,
                photo=final_url,  # Сервис уже возвращает полный URL
                caption=message_text,
                parse_mode=parse_mode,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        await query.answer("✅ Картинка обновлена!")

    async def _handle_show_images_for_publish(self, query, draft_id: int) -> None:
        """Показать картинки для выбора при публикации."""
        draft = self.db.get_draft_post(draft_id)
        if not draft:
            await query.edit_message_text("❌ Черновик не найден.")
            return

        image_query = draft.get("image_query")
        
        # Если image_query нет, генерируем его из заголовка
        if not image_query or not str(image_query).strip():
            logger.info("_handle_show_images_for_publish: image_query отсутствует, генерирую из заголовка")
            title = draft.get("title", "")
            # Простая генерация image_query из заголовка
            title_lower = title.lower()
            if "матч" in title_lower or "match" in title_lower:
                image_query = "tennis match"
            elif "игрок" in title_lower or "player" in title_lower or "теннисист" in title_lower:
                image_query = "tennis player"
            elif "турнир" in title_lower or "tournament" in title_lower:
                image_query = "tennis tournament"
            elif "чемпионат" in title_lower or "championship" in title_lower:
                image_query = "tennis championship"
            elif "wta" in title_lower:
                image_query = "tennis WTA match"
            elif "atp" in title_lower:
                image_query = "tennis ATP match"
            else:
                image_query = "tennis sport"
            
            logger.info("_handle_show_images_for_publish: сгенерирован image_query: %s", image_query)
            
            # Сохраняем сгенерированный image_query в БД
            try:
                self.db.update_draft_post(draft_id, image_query=image_query)
                logger.info("_handle_show_images_for_publish: image_query сохранен в БД")
            except Exception as e:
                logger.error("_handle_show_images_for_publish: ошибка при сохранении image_query: %s", e)

        await query.edit_message_text("🔄 Ищу картинки...")

        # Запрос к Pexels API (используем случайную страницу для разнообразия)
        import random
        random_page = random.randint(1, 10)
        logger.info("Поиск картинок для публикации: query=%s, page=%s", image_query, random_page)
        
        pexels_images = self._search_pexels_images(image_query, page=random_page)
        if not pexels_images or len(pexels_images) == 0:
            await query.edit_message_text("❌ Не удалось найти картинки. Попробуйте позже.")
            return

        # Сохраняем картинки в БД
        import json
        pexels_images_json = json.dumps(pexels_images, ensure_ascii=False)
        self.db.update_draft_post(draft_id, pexels_images_json=pexels_images_json)

        # Показываем картинки для выбора
        await query.edit_message_text("📸 Выберите картинку для публикации:")
        
        # Отправляем каждую картинку с кнопкой выбора
        for idx, pexels_img in enumerate(pexels_images):
            callback_data = f"select_image_for_publish:{draft_id}:{idx}"
            keyboard = [[
                InlineKeyboardButton(
                    f"✅ Выбрать эту ({idx+1}/3)",
                    callback_data=callback_data
                )
            ]]
            try:
                logger.info("Отправка картинки %s с callback_data: %s", idx, callback_data)
                result = await self.app.bot.send_photo(
                    chat_id=query.from_user.id,
                    photo=pexels_img["url"],
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                logger.info("Картинка %s отправлена. message_id=%s", idx, result.message_id)
            except Exception as e:
                logger.error("Ошибка при отправке картинки %s: %s", idx, e, exc_info=True)
        
        # Отправляем кнопку "Еще картинки"
        keyboard_more = [[
            InlineKeyboardButton(
                "🔄 Еще картинки",
                callback_data=f"more_images_for_publish:{draft_id}"
            )
        ]]
        await self.app.bot.send_message(
            chat_id=query.from_user.id,
            text="Или запросите другие картинки:",
            reply_markup=InlineKeyboardMarkup(keyboard_more)
        )

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
        # Если сообщение - фото, используем edit_message_caption, иначе edit_message_text
        try:
            if query.message.photo:
                await query.edit_message_caption(caption="🎨 Стилизую картинку...")
            else:
                await query.edit_message_text("🎨 Стилизую картинку...")
        except Exception as e:
            logger.warning("Не удалось отредактировать сообщение, отправляю новое: %s", e)
            await query.answer("🎨 Стилизую картинку...")
            await self.app.bot.send_message(chat_id=query.from_user.id, text="🎨 Стилизую картинку...")
        
        selected_image_url = pexels_images[image_index]["url"]
        logger.info("Выбрана картинка: %s", selected_image_url)
        title = draft.get("title") if isinstance(draft, dict) else draft["title"]
        logger.info("Начинаю стилизацию картинки для draft_id=%s, title=%s", draft_id, title[:50])
        
        try:
            # Вызываем синхронную функцию в executor, чтобы не блокировать event loop
            import asyncio
            loop = asyncio.get_event_loop()
            final_url = await loop.run_in_executor(None, self._render_image, selected_image_url, title)
            logger.info("_render_image вернул: %s", final_url)
        except Exception as e:
            logger.error("Ошибка при вызове _render_image: %s", e, exc_info=True)
            await query.edit_message_text("❌ Ошибка при стилизации картинки.")
            return

        if not final_url:
            logger.error("Не удалось стилизовать картинку: %s, _render_image вернул None", selected_image_url)
            await query.edit_message_text("❌ Не удалось стилизовать картинку.")
            return

        logger.info("Картинка стилизована: %s", final_url)
        # Обновляем final_image_url в БД
        try:
            self.db.update_draft_post(draft_id, final_image_url=final_url)
            logger.info("final_image_url обновлен в БД для draft_id=%s", draft_id)
        except Exception as e:
            logger.error("Ошибка при обновлении БД: %s", e, exc_info=True)
            await query.edit_message_text("❌ Ошибка при сохранении картинки в БД.")
            return

        # Публикуем черновик
        user_id = query.from_user.id
        logger.info("Проверка publishing_states для user_id=%s: %s", user_id, user_id in self.publishing_states)
        logger.info("Текущие publishing_states: %s", self.publishing_states)
        
        if user_id in self.publishing_states:
            _, target_channels = self.publishing_states[user_id]
            logger.info("Найдено состояние публикации, каналы: %s", target_channels)
            try:
                await self._publish_draft(draft_id, target_channels)
                try:
                    if query.message.photo:
                        await query.edit_message_caption(caption="✅ Пост опубликован!")
                    else:
                        await query.edit_message_text("✅ Пост опубликован!")
                except:
                    await self.app.bot.send_message(chat_id=query.from_user.id, text="✅ Пост опубликован!")
                del self.publishing_states[user_id]
                logger.info("Публикация завершена, состояние удалено")
            except Exception as e:
                logger.error("Ошибка при публикации: %s", e, exc_info=True)
                try:
                    if query.message.photo:
                        await query.edit_message_caption(caption=f"❌ Ошибка при публикации: {str(e)}")
                    else:
                        await query.edit_message_text(f"❌ Ошибка при публикации: {str(e)}")
                except:
                    await self.app.bot.send_message(chat_id=query.from_user.id, text=f"❌ Ошибка при публикации: {str(e)}")
        else:
            logger.warning("Состояние публикации не найдено для user_id=%s. publishing_states: %s", user_id, self.publishing_states)
            # Если состояние не найдено, используем дефолтный канал
            if len(config.TARGET_CHANNEL_IDS) == 1:
                target_channel = config.TARGET_CHANNEL_IDS[0]
                logger.info("Используем дефолтный канал: %s", target_channel)
                try:
                    await self._publish_draft(draft_id, [target_channel])
                    try:
                        if query.message.photo:
                            await query.edit_message_caption(caption="✅ Пост опубликован!")
                        else:
                            await query.edit_message_text("✅ Пост опубликован!")
                    except:
                        await self.app.bot.send_message(chat_id=query.from_user.id, text="✅ Пост опубликован!")
                    logger.info("Публикация завершена с дефолтным каналом")
                except Exception as e:
                    logger.error("Ошибка при публикации с дефолтным каналом: %s", e, exc_info=True)
                    try:
                        if query.message.photo:
                            await query.edit_message_caption(caption=f"❌ Ошибка при публикации: {str(e)}")
                        else:
                            await query.edit_message_text(f"❌ Ошибка при публикации: {str(e)}")
                    except:
                        await self.app.bot.send_message(chat_id=query.from_user.id, text=f"❌ Ошибка при публикации: {str(e)}")
            else:
                try:
                    if query.message.photo:
                        await query.edit_message_caption(caption="❌ Ошибка: состояние публикации не найдено. Пожалуйста, нажмите 'Опубликовать' снова и выберите каналы.")
                    else:
                        await query.edit_message_text("❌ Ошибка: состояние публикации не найдено. Пожалуйста, нажмите 'Опубликовать' снова и выберите каналы.")
                except:
                    await self.app.bot.send_message(chat_id=query.from_user.id, text="❌ Ошибка: состояние публикации не найдено. Пожалуйста, нажмите 'Опубликовать' снова и выберите каналы.")

    def _search_pexels_images(self, query: str, page: int = 1) -> Optional[List[Dict[str, str]]]:
        """Поиск картинок через Pexels API (синхронная функция).

        Args:
            query: Поисковый запрос
            page: Номер страницы (1-80, по умолчанию 1)

        Returns:
            Список словарей с URL картинок или None при ошибке
        """
        if not query:
            return None

        url = config.PEXELS_API_URL
        headers = {
            "Authorization": config.PEXELS_API_KEY
        }
        # Ограничиваем page от 1 до 80 (максимум для Pexels API)
        page = max(1, min(page, 80))
        params = {
            "query": query,
            "per_page": config.PEXELS_PER_PAGE,
            "orientation": "landscape",
            "page": page
        }
        logger.info("Поиск картинок в Pexels: query=%s, page=%s", query, page)

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

    def _generate_simpsons_image(self, original_text: str) -> Optional[str]:
        """Генерировать изображение в стиле Симпсонов через DALL-E API (синхронная функция).

        Args:
            original_text: Оригинальный текст новости для генерации изображения

        Returns:
            URL сгенерированного изображения или None при ошибке
        """
        import httpx
        from pathlib import Path
        import uuid
        from io import BytesIO
        
        # Формируем промпт для DALL-E согласно новым требованиям
        # Используем оригинальный текст новости полностью
        # Ограничиваем длину до 1000 символов
        news_text = original_text.strip()[:1000]
        
        # Используем GPT для создания детального промпта для DALL-E в стиле Симпсонов
        try:
            import httpx
            proxy_url = None
            if config.OPENAI_PROXY:
                proxy_url = config.OPENAI_PROXY
                if proxy_url.startswith("http://"):
                    proxy_url = proxy_url.replace("http://", "socks5://", 1)
            
            # Используем GPT для создания промпта для DALL-E
            from openai import OpenAI
            client = OpenAI(
                api_key=config.OPENAI_API_KEY,
                http_client=httpx.Client(proxy=proxy_url, timeout=30.0) if proxy_url else None
            )
            
            system_prompt = """You are generating a single funny 2D illustration in the style of "The Simpsons" for a tennis media project called Setka360.

I will give you a short tennis news text in Russian.

Task:

 1. Read the news and extract the main idea (who, где, что произошло, какой главный прикол/изюминка).

 2. Based only on this essence, create ONE humorous scene as a detailed image prompt.

Style & rules:

 • Classic The Simpsons look: yellow skin, big round eyes, thick black outlines, simple but expressive faces.

 • Main character = теннисист(ка) из новости, узнаваем по общему образу (пол, прическа/её отсутствие, цвет формы, флаг страны), но без фотореализма и без точного копирования лица.

 • Сцена всегда связана с теннисом и новостью:

 • матч, тренировка, корты, трибуны, раздевалка, барбершоп, аэропорт, автодром и т.п.

 • один яркий визуальный гэг, отражающий суть новости (например, смена имиджа, скорость как в F1, возвращение на корт после паузы и т.д.).

 • На заднем плане по возможности добавить:

 • надпись с городом/турниром из новости (например, "ABU DHABI", "BASEL", "ATLANTA" на табло или баннере);

 • мелкие детали, подчёркивающие страну игрока (флаг на форме, маленький флажок на табло и др.).

 • Обязательно где-то на корте или баннере маленькая, но читаемая подпись: "Setka360".

 • Цвета яркие, контрастные; настроение весёлое и динамичное; формат изображения квадратный (1:1).

 • Никаких реальных логотипов брендов и спонсоров (только вымышленные или текстовые).

Output format:

 • Give ONLY the final image description in English, ready to send to an image model (no explanations, no extra text).

News text (in Russian):

{ВСТАВЬ СЮДА НОВОСТЬ}"""
            
            # Подставляем текст новости в промпт
            user_prompt = system_prompt.replace("{ВСТАВЬ СЮДА НОВОСТЬ}", news_text)
            
            gpt_response = client.chat.completions.create(
                model="gpt-4o-mini",  # Используем более дешевую модель для создания промпта
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            prompt = gpt_response.choices[0].message.content.strip()
            logger.info("Промпт для DALL-E создан через GPT: %s", prompt[:300])
        except Exception as e:
            logger.error("Не удалось создать промпт через GPT: %s, используем упрощенный вариант", e, exc_info=True)
            # Если создание промпта не удалось, используем упрощенный вариант
            prompt = f"Generate a humorous cartoon image in The Simpsons style for a Telegram channel post about tennis news: {news_text[:500]}. The image should be funny, colorful, and suitable for a sports news channel. Style: The Simpsons animation, 1024x1024 pixels, square format."
        
        url = "https://api.openai.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "dall-e-3",
            "prompt": prompt,
            "size": "1024x1024",
            "quality": "standard",
            "n": 1
        }
        
        try:
            logger.info("Запрос к DALL-E API для генерации изображения в стиле Симпсонов")
            logger.info("Промпт: %s", prompt[:200])
            
            # Используем httpx с прокси
            proxy_url = None
            if config.OPENAI_PROXY:
                proxy_url = config.OPENAI_PROXY
                if proxy_url.startswith("http://"):
                    proxy_url = proxy_url.replace("http://", "socks5://", 1)
            
            with httpx.Client(proxy=proxy_url, timeout=60.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            
            image_url = data.get("data", [{}])[0].get("url")
            if not image_url:
                logger.error("DALL-E API не вернул URL изображения: %s", data)
                return None
            
            logger.info("Изображение сгенерировано: %s", image_url)
            
            # Передаём URL DALL-E напрямую в сервис стилизации
            # Сервис сам скачает изображение и обработает его
            # Извлекаем title для стилизации из оригинального текста (первые 50 символов)
            title_for_render = original_text.strip()[:50] if original_text else "Tennis News"
            final_url = self._render_image(image_url, title_for_render)
            
            # Если стилизация не удалась, используем оригинальное изображение DALL-E
            if not final_url:
                logger.warning("Стилизация не удалась, используем оригинальное изображение DALL-E")
                final_url = image_url
            
            return final_url
            
        except Exception as e:
            logger.error("Ошибка при генерации изображения через DALL-E: %s", e, exc_info=True)
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
            logger.info("Запрос к сервису стилизации: %s", service_url)
            resp = requests.post(service_url, json=payload, timeout=30)
            logger.info("Ответ сервиса стилизации: status=%s", resp.status_code)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Данные от сервиса стилизации: %s", data)

            final_url = data.get("final_image_url")
            logger.info("Получен final_image_url: %s", final_url)
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

        body = draft["body"]
        final_image_url = draft.get("final_image_url")
        
        # Логируем что получили из БД
        logger.info("_publish_draft: draft_id=%s, body (first 300): %s", draft_id, body[:300] if body else "EMPTY")
        logger.info("_publish_draft: body содержит эмоджи 🎾: %s", "🎾" in (body or ""))

        # Формируем текст поста
        # Если body содержит HTML-теги (новый формат), используем его напрямую
        # Иначе формируем из title/body/hashtags (старый формат для обратной совместимости)
        # Проверяем наличие HTML-тегов (более полная проверка)
        has_html_tags = (
            "<b>" in body or "</b>" in body or
            "<i>" in body or "</i>" in body or
            "<u>" in body or "</u>" in body or
            "<s>" in body or "</s>" in body or
            "<a " in body or "</a>" in body or
            "<code>" in body or "</code>" in body
        )
        
        # ВСЕГДА используем body напрямую, если он не пустой
        # GPT теперь всегда возвращает HTML с эмоджи в body
        if body and body.strip():
            post_text = body
            # Проверяем HTML-теги для определения parse_mode
            if has_html_tags:
                parse_mode = "HTML"
                logger.info("Используется HTML parse_mode для draft_id=%s", draft_id)
            else:
                parse_mode = None  # Без parse_mode, чтобы эмоджи отображались
                logger.info("Используется parse_mode=None для draft_id=%s (эмоджи будут отображаться)", draft_id)
        else:
            # Fallback на старый формат только если body пустой
            title = draft.get("title", "")
            hashtags = draft.get("hashtags", "")
            post_text = f"{title}\n\n{body}\n\n{hashtags}" if body else f"{title}\n\n{hashtags}"
            parse_mode = "Markdown"
            logger.warning("Используется старый формат для draft_id=%s (body пустой)", draft_id)
        
        # Проверяем что post_text не пустой
        if not post_text or not post_text.strip():
            logger.error("_publish_draft: post_text ПУСТОЙ для draft_id=%s! body=%s", draft_id, body[:200] if body else "EMPTY")
            raise ValueError("post_text is empty")
        
        logger.info("_publish_draft: финальный post_text (first 300): %s, parse_mode=%s", post_text[:300], parse_mode)

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
                    # Если это URL (стилизованная картинка), скачиваем и отправляем как файл
                    # Если это file_id (исходная картинка), используем file_id
                    if image_to_use.startswith("http://") or image_to_use.startswith("https://"):
                        # Скачиваем картинку по URL
                        logger.info("Скачивание картинки для публикации: %s", image_to_use)
                        try:
                            import httpx
                            from io import BytesIO
                            proxy_url = None
                            if config.OPENAI_PROXY:
                                proxy_url = config.OPENAI_PROXY
                                if proxy_url.startswith("http://"):
                                    proxy_url = proxy_url.replace("http://", "socks5://", 1)
                            
                            with httpx.Client(proxy=proxy_url, timeout=30.0) as client:
                                resp = client.get(image_to_use)
                                resp.raise_for_status()
                                image_data = BytesIO(resp.content)
                                image_data.name = "image.jpg"  # Нужно для Telegram API
                            
                            # Отправляем как файл
                            logger.info("Отправка фото с caption в канал %s, caption (first 300): %s, parse_mode=%s", 
                                       channel_id, post_text[:300] if post_text else "EMPTY", parse_mode)
                            message = await self.app.bot.send_photo(
                                chat_id=channel_id,
                                photo=image_data,
                                caption=post_text,
                                parse_mode=parse_mode,
                            )
                            logger.info("Картинка отправлена успешно в канал %s", channel_id)
                        except Exception as download_error:
                            logger.error("Ошибка при скачивании/отправке картинки: %s", download_error, exc_info=True)
                            # Если не удалось отправить с фото, отправляем только текст
                            message = await self.app.bot.send_message(
                                chat_id=channel_id,
                                text=post_text,
                                parse_mode=parse_mode,
                            )
                            errors.append(f"Канал {channel_id}: не удалось отправить фото ({str(download_error)})")
                    else:
                        # Это file_id - может быть как photo, так и document
                        # Пытаемся отправить напрямую, если не получится - скачиваем и отправляем
                        try:
                            message = await self.app.bot.send_photo(
                                chat_id=channel_id,
                                photo=image_to_use,
                                caption=post_text,
                                parse_mode=parse_mode,
                            )
                            logger.info("Картинка отправлена успешно через file_id в канал %s", channel_id)
                        except Exception as photo_error:
                            # Если не получилось (например, file_id это document, а не photo),
                            # скачиваем файл и отправляем как BytesIO
                            logger.warning("Не удалось отправить через file_id (возможно, это document): %s. Скачиваю файл...", photo_error)
                            try:
                                # Скачиваем файл через get_file
                                file = await self.app.bot.get_file(image_to_use)
                                from io import BytesIO
                                file_data = BytesIO()
                                await file.download_to_memory(file_data)
                                file_data.seek(0)
                                file_data.name = "image.jpg"
                                
                                # Отправляем как фото
                                message = await self.app.bot.send_photo(
                                    chat_id=channel_id,
                                    photo=file_data,
                                    caption=post_text,
                                    parse_mode=parse_mode,
                                )
                                logger.info("Картинка скачана и отправлена успешно в канал %s", channel_id)
                            except Exception as download_error:
                                logger.error("Ошибка при скачивании/отправке файла: %s", download_error, exc_info=True)
                                # Если не удалось отправить с фото, отправляем только текст
                                message = await self.app.bot.send_message(
                                    chat_id=channel_id,
                                    text=post_text,
                                    parse_mode=parse_mode,
                                )
                                errors.append(f"Канал {channel_id}: не удалось отправить фото ({str(download_error)})")
                else:
                    # Отправляем текстовое сообщение
                    logger.info("Отправка текстового сообщения в канал %s, post_text (first 300): %s", channel_id, post_text[:300] if post_text else "EMPTY")
                    if not post_text or not post_text.strip():
                        logger.error("ОШИБКА: post_text пустой для канала %s! Пропускаю публикацию.", channel_id)
                        errors.append(f"Канал {channel_id}: post_text пустой")
                        continue
                    logger.info("Отправка текста в канал %s, text (first 300): %s, parse_mode=%s", 
                               channel_id, post_text[:300] if post_text else "EMPTY", parse_mode)
                    message = await self.app.bot.send_message(
                        chat_id=channel_id,
                        text=post_text,
                        parse_mode=parse_mode,
                    )
                    logger.info("Текстовое сообщение отправлено успешно в канал %s", channel_id)

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
        # ВАЖНО: CallbackQueryHandler должен быть ПЕРВЫМ, чтобы не перехватывался MessageHandler
        logger.info("Регистрация обработчиков...")
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))
        logger.info("Обработчик callback зарегистрирован (ПЕРВЫМ)")
        self.app.add_handler(CommandHandler("start", self.start_command))
        logger.info("Обработчик команд зарегистрирован")
        # MessageHandler должен быть последним, чтобы не перехватывать callback queries
        # Обрабатываем и текст, и фото (для загрузки своих картинок)
        # Используем filters.ALL чтобы перехватить все сообщения (текст, фото, документы), кроме команд
        self.app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, self.message_handler))
        logger.info("Обработчик сообщений зарегистрирован (ALL, не COMMAND)")

        # Запускаем бота
        logger.info("Инициализация бота...")
        await self.app.initialize()
        logger.info("Бот инициализирован")
        await self.app.start()
        logger.info("Бот запущен")
        await self.app.updater.start_polling()
        logger.info("Polling запущен, бот готов к работе")

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

