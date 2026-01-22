#!/usr/bin/env python3
"""
Тест парсинга VK группы
Проверяет два токена VK API
"""

import logging
import sys
import os
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

VK_GROUP_ID = 212808533

print("="*70)
print("ТЕСТИРОВАНИЕ ПАРСИНГА VK ГРУППЫ")
print("="*70)
print(f"Группа: tennisprimesport (ID: {VK_GROUP_ID})")
print()

# Загружаем токены из .env если есть
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip('"\'')
                if key in ["VK_TOKEN", "VK_TOKEN_2"] and key not in os.environ:
                    os.environ[key] = value

from vk_to_telegram import get_vk_posts_via_api, VK_TOKEN, VK_TOKEN_2

# Проверка первого токена
print("1. Проверка первого токена VK API...")
print("-" * 70)
token_1 = os.getenv("VK_TOKEN") or VK_TOKEN
if token_1 and token_1 != "VK_ACCESS_TOKEN":
    posts = get_vk_posts_via_api(token_1)
    if posts:
        print(f"   ✅ Первый токен работает! Получено {len(posts)} пост(ов)")
        for post in posts[:3]:
            post_id = post.get("id")
            text = post.get("text", "")[:50]
            attachments = post.get("attachments", [])
            has_video = any(a.get("type") == "video" for a in attachments)
            print(f"      - Пост {post_id}: {text}... [видео: {'да' if has_video else 'нет'}]")
    else:
        print("   ❌ Первый токен не вернул посты")
else:
    print("   ⚠️  Первый токен не задан")

print()

# Проверка второго токена
print("2. Проверка второго токена VK API...")
print("-" * 70)
token_2 = os.getenv("VK_TOKEN_2") or VK_TOKEN_2
if token_2 and token_2 != "":
    posts = get_vk_posts_via_api(token_2)
    if posts:
        print(f"   ✅ Второй токен работает! Получено {len(posts)} пост(ов)")
        for post in posts[:3]:
            post_id = post.get("id")
            text = post.get("text", "")[:50]
            attachments = post.get("attachments", [])
            has_video = any(a.get("type") == "video" for a in attachments)
            print(f"      - Пост {post_id}: {text}... [видео: {'да' if has_video else 'нет'}]")
    else:
        print("   ❌ Второй токен не вернул посты")
else:
    print("   ⚠️  Второй токен не задан")

print()

# Проверка общего метода get_vk_posts
print("3. Проверка общего метода get_vk_posts()...")
print("-" * 70)
try:
    from vk_to_telegram import get_vk_posts
    posts = get_vk_posts()
    if posts:
        print(f"   ✅ get_vk_posts() работает! Получено {len(posts)} пост(ов)")
        for post in posts[:3]:
            post_id = post.get("id")
            text = post.get("text", "")[:50]
            attachments = post.get("attachments", [])
            has_video = any(a.get("type") == "video" for a in attachments)
            print(f"      - Пост {post_id}: {text}... [видео: {'да' if has_video else 'нет'}]")
    else:
        print("   ❌ get_vk_posts() не вернул посты (оба токена не работают)")
except Exception as e:
    print(f"   ❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()

print()
print("="*70)
print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print("="*70)
