#!/usr/bin/env python3
"""
Скрипт для проверки, какой токен VK работает для wall.get
"""

import requests
import sys

# Ключи для проверки
SERVICE_KEY = "3621a11a3621a11a3621a11a8a351c1fa9336213621a11a5f0e4d10720acc3bddc32da5"
PROTECTED_KEY = "oprOGUVvCwDnFKsvAZIr"

VK_GROUP_ID = 212808533
VK_API_VERSION = "5.199"

def test_token(token_name, token):
    """Проверить, работает ли токен для wall.get"""
    print(f"\n{'='*60}")
    print(f"Проверка {token_name} ключа...")
    print(f"{'='*60}")
    
    url = "https://api.vk.com/method/wall.get"
    params = {
        "access_token": token,
        "v": VK_API_VERSION,
        "owner_id": -VK_GROUP_ID,
        "count": 1,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if "error" in data:
            error = data["error"]
            error_code = error.get("error_code", "?")
            error_msg = error.get("error_msg", "Unknown error")
            print(f"❌ Ошибка: {error_code} - {error_msg}")
            return False
        else:
            items = data.get("response", {}).get("items", [])
            print(f"✅ Токен работает! Получено {len(items)} пост(ов)")
            if items:
                post = items[0]
                print(f"   Последний пост ID: {post.get('id')}")
            return True
    except Exception as e:
        print(f"❌ Ошибка при запросе: {e}")
        return False

if __name__ == "__main__":
    print("Проверка токенов VK для wall.get")
    print(f"Группа: tennisprimesport (ID: {VK_GROUP_ID})")
    
    # Проверяем сервисный ключ
    service_works = test_token("Сервисный", SERVICE_KEY)
    
    # Проверяем защищенный ключ
    protected_works = test_token("Защищенный", PROTECTED_KEY)
    
    print(f"\n{'='*60}")
    print("РЕЗУЛЬТАТЫ:")
    print(f"{'='*60}")
    if service_works:
        print("✅ Сервисный ключ РАБОТАЕТ - используйте его!")
        print(f"   Токен: {SERVICE_KEY}")
    elif protected_works:
        print("✅ Защищенный ключ РАБОТАЕТ - используйте его!")
        print(f"   Токен: {PROTECTED_KEY}")
    else:
        print("❌ Ни один из ключей не работает для wall.get")
        print("   Возможно, нужен токен пользователя через OAuth")
