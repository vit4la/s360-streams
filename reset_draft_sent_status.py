#!/usr/bin/env python3
"""
Скрипт для сброса статуса отправки черновика, чтобы он снова пришел в бот.
"""

import sqlite3
import sys

# Подключаемся к БД
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Находим последний черновик со статусом pending_moderation
cursor.execute("""
    SELECT id, title, body, created_at
    FROM draft_posts
    WHERE status = 'pending_moderation'
    ORDER BY id DESC
    LIMIT 1
""")

draft = cursor.fetchone()

if not draft:
    print("Нет черновиков со статусом 'pending_moderation'")
    sys.exit(1)

draft_id = draft['id']
print(f"Найден черновик ID: {draft_id}")
print(f"Создан: {draft['created_at']}")
print(f"Body содержит эмоджи 🎾: {'🎾' in (draft['body'] or '')}")
print(f"Body содержит <b>: {'<b>' in (draft['body'] or '')}")

# Обновляем created_at на текущее время, чтобы черновик не считался старым
from datetime import datetime
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

cursor.execute("""
    UPDATE draft_posts
    SET created_at = ?
    WHERE id = ?
""", (now, draft_id))

conn.commit()
conn.close()

print(f"\nЧерновик {draft_id} обновлен: created_at = {now}")
print("Теперь он должен прийти в бот (перезапусти бота или подожди 10 секунд)")

