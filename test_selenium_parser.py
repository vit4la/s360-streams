#!/usr/bin/env python3
"""
Тест парсера VK через Selenium
"""

import sys
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

print("="*70)
print("Тестирование парсера VK через Selenium...")
print("="*70)

try:
    from vk_parser_selenium import get_vk_posts_selenium
    
    print("\n1. Запускаю Selenium парсер...")
    print("   (Это может занять 10-20 секунд, так как запускается браузер)")
    
    posts = get_vk_posts_selenium()
    
    print(f"\n2. Результат:")
    if posts:
        print(f"   ✅ УСПЕХ! Получено {len(posts)} пост(ов)")
        print("\n3. Первые посты:")
        for i, post in enumerate(posts[:3], 1):
            print(f"\n   Пост #{i}:")
            print(f"   ID: {post.get('id')}")
            text = post.get('text', '')
            if text:
                print(f"   Текст: {text[:100]}..." if len(text) > 100 else f"   Текст: {text}")
            else:
                print(f"   Текст: (пусто)")
            attachments = post.get('attachments', [])
            if attachments:
                print(f"   Вложения: {len(attachments)}")
    else:
        print("   ❌ Парсер не вернул посты")
        print("\n   Возможные причины:")
        print("   1. Cookies истекли или недействительны")
        print("   2. Группа недоступна даже с авторизацией")
        print("   3. Selenium не может найти посты на странице")
        print("   4. Проблемы с Chrome/ChromeDriver")
        print("\n   Проверьте:")
        print("   - Файл vk_cookies.txt существует и содержит cookies")
        print("   - Chrome/Chromium установлен: chromium-browser --version")
        print("   - ChromeDriver установлен: chromedriver --version")
        
except ImportError as e:
    print(f"\n❌ Ошибка импорта: {e}")
    print("\nУстановите Selenium:")
    print("  pip3 install selenium")
    print("  apt-get install chromium-browser chromium-chromedriver")
    
except Exception as e:
    print(f"\n❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
    print("\nПроверьте логи выше для деталей")

print("\n" + "="*70)
