#!/usr/bin/env python3
"""
Проверка текущего токена из CONFIG.txt
"""

import requests

# Токен из CONFIG.txt
CURRENT_TOKEN = "d165ed0dd165ed0dd165ed0dddd25853dbdd165d165ed0db84a1c02d67d4a7083b2f985"
VK_GROUP_ID = 212808533
VK_API_VERSION = "5.199"

print("Проверка текущего токена из CONFIG.txt...")
print(f"Группа: tennisprimesport (ID: {VK_GROUP_ID})\n")

url = "https://api.vk.com/method/wall.get"
params = {
    "access_token": CURRENT_TOKEN,
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
            print("\n⚠️  Ошибка 15 означает:")
            print("   - Группа стала приватной/закрытой, ИЛИ")
            print("   - Токен не имеет доступа к стене группы")
            print("\nПроверьте, не стала ли группа приватной:")
            print("   Откройте https://vk.com/tennisprimesport в браузере")
        elif error_code == 5:
            print("\n⚠️  Ошибка 5 означает, что токен истек или недействителен")
            print("   Нужно получить новый токен")
    else:
        items = data.get("response", {}).get("items", [])
        print(f"✅ Токен РАБОТАЕТ! Получено {len(items)} пост(ов)")
        if items:
            post = items[0]
            print(f"   Последний пост ID: {post.get('id')}")
            print(f"   Дата: {post.get('date')}")
        print("\n✅ Токен рабочий! Проблема может быть в другом месте.")
        
except Exception as e:
    print(f"❌ Ошибка при запросе: {e}")
