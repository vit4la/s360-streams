#!/usr/bin/env python3
"""
Скрипт для сброса статуса отправки черновиков.
Очищает информацию о том, кому были отправлены черновики, чтобы бот отправил их заново.
"""

import sqlite3
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
print("СБРОС СТАТУСА ОТПРАВКИ ЧЕРНОВИКОВ")
print("=" * 60)

# Проверяем черновики pending_moderation
cursor.execute("""
    SELECT COUNT(*) as count
    FROM draft_posts
    WHERE status = 'pending_moderation'
""")
pending_count = cursor.fetchone()['count']
print(f"\nНайдено черновиков 'pending_moderation': {pending_count}")

if pending_count == 0:
    print("\n⚠️  Нет черновиков для сброса статуса.")
    print("   Проверьте, есть ли новые посты в БД и обрабатываются ли они GPT воркером.")
    conn.close()
    sys.exit(0)

# Показываем список черновиков
cursor.execute("""
    SELECT d.id, d.title, d.created_at
    FROM draft_posts d
    WHERE d.status = 'pending_moderation'
    ORDER BY d.created_at DESC
    LIMIT 10
""")
drafts = cursor.fetchall()

print(f"\nПоследние {len(drafts)} черновиков 'pending_moderation':")
for draft in drafts:
    title_preview = draft['title'][:50] if draft['title'] else 'EMPTY'
    print(f"  - Draft ID: {draft['id']}, Создан: {draft['created_at']}, "
          f"Заголовок: {title_preview}...")

print("\n" + "=" * 60)
print("ИНСТРУКЦИЯ:")
print("=" * 60)
print("Для сброса статуса отправки черновиков нужно:")
print("1. Перезапустить бот модерации (moderation-bot)")
print("2. Это очистит память о том, кому были отправлены черновики")
print("3. Бот отправит все черновики 'pending_moderation' заново")
print("\nКоманда для перезапуска:")
print("  sudo systemctl restart moderation-bot")
print("\nИли отправьте команду /start в боте для принудительной проверки")
print("=" * 60)

conn.close()

