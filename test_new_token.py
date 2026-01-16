#!/usr/bin/env python3
"""
Проверка нового токена пользователя через OAuth
"""

import requests

# Новый токен пользователя, полученный через OAuth
NEW_TOKEN = "vk1.a.LSaMaMv9ZuMr9a1VNgV8nbnxcbJ2sTsak-9r-NEzNxvQRH2S37JX3ctrsB1vAnmAAmJRBatzNMHkPnhHXzY-V-MNPiH96istX1cOzcTk3AKr-aWQwymLRILWp0YiZSsWgwolbz2yAFxXygOlvpdV1KjKcWVxzbqHSp-nZ3cL8_x1ceaa51bQPq4h9bRoTW0IUlJKtEpZoZGwMWZCmhuEgg"

VK_GROUP_ID = 212808533
VK_API_VERSION = "5.199"

print("="*70)
print("ПРОВЕРКА НОВОГО ТОКЕНА ПОЛЬЗОВАТЕЛЯ (через OAuth)")
print("="*70)
print(f"Группа: tennisprimesport (ID: {VK_GROUP_ID})")
print(f"Токен: {NEW_TOKEN[:30]}...{NEW_TOKEN[-20:]}")
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
            print("   Возможные причины:")
            print("   - Группа все еще закрыта")
            print("   - Вы не являетесь участником группы")
            print("   - Токен не имеет нужных прав")
        elif error_code == 5:
            print("\n⚠️  Ошибка 5: Токен недействителен")
    else:
        items = data.get("response", {}).get("items", [])
        print(f"✅ ТОКЕН РАБОТАЕТ! Получено {len(items)} пост(ов)")
        if items:
            post = items[0]
            print(f"   Последний пост ID: {post.get('id')}")
            print(f"   Дата: {post.get('date')}")
        print("\n✅ Этот токен можно использовать на сервере!")
        print("\n📋 Команды для обновления:")
        print(f"   nano /root/s360-streams/.env")
        print(f"   # Замените VK_TOKEN= на:")
        print(f"   VK_TOKEN={NEW_TOKEN}")
        print(f"   systemctl restart vk-to-telegram.service")
        
except Exception as e:
    print(f"❌ Ошибка при запросе: {e}")
