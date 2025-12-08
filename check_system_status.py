#!/usr/bin/env python3
"""
Диагностический скрипт для проверки состояния системы модерации постов.
Проверяет наличие новых постов, черновиков и их статусы.
"""

import sqlite3
from datetime import datetime
import sys

# Подключаемся к БД
try:
    conn = sqlite3.connect("posts.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
except Exception as e:
    print(f"❌ Ошибка подключения к БД: {e}")
    sys.exit(1)

print("=" * 60)
print("ПРОВЕРКА СИСТЕМЫ МОДЕРАЦИИ ПОСТОВ")
print("=" * 60)

# 1. Проверяем исходные посты со статусом 'new'
print("\n1. ИСХОДНЫЕ ПОСТЫ (source_posts):")
print("-" * 60)

cursor.execute("""
    SELECT COUNT(*) as count
    FROM source_posts
    WHERE status = 'new'
""")
new_posts_count = cursor.fetchone()['count']
print(f"   Постов со статусом 'new': {new_posts_count}")

if new_posts_count > 0:
    cursor.execute("""
        SELECT id, channel_id, message_id, text_original, date, status
        FROM source_posts
        WHERE status = 'new'
        ORDER BY date DESC
        LIMIT 5
    """)
    new_posts = cursor.fetchall()
    print(f"\n   Последние {len(new_posts)} постов со статусом 'new':")
    for post in new_posts:
        text_preview = post['text_original'][:80] if post['text_original'] else 'EMPTY'
        print(f"   - ID: {post['id']}, Канал: {post['channel_id']}, "
              f"Дата: {post['date']}, Текст: {text_preview}...")

cursor.execute("""
    SELECT COUNT(*) as count
    FROM source_posts
    WHERE status = 'processed'
""")
processed_count = cursor.fetchone()['count']
print(f"\n   Постов со статусом 'processed': {processed_count}")

cursor.execute("""
    SELECT id, channel_id, message_id, date, status
    FROM source_posts
    ORDER BY date DESC
    LIMIT 1
""")
last_post = cursor.fetchone()
if last_post:
    print(f"\n   Последний пост в БД:")
    print(f"   - ID: {last_post['id']}, Канал: {last_post['channel_id']}, "
          f"Дата: {last_post['date']}, Статус: {last_post['status']}")

# 2. Проверяем черновики
print("\n2. ЧЕРНОВИКИ (draft_posts):")
print("-" * 60)

cursor.execute("""
    SELECT COUNT(*) as count
    FROM draft_posts
    WHERE status = 'pending_moderation'
""")
pending_drafts_count = cursor.fetchone()['count']
print(f"   Черновиков со статусом 'pending_moderation': {pending_drafts_count}")

if pending_drafts_count > 0:
    cursor.execute("""
        SELECT d.id, d.title, d.status, d.created_at, d.image_query,
               s.channel_id, s.message_id
        FROM draft_posts d
        JOIN source_posts s ON d.source_post_id = s.id
        WHERE d.status = 'pending_moderation'
        ORDER BY d.created_at DESC
        LIMIT 5
    """)
    pending_drafts = cursor.fetchall()
    print(f"\n   Последние {len(pending_drafts)} черновиков 'pending_moderation':")
    for draft in pending_drafts:
        title_preview = draft['title'][:50] if draft['title'] else 'EMPTY'
        print(f"   - Draft ID: {draft['id']}, Создан: {draft['created_at']}, "
              f"Заголовок: {title_preview}...")
        print(f"     Канал: {draft['channel_id']}, Image query: {draft['image_query']}")

cursor.execute("""
    SELECT COUNT(*) as count
    FROM draft_posts
    WHERE status = 'approved'
""")
approved_count = cursor.fetchone()['count']
print(f"\n   Черновиков со статусом 'approved': {approved_count}")

cursor.execute("""
    SELECT COUNT(*) as count
    FROM draft_posts
    WHERE status = 'rejected'
""")
rejected_count = cursor.fetchone()['count']
print(f"   Черновиков со статусом 'rejected': {rejected_count}")

cursor.execute("""
    SELECT d.id, d.title, d.status, d.created_at
    FROM draft_posts d
    ORDER BY d.created_at DESC
    LIMIT 1
""")
last_draft = cursor.fetchone()
if last_draft:
    print(f"\n   Последний черновик в БД:")
    print(f"   - Draft ID: {last_draft['id']}, Статус: {last_draft['status']}, "
          f"Создан: {last_draft['created_at']}")

# 3. Проверяем связь между постами и черновиками
print("\n3. СВЯЗЬ МЕЖДУ ПОСТАМИ И ЧЕРНОВИКАМИ:")
print("-" * 60)

cursor.execute("""
    SELECT 
        COUNT(DISTINCT s.id) as posts_without_drafts
    FROM source_posts s
    LEFT JOIN draft_posts d ON s.id = d.source_post_id
    WHERE s.status = 'new' AND d.id IS NULL
""")
posts_without_drafts = cursor.fetchone()['posts_without_drafts']
print(f"   Постов 'new' без черновиков: {posts_without_drafts}")

# 4. Рекомендации
print("\n4. РЕКОМЕНДАЦИИ:")
print("-" * 60)

if new_posts_count > 0:
    print(f"   ⚠️  Найдено {new_posts_count} постов со статусом 'new'.")
    print("      → Проверьте, работает ли GPT воркер (gpt_worker.py)")
    print("      → Проверьте логи GPT воркера на ошибки")
else:
    print("   ✓ Нет постов со статусом 'new'")
    print("      → Проверьте, работает ли Telethon listener (telethon_listener.py)")
    print("      → Проверьте, получает ли listener новые посты из каналов")

if pending_drafts_count > 0:
    print(f"\n   ⚠️  Найдено {pending_drafts_count} черновиков 'pending_moderation'.")
    print("      → Проверьте, работает ли бот модерации (moderation_bot.py)")
    print("      → Проверьте логи бота на ошибки отправки")
    print("      → Попробуйте команду /start в боте для принудительной проверки")
else:
    print("\n   ✓ Нет черновиков 'pending_moderation'")
    if new_posts_count == 0:
        print("      → Система работает нормально, новых постов нет")

if posts_without_drafts > 0:
    print(f"\n   ⚠️  Найдено {posts_without_drafts} постов 'new' без черновиков.")
    print("      → GPT воркер не обрабатывает эти посты")
    print("      → Проверьте логи GPT воркера")

print("\n" + "=" * 60)
print("Для проверки логов сервисов:")
print("  sudo journalctl -u telethon-listener -n 50")
print("  sudo journalctl -u gpt-worker -n 50")
print("  sudo journalctl -u moderation-bot -n 50")
print("=" * 60)

conn.close()

