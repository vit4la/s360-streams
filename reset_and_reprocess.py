#!/usr/bin/env python3
"""
Скрипт для удаления старых черновиков и повторной обработки последнего поста.
"""

import sqlite3
import sys

# Подключаемся к БД
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1. Удаляем все старые черновики
cursor.execute("DELETE FROM draft_posts")
deleted_count = cursor.rowcount
print(f"Удалено черновиков: {deleted_count}")

# 2. Находим последний исходный пост
cursor.execute("""
    SELECT id, channel_id, message_id, text_original, status
    FROM source_posts
    ORDER BY id DESC
    LIMIT 1
""")

post = cursor.fetchone()

if not post:
    print("Нет исходных постов в БД")
    conn.close()
    sys.exit(1)

post_id = post['id']
print(f"\nНайден последний пост ID: {post_id}")
print(f"Канал: {post['channel_id']}")
print(f"Статус: {post['status']}")
print(f"Текст (first 200): {post['text_original'][:200] if post['text_original'] else 'EMPTY'}...")

# 3. Помечаем пост как 'new' для повторной обработки
cursor.execute("""
    UPDATE source_posts
    SET status = 'new'
    WHERE id = ?
""", (post_id,))

conn.commit()
conn.close()

print(f"\nПост {post_id} помечен как 'new' для повторной обработки")
print("GPT воркер обработает его заново с новой логикой (HTML + эмоджи)")
print("Подожди 5-10 секунд, черновик должен появиться")

