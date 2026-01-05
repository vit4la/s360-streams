#!/usr/bin/env python3
"""
Скрипт для создания тестового поста с проверкой нового шаблона.
"""

import sqlite3
from datetime import datetime
import time

# Подключаемся к БД
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Создаем тестовый пост
test_text = """Карлос Алькарас одержал победу над Новаком Джоковичем в финале турнира ATP Masters 1000.

Испанец выиграл со счетом 6:4, 3:6, 7:6(5) в напряженном трехсетовом матче, который длился более трех часов.

Это первая победа Алькараса над Джоковичем в этом сезоне."""

# Создаем новый пост с текущим timestamp как message_id
new_message_id = int(time.time())

cursor.execute("""
    INSERT INTO source_posts 
    (channel_id, message_id, text_original, photo_file_id, date, status)
    VALUES (?, ?, ?, ?, ?, 'new')
""", (
    '@test_channel',
    new_message_id,
    test_text,
    None,
    datetime.now()
))

new_post_id = cursor.lastrowid
conn.commit()
conn.close()

print(f"✅ Создан тестовый пост:")
print(f"   ID: {new_post_id}")
print(f"   Message ID: {new_message_id}")
print(f"   Статус: 'new'")
print(f"\n📝 GPT воркер обработает его через несколько секунд")
print(f"📬 Затем черновик придет в бот модерации")

