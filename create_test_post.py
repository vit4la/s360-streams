#!/usr/bin/env python3
"""
Скрипт для создания тестового исходного поста для обработки.
"""

import sqlite3
from datetime import datetime

# Подключаемся к БД
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Тестовый текст поста
test_text = """Жоао Фонсека сбрил кудри после победы в Базеле. Бразильский теннисист выполнил свое обещание и изменил образ после успешного выступления на турнире."""

# Создаём тестовый исходный пост
cursor.execute("""
    INSERT INTO source_posts 
    (channel_id, message_id, text_original, date, status)
    VALUES (?, ?, ?, ?, 'new')
""", ("@test_channel", 99999, test_text, datetime.now()))

post_id = cursor.lastrowid
conn.commit()
conn.close()

print(f"✅ Создан тестовый пост ID: {post_id}")
print(f"Текст: {test_text[:100]}...")
print("\nGPT воркер обработает его в течение 5-10 секунд")
print("Черновик появится в боте автоматически")

