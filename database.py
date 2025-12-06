"""
Модуль для работы с базой данных SQLite.
Хранит исходные посты и черновики для модерации.
"""

import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с базой данных."""

    def __init__(self, db_path: str):
        """Инициализация подключения к БД.

        Args:
            db_path: Путь к файлу SQLite БД
        """
        self.db_path = db_path
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Получить соединение с БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self) -> None:
        """Создать таблицы, если их нет."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Таблица исходных постов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                text_original TEXT NOT NULL,
                photo_file_id TEXT,
                date TIMESTAMP NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, message_id)
            )
        """)
        
        # Добавляем колонку photo_file_id если её нет (для существующих БД)
        try:
            cursor.execute("ALTER TABLE source_posts ADD COLUMN photo_file_id TEXT")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

        # Таблица черновиков для модерации
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS draft_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_post_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                hashtags TEXT NOT NULL,
                gpt_response_raw TEXT,
                image_query TEXT,
                final_image_url TEXT,
                status TEXT NOT NULL DEFAULT 'pending_moderation',
                target_chat_id TEXT,
                target_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_post_id) REFERENCES source_posts(id)
            )
        """)
        
        # Добавляем колонки для картинок, если их нет (для существующих БД)
        try:
            cursor.execute("ALTER TABLE draft_posts ADD COLUMN image_query TEXT")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
        try:
            cursor.execute("ALTER TABLE draft_posts ADD COLUMN final_image_url TEXT")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
        try:
            cursor.execute("ALTER TABLE draft_posts ADD COLUMN pexels_images_json TEXT")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

        # Индексы для быстрого поиска
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_source_posts_status 
            ON source_posts(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_draft_posts_status 
            ON draft_posts(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_source_posts_channel_message 
            ON source_posts(channel_id, message_id)
        """)

        conn.commit()
        conn.close()
        logger.info("База данных инициализирована: %s", self.db_path)

    def add_source_post(
        self,
        channel_id: str,
        message_id: int,
        text_original: str,
        date: datetime,
        photo_file_id: Optional[str] = None,
    ) -> Optional[int]:
        """Добавить исходный пост в БД.

        Args:
            channel_id: ID канала
            message_id: ID сообщения
            text_original: Оригинальный текст поста
            date: Дата поста
            photo_file_id: file_id картинки из поста (опционально)

        Returns:
            ID созданного поста или None, если пост уже существует
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO source_posts (channel_id, message_id, text_original, photo_file_id, date, status)
                VALUES (?, ?, ?, ?, ?, 'new')
            """, (channel_id, str(message_id), text_original, photo_file_id, date))
            post_id = cursor.lastrowid
            conn.commit()
            logger.debug("Добавлен исходный пост: channel_id=%s, message_id=%s, id=%s", 
                        channel_id, message_id, post_id)
            return post_id
        except sqlite3.IntegrityError:
            # Пост уже существует (дубль)
            logger.debug("Пост уже существует: channel_id=%s, message_id=%s", 
                        channel_id, message_id)
            return None
        finally:
            conn.close()

    def get_new_source_posts(self) -> List[Dict[str, Any]]:
        """Получить все исходные посты со статусом 'new'.

        Returns:
            Список словарей с данными постов
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, channel_id, message_id, text_original, date
            FROM source_posts
            WHERE status = 'new'
            ORDER BY date ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        posts = []
        for row in rows:
            posts.append({
                "id": row["id"],
                "channel_id": row["channel_id"],
                "message_id": row["message_id"],
                "text_original": row["text_original"],
                "date": row["date"],
            })

        return posts

    def mark_source_post_processed(self, post_id: int) -> None:
        """Отметить исходный пост как обработанный.

        Args:
            post_id: ID поста
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE source_posts
            SET status = 'processed'
            WHERE id = ?
        """, (post_id,))

        conn.commit()
        conn.close()
        logger.debug("Исходный пост отмечен как обработанный: id=%s", post_id)

    def add_draft_post(
        self,
        source_post_id: int,
        title: str,
        body: str,
        hashtags: str,
        gpt_response_raw: Optional[str] = None,
        image_query: Optional[str] = None,
        final_image_url: Optional[str] = None,
        pexels_images_json: Optional[str] = None,
    ) -> int:
        """Добавить черновик для модерации.

        Args:
            source_post_id: ID исходного поста
            title: Заголовок
            body: Текст поста
            hashtags: Хэштеги (строка)
            gpt_response_raw: Сырой JSON ответ GPT (опционально)
            image_query: Запрос для поиска картинки (опционально)
            final_image_url: URL стилизованной картинки (опционально)

        Returns:
            ID созданного черновика
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO draft_posts 
            (source_post_id, title, body, hashtags, gpt_response_raw, image_query, final_image_url, pexels_images_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_moderation')
        """, (source_post_id, title, body, hashtags, gpt_response_raw, image_query, final_image_url, pexels_images_json))

        draft_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info("Создан черновик: id=%s, source_post_id=%s", draft_id, source_post_id)
        return draft_id

    def get_pending_draft_posts(self) -> List[Dict[str, Any]]:
        """Получить все черновики со статусом 'pending_moderation'.

        Returns:
            Список словарей с данными черновиков
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                d.id,
                d.source_post_id,
                d.title,
                d.body,
                d.hashtags,
                d.gpt_response_raw,
                d.image_query,
                d.final_image_url,
                d.pexels_images_json,
                d.created_at,
                s.channel_id,
                s.message_id,
                s.text_original,
                s.photo_file_id,
                s.date as source_date
            FROM draft_posts d
            JOIN source_posts s ON d.source_post_id = s.id
            WHERE d.status = 'pending_moderation'
            ORDER BY d.created_at ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        drafts = []
        for row in rows:
            drafts.append({
                "id": row["id"],
                "source_post_id": row["source_post_id"],
                "title": row["title"],
                "body": row["body"],
                "hashtags": row["hashtags"],
                "gpt_response_raw": row["gpt_response_raw"],
                "image_query": row["image_query"] if "image_query" in row.keys() else None,
                "final_image_url": row["final_image_url"] if "final_image_url" in row.keys() else None,
                "pexels_images_json": row["pexels_images_json"] if "pexels_images_json" in row.keys() else None,
                "created_at": row["created_at"],
                "channel_id": row["channel_id"],
                "message_id": row["message_id"],
                "text_original": row["text_original"],
                "photo_file_id": row["photo_file_id"] if "photo_file_id" in row.keys() else None,
                "source_date": row["source_date"],
            })

        return drafts

    def get_draft_post(self, draft_id: int) -> Optional[Dict[str, Any]]:
        """Получить черновик по ID.

        Args:
            draft_id: ID черновика

        Returns:
            Словарь с данными черновика или None
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                d.id,
                d.source_post_id,
                d.title,
                d.body,
                d.hashtags,
                d.gpt_response_raw,
                d.image_query,
                d.final_image_url,
                d.pexels_images_json,
                d.status,
                d.target_chat_id,
                d.target_message_id,
                s.channel_id,
                s.message_id,
                s.text_original,
                s.photo_file_id
            FROM draft_posts d
            JOIN source_posts s ON d.source_post_id = s.id
            WHERE d.id = ?
        """, (draft_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        result = {
            "id": row["id"],
            "source_post_id": row["source_post_id"],
            "title": row["title"],
            "body": row["body"],
            "hashtags": row["hashtags"],
            "gpt_response_raw": row["gpt_response_raw"],
            "image_query": row["image_query"] if "image_query" in row.keys() else None,
            "final_image_url": row["final_image_url"] if "final_image_url" in row.keys() else None,
            "pexels_images_json": row["pexels_images_json"] if "pexels_images_json" in row.keys() else None,
            "status": row["status"],
            "target_chat_id": row["target_chat_id"],
            "target_message_id": row["target_message_id"],
            "channel_id": row["channel_id"],
            "message_id": row["message_id"],
            "text_original": row["text_original"],
        }
        # Добавляем photo_file_id если есть
        if "photo_file_id" in row.keys():
            result["photo_file_id"] = row["photo_file_id"]
        return result

    def update_draft_post(
        self,
        draft_id: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        hashtags: Optional[str] = None,
        status: Optional[str] = None,
        final_image_url: Optional[str] = None,
        pexels_images_json: Optional[str] = None,
    ) -> None:
        """Обновить черновик.

        Args:
            draft_id: ID черновика
            title: Новый заголовок (опционально)
            body: Новый текст (опционально)
            hashtags: Новые хэштеги (опционально)
            status: Новый статус (опционально)
            final_image_url: URL стилизованной картинки (опционально)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        updates = []
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if body is not None:
            updates.append("body = ?")
            params.append(body)
        if hashtags is not None:
            updates.append("hashtags = ?")
            params.append(hashtags)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if final_image_url is not None:
            updates.append("final_image_url = ?")
            params.append(final_image_url)

        if pexels_images_json is not None:
            updates.append("pexels_images_json = ?")
            params.append(pexels_images_json)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(draft_id)

            query = f"UPDATE draft_posts SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()

        conn.close()
        logger.debug("Черновик обновлён: id=%s", draft_id)

    def mark_draft_published(
        self,
        draft_id: int,
        target_chat_id: str,
        target_message_id: int,
    ) -> None:
        """Отметить черновик как опубликованный.

        Args:
            draft_id: ID черновика
            target_chat_id: ID целевого канала
            target_message_id: ID сообщения в целевом канале
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE draft_posts
            SET status = 'published',
                target_chat_id = ?,
                target_message_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (target_chat_id, target_message_id, draft_id))

        conn.commit()
        conn.close()
        logger.info("Черновик отмечен как опубликованный: id=%s, target_chat_id=%s", 
                   draft_id, target_chat_id)

    def mark_draft_rejected(self, draft_id: int) -> None:
        """Отметить черновик как отклонённый.

        Args:
            draft_id: ID черновика
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE draft_posts
            SET status = 'rejected',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (draft_id,))

        conn.commit()
        conn.close()
        logger.info("Черновик отмечен как отклонённый: id=%s", draft_id)


