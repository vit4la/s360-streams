#!/usr/bin/env python3
"""
Скрипт для обновления черновика тестовым HTML-текстом с эмоджи для проверки.
"""

import sqlite3
import sys

# Подключаемся к БД
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Находим последний черновик со статусом pending_moderation
cursor.execute("""
    SELECT id, title, body
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
print(f"Старый body (first 200): {draft['body'][:200] if draft['body'] else 'EMPTY'}")

# Обновляем тестовым HTML-текстом с эмоджи
test_html = """🎾 <b>Тестовый пост с эмоджи и HTML-форматированием</b>

Это <b>тестовый пост</b> для проверки работы эмоджи и HTML-форматирования.

<i>Теннисный матч</i> прошел успешно! 🏆

#теннис #Setka360 #тест"""

cursor.execute("""
    UPDATE draft_posts
    SET body = ?
    WHERE id = ?
""", (test_html, draft_id))

conn.commit()
conn.close()

print(f"\nЧерновик {draft_id} обновлен тестовым HTML-текстом с эмоджи!")
print(f"Новый body: {test_html[:200]}...")

