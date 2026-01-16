#!/usr/bin/env python3
"""
Проверка токена формата vk1.a. для wall.get
"""

import requests

# Новый токен формата vk1.a.
NEW_TOKEN = "vk1.a.zKf_R2h2HH3Rs04wRYzCMmsNr1rUbf8k9QYWMxwFcEl4ScUVSO5gTmpJDIwYJUWVa109xC4Y6l19504-IPgZ87AJeeUlqwCft-k"

VK_GROUP_ID = 212808533
VK_API_VERSION = "5.199"

print("="*70)
print("ПРОВЕРКА ТОКЕНА ФОРМАТА vk1.a. ДЛЯ wall.get")
print("="*70)
print(f"Группа: tennisprimesport (ID: {VK_GROUP_ID})")
print(f"Токен: {NEW_TOKEN[:50]}...")
print()

url = "https://api.vk.com/method/wall.get"
params = {
    "access_token": NEW_TOKEN,
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
        
        if error_code == 15:
            print("\n⚠️  Ошибка 15: Access denied")
            print("   Группа закрыта или токен не имеет доступа")
        elif error_code == 5:
            print("\n⚠️  Ошибка 5: Токен недействителен")
            print("   Возможно, токен формата vk1.a. не поддерживается для wall.get")
        elif error_code == 113:
            print("\n⚠️  Ошибка 113: Invalid user id")
        else:
            print(f"\n⚠️  Неизвестная ошибка: {error_code}")
    else:
        items = data.get("response", {}).get("items", [])
        print(f"✅ ТОКЕН РАБОТАЕТ! Получено {len(items)} пост(ов)")
        if items:
            post = items[0]
            print(f"   Последний пост ID: {post.get('id')}")
        print("\n✅ Токен формата vk1.a. работает для wall.get!")
        
except Exception as e:
    print(f"❌ Ошибка при запросе: {e}")
