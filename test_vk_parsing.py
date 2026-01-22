#!/usr/bin/env python3
"""
Тест парсинга VK группы
Проверяет все доступные методы получения постов
"""

import logging
import sys
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

VK_GROUP_ID = 212808533
VK_GROUP_URL = "https://vk.com/tennisprimesport"

print("="*70)
print("ТЕСТИРОВАНИЕ ПАРСИНГА VK ГРУППЫ")
print("="*70)
print(f"Группа: tennisprimesport (ID: {VK_GROUP_ID})")
print(f"URL: {VK_GROUP_URL}")
print()

# Метод 1: VK API напрямую
print("1. Проверка VK API (wall.get)...")
print("-" * 70)
try:
    import os
    
    # Загружаем токен из .env если есть
    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        with open(_env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    value = value.strip('"\'')
                    if key == "VK_TOKEN" and key not in os.environ:
                        os.environ[key] = value
    
    from vk_to_telegram import get_vk_posts_via_api
    posts = get_vk_posts_via_api()
    if posts:
        print(f"   ✅ VK API работает! Получено {len(posts)} пост(ов)")
        for post in posts[:3]:
            post_id = post.get("id")
            text = post.get("text", "")[:50]
            attachments = post.get("attachments", [])
            has_video = any(a.get("type") == "video" for a in attachments)
            print(f"      - Пост {post_id}: {text}... [видео: {'да' if has_video else 'нет'}]")
    else:
        print("   ❌ VK API не вернул посты (проверьте токен или группа закрыта)")
except Exception as e:
    print(f"   ❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()

print()

# Метод 2: RSS фид
print("2. Проверка RSS фида...")
print("-" * 70)
try:
    from vk_to_telegram import get_vk_posts_scraping
    posts = get_vk_posts_scraping()
    if posts:
        print(f"   ✅ RSS работает! Получено {len(posts)} пост(ов)")
        for post in posts[:3]:
            post_id = post.get("id")
            text = post.get("text", "")[:50]
            print(f"      - Пост {post_id}: {text}...")
    else:
        print("   ❌ RSS не вернул посты (группа может быть закрытой)")
except Exception as e:
    print(f"   ❌ Ошибка RSS: {e}")

print()

# Метод 3: Парсинг с cookies
print("3. Проверка парсинга с cookies...")
print("-" * 70)
try:
    from vk_parser_with_auth import get_vk_posts_with_auth
    posts = get_vk_posts_with_auth()
    if posts:
        print(f"   ✅ Парсинг с cookies работает! Получено {len(posts)} пост(ов)")
        for post in posts[:3]:
            post_id = post.get("id")
            text = post.get("text", "")[:50]
            print(f"      - Пост {post_id}: {text}...")
    else:
        print("   ❌ Парсинг с cookies не вернул посты")
except ImportError:
    print("   ⚠️  vk_parser_with_auth не найден")
except Exception as e:
    print(f"   ❌ Ошибка парсинга с cookies: {e}")

print()

# Метод 4: Selenium
print("4. Проверка Selenium парсера...")
print("-" * 70)
try:
    from vk_parser_selenium import get_vk_posts_selenium
    print("   (Это может занять 10-20 секунд...)")
    posts = get_vk_posts_selenium()
    if posts:
        print(f"   ✅ Selenium работает! Получено {len(posts)} пост(ов)")
        for post in posts[:3]:
            post_id = post.get("id")
            text = post.get("text", "")[:50]
            print(f"      - Пост {post_id}: {text}...")
    else:
        print("   ❌ Selenium не вернул посты")
except ImportError:
    print("   ⚠️  Selenium не установлен")
except Exception as e:
    print(f"   ❌ Ошибка Selenium: {e}")

print()
print("="*70)
print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print("="*70)
