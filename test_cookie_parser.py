#!/usr/bin/env python3
"""
Тест парсера VK с cookies
"""

import sys
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

try:
    from vk_parser_with_auth import get_vk_posts_with_auth
    
    print("Тестирование парсера VK с cookies...")
    print("="*70)
    
    posts = get_vk_posts_with_auth()
    
    if posts:
        print(f"✅ УСПЕХ! Получено {len(posts)} пост(ов)")
        for i, post in enumerate(posts[:3], 1):
            print(f"\n{i}. Пост ID: {post.get('id')}")
            print(f"   Текст: {post.get('text', '')[:100]}...")
    else:
        print("❌ Парсер не вернул посты")
        print("\nВозможные причины:")
        print("1. Cookies истекли или недействительны")
        print("2. Группа недоступна даже с авторизацией")
        print("3. Структура страницы VK изменилась")
        print("\nПроверьте файл vk_cookies.txt и обновите cookies если нужно")
        
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("Убедитесь, что файл vk_parser_with_auth.py существует")
except Exception as e:
    print(f"❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
