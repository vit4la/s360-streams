#!/usr/bin/env python3
"""
Скрипт для переотправки последнего реального поста в бот модерации.
Берёт последний пост из source_posts и создаёт его копию с новым message_id.
"""

import sqlite3
from datetime import datetime
import time

# Подключаемся к БД
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Находим последний реальный пост (не тестовый)
cursor.execute("""
    SELECT id, channel_id, message_id, text_original, photo_file_id, date
    FROM source_posts
    WHERE channel_id != '@test_channel'
    ORDER BY id DESC
    LIMIT 1
""")

last_post = cursor.fetchone()

if not last_post:
    print("❌ Не найдено реальных постов в базе данных")
    conn.close()
    exit(1)

print(f"📋 Найден последний пост:")
print(f"   ID: {last_post['id']}")
print(f"   Канал: {last_post['channel_id']}")
print(f"   Текст (первые 100 символов): {last_post['text_original'][:100]}...")

# Создаём новый пост с тем же текстом, но с новым message_id
# Используем текущий timestamp как message_id, чтобы избежать конфликтов
new_message_id = int(time.time())

cursor.execute("""
    INSERT INTO source_posts 
    (channel_id, message_id, text_original, photo_file_id, date, status)
    VALUES (?, ?, ?, ?, ?, 'new')
""", (
    last_post['channel_id'],
    new_message_id,
    last_post['text_original'],
    last_post['photo_file_id'],
    datetime.now()
))

new_post_id = cursor.lastrowid
conn.commit()
conn.close()

print(f"\n✅ Создан новый пост для обработки:")
print(f"   ID: {new_post_id}")
print(f"   Message ID: {new_message_id}")
print(f"   Статус: 'new'")
print(f"\n📝 GPT воркер обработает его в течение 5-10 секунд")
print(f"📱 Черновик появится в боте автоматически")

