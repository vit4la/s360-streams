#!/usr/bin/env python3
"""
Тестовый скрипт для проверки черновиков в БД и их отправки.
"""

import sqlite3
from datetime import datetime

# Подключаемся к БД
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Проверяем черновики со статусом pending_moderation
cursor.execute("""
    SELECT 
        d.id,
        d.title,
        d.body,
        d.status,
        d.created_at,
        d.image_query,
        s.channel_id,
        s.message_id
    FROM draft_posts d
    JOIN source_posts s ON d.source_post_id = s.id
    WHERE d.status = 'pending_moderation'
    ORDER BY d.created_at DESC
    LIMIT 10
""")

drafts = cursor.fetchall()

print(f"Найдено черновиков со статусом 'pending_moderation': {len(drafts)}\n")

if drafts:
    for draft in drafts:
        print(f"=== Draft ID: {draft['id']} ===")
        print(f"Статус: {draft['status']}")
        print(f"Создан: {draft['created_at']}")
        print(f"Канал: {draft['channel_id']}")
        print(f"Title: {draft['title'][:100] if draft['title'] else 'None'}...")
        print(f"Body (first 200): {draft['body'][:200] if draft['body'] else 'None'}...")
        print(f"Has emoji 🎾: {'🎾' in (draft['body'] or '')}")
        print(f"Has <b>: {'<b>' in (draft['body'] or '')}")
        print(f"image_query: {draft['image_query']}")
        print()
else:
    print("Нет черновиков со статусом 'pending_moderation'")
    print("\nПроверяем все черновики:")
    cursor.execute("""
        SELECT id, status, created_at, title
        FROM draft_posts
        ORDER BY created_at DESC
        LIMIT 10
    """)
    all_drafts = cursor.fetchall()
    for draft in all_drafts:
        print(f"  Draft ID: {draft['id']}, Status: {draft['status']}, Created: {draft['created_at']}")

conn.close()

