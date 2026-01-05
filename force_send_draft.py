#!/usr/bin/env python3
"""
Скрипт для принудительной отправки черновика в бот модерации.
Сбрасывает статус отправки и перезапускает бот.
"""

import sys

print("=" * 60)
print("ПРИНУДИТЕЛЬНАЯ ОТПРАВКА ЧЕРНОВИКА")
print("=" * 60)

# Проверяем черновики
import sqlite3
conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("""
    SELECT id, title, status, created_at 
    FROM draft_posts 
    WHERE status = 'pending_moderation'
    ORDER BY created_at DESC
    LIMIT 5
""")
drafts = cursor.fetchall()

if not drafts:
    print("\n❌ Нет черновиков со статусом 'pending_moderation'")
    conn.close()
    sys.exit(1)

print(f"\nНайдено черновиков: {len(drafts)}")
for d in drafts:
    title_preview = d['title'][:50] if d['title'] else 'EMPTY'
    print(f"  - Draft ID: {d['id']}, Создан: {d['created_at']}, Заголовок: {title_preview}...")

print("\n" + "=" * 60)
print("РЕШЕНИЕ:")
print("=" * 60)
print("1. Перезапустите бот модерации (очистит память о sent_drafts):")
print("   sudo systemctl restart moderation-bot")
print("\n2. Отправьте команду /start в боте")
print("   Это принудительно вызовет _check_and_send_new_drafts()")
print("\n3. Или проверьте логи бота:")
print("   sudo journalctl -u moderation-bot -n 50 --no-pager | grep -i draft")
print("=" * 60)

conn.close()

