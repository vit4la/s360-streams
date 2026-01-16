#!/usr/bin/env python3
"""
Проверка всех ключей VK, которые были предоставлены
"""

import requests

VK_GROUP_ID = 212808533
VK_API_VERSION = "5.199"

# Все ключи, которые были предоставлены
KEYS = [
    {
        "name": "Сервисный ключ (первый из VK ID)",
        "key": "3621a11a3621a11a3621a11a8a351c1fa9336213621a11a5f0e4d10720acc3bddc32da5"
    },
    {
        "name": "Защищенный ключ (первый из VK ID)",
        "key": "oprOGUVvCwDnFKsvAZIr"
    },
    {
        "name": "Сервисный ключ (новый из VK ID) / Токен из CONFIG.txt",
        "key": "d165ed0dd165ed0dd165ed0dddd25853dbdd165d165ed0db84a1c02d67d4a7083b2f985"
    },
    {
        "name": "Защищенный ключ (новый из VK ID)",
        "key": "hDMS4IS0pJSfhcP5qP86"
    }
]

def test_token(token_name, token):
    """Проверить, работает ли токен для wall.get"""
    print(f"\n{'='*70}")
    print(f"Проверка: {token_name}")
    print(f"Ключ: {token[:20]}...{token[-10:] if len(token) > 30 else token}")
    print(f"{'='*70}")
    
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
            
            if error_code == 15:
                print("   ⚠️  Ошибка 15: Access denied")
                print("   Это может означать, что группа закрыта или токен не имеет доступа")
            elif error_code == 5:
                print("   ⚠️  Ошибка 5: Токен недействителен или истек")
            
            return False, error_code, error_msg
        else:
            items = data.get("response", {}).get("items", [])
            print(f"✅ ТОКЕН РАБОТАЕТ! Получено {len(items)} пост(ов)")
            if items:
                post = items[0]
                print(f"   Последний пост ID: {post.get('id')}")
                print(f"   Дата: {post.get('date')}")
            return True, None, None
    except Exception as e:
        print(f"❌ Ошибка при запросе: {e}")
        return False, None, str(e)

if __name__ == "__main__":
    print("="*70)
    print("ПРОВЕРКА ВСЕХ КЛЮЧЕЙ VK ДЛЯ wall.get")
    print("="*70)
    print(f"Группа: tennisprimesport (ID: {VK_GROUP_ID})")
    print(f"Версия API: {VK_API_VERSION}")
    print("\nПроверяю все ключи, которые были предоставлены...")
    
    working_keys = []
    failed_keys = []
    
    for key_info in KEYS:
        name = key_info["name"]
        key = key_info["key"]
        
        works, error_code, error_msg = test_token(name, key)
        
        if works:
            working_keys.append({"name": name, "key": key})
        else:
            failed_keys.append({"name": name, "key": key, "error_code": error_code, "error_msg": error_msg})
    
    # Итоговый отчет
    print(f"\n\n{'='*70}")
    print("ИТОГОВЫЙ ОТЧЕТ")
    print(f"{'='*70}")
    
    if working_keys:
        print(f"\n✅ РАБОТАЮЩИХ КЛЮЧЕЙ: {len(working_keys)}")
        for i, key_info in enumerate(working_keys, 1):
            print(f"\n{i}. {key_info['name']}")
            print(f"   Токен: {key_info['key']}")
            print(f"   ✅ Используйте этот токен на сервере!")
    else:
        print("\n❌ НИ ОДИН КЛЮЧ НЕ РАБОТАЕТ")
        print("   Возможные причины:")
        print("   - Группа все еще закрыта")
        print("   - Токены не имеют нужных прав")
        print("   - Нужен токен пользователя через OAuth")
    
    if failed_keys:
        print(f"\n❌ НЕ РАБОТАЮЩИХ КЛЮЧЕЙ: {len(failed_keys)}")
        for i, key_info in enumerate(failed_keys, 1):
            print(f"\n{i}. {key_info['name']}")
            print(f"   Ошибка: {key_info.get('error_code', '?')} - {key_info.get('error_msg', 'Unknown')}")
    
    print(f"\n{'='*70}")
    
    # Если есть рабочий ключ, показать команду для обновления
    if working_keys:
        best_key = working_keys[0]
        print("\n📋 КОМАНДЫ ДЛЯ ОБНОВЛЕНИЯ ТОКЕНА НА СЕРВЕРЕ:")
        print(f"\nnano /root/s360-streams/.env")
        print(f"# Замените VK_TOKEN= на:")
        print(f"VK_TOKEN={best_key['key']}")
        print(f"\nsystemctl restart vk-to-telegram.service")
        print(f"tail -n 20 /root/s360-streams/vk_to_telegram.log")
