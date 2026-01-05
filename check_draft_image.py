#!/usr/bin/env python3
"""
Проверка наличия картинки в черновике.
"""

import sqlite3
import sys

conn = sqlite3.connect("posts.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Проверяем последние черновики
cursor.execute("""
    SELECT id, title, final_image_url, image_query, pexels_images_json, created_at
    FROM draft_posts
    WHERE status = 'pending_moderation' OR status = 'approved'
    ORDER BY created_at DESC
    LIMIT 5
""")

drafts = cursor.fetchall()

print("=" * 60)
print("ПРОВЕРКА КАРТИНОК В ЧЕРНОВИКАХ")
print("=" * 60)

for draft in drafts:
    draft_id = draft['id']
    final_image_url = draft['final_image_url']
    image_query = draft['image_query']
    pexels_images = draft['pexels_images_json']
    
    print(f"\nDraft ID: {draft_id}")
    print(f"  Заголовок: {draft['title'][:50] if draft['title'] else 'EMPTY'}...")
    print(f"  Создан: {draft['created_at']}")
    print(f"  final_image_url: {'✅ ЕСТЬ' if final_image_url else '❌ НЕТ'}")
    if final_image_url:
        print(f"    URL: {final_image_url[:80]}...")
    print(f"  image_query: {'✅ ЕСТЬ' if image_query else '❌ НЕТ'}")
    if image_query:
        print(f"    Запрос: {image_query}")
    print(f"  pexels_images_json: {'✅ ЕСТЬ' if pexels_images else '❌ НЕТ'}")
    if pexels_images:
        import json
        try:
            images = json.loads(pexels_images)
            print(f"    Количество картинок: {len(images)}")
        except:
            print(f"    Ошибка парсинга JSON")

print("\n" + "=" * 60)
print("РЕКОМЕНДАЦИИ:")
print("=" * 60)

# Проверяем последний опубликованный черновик
cursor.execute("""
    SELECT id, final_image_url, image_query
    FROM draft_posts
    WHERE status = 'approved'
    ORDER BY created_at DESC
    LIMIT 1
""")
last_published = cursor.fetchone()

if last_published:
    print(f"\nПоследний опубликованный черновик (ID: {last_published['id']}):")
    if last_published['final_image_url']:
        print("  ✅ Имел final_image_url - картинка должна была быть отправлена")
    else:
        print("  ❌ НЕ имел final_image_url - картинка не была отправлена")
        if last_published['image_query']:
            print("  ⚠️  Но был image_query - значит картинки были найдены в Pexels")
            print("  → Оператор должен был выбрать картинку из Pexels или загрузить свою")

conn.close()

