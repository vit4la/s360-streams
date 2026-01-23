#!/usr/bin/env python3
"""
Тест Community Token для группы club235512260
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

VK_GROUP_ID = 235512260
VK_API_VERSION = "5.199"

# Новый Community Token
COMMUNITY_TOKEN = "vk1.a.FPDg_piW9vaMtIrZaYdu4RLwn8MafVdULEVrqjUNUOcFG6QuW696NRH6hMi4AQ1uSC5J7_Pu_bfuuLiY3zXaB9WhJ79YLunyXZb65p6HaUU45xnHOyqJzLtj6l88QOMYcNtuKY5_tOE40NuHXM_iikja-6GeJoPotE2nBpaEsbNhBKOmbb7hotN3btfEZoVXo0cKeZ1Bej6ALG7EVmPtcg"

print("="*70)
print("ТЕСТ COMMUNITY TOKEN ДЛЯ ГРУППЫ club235512260")
print("="*70)
print(f"Группа ID: {VK_GROUP_ID}")
print(f"Токен: {COMMUNITY_TOKEN[:50]}...")
print()

import requests

# Тест 1: Проверка токена через users.get
print("1. Проверка токена (users.get)...")
print("-" * 70)
try:
    url = "https://api.vk.com/method/users.get"
    params = {
        "access_token": COMMUNITY_TOKEN,
        "v": VK_API_VERSION,
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()
    
    if "error" in data:
        print(f"   ❌ Ошибка: {data['error']}")
    else:
        print(f"   ✅ Токен валиден")
        if "response" in data and data["response"]:
            user = data["response"][0]
            print(f"   Пользователь: {user.get('first_name')} {user.get('last_name')} (ID: {user.get('id')})")
except Exception as e:
    print(f"   ❌ Ошибка запроса: {e}")

print()

# Тест 2: Получение постов через wall.get
print("2. Получение постов через wall.get...")
print("-" * 70)
try:
    url = "https://api.vk.com/method/wall.get"
    params = {
        "access_token": COMMUNITY_TOKEN,
        "v": VK_API_VERSION,
        "owner_id": -VK_GROUP_ID,
        "count": 10,
        "extended": 1,
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()
    
    if "error" in data:
        error = data["error"]
        print(f"   ❌ Ошибка VK API: {error.get('error_code')} - {error.get('error_msg')}")
        if "request_params" in error:
            print(f"   Параметры запроса: {error.get('request_params')}")
    else:
        items = data.get("response", {}).get("items", [])
        if items:
            print(f"   ✅ Успешно получено {len(items)} пост(ов)")
            print()
            print("   Последние посты:")
            for i, post in enumerate(items[:5], 1):
                post_id = post.get("id")
                text = post.get("text", "")[:80]
                attachments = post.get("attachments", [])
                has_video = any(att.get("type") == "video" for att in attachments)
                print(f"   {i}. Пост {post_id}: {text}... [видео: {'да' if has_video else 'нет'}]")
        else:
            print("   ⚠️  Посты не найдены (группа может быть пустой)")
except Exception as e:
    print(f"   ❌ Ошибка запроса: {e}")
    import traceback
    traceback.print_exc()

print()

# Тест 3: Проверка прав доступа
print("3. Проверка прав доступа...")
print("-" * 70)
try:
    url = "https://api.vk.com/method/groups.getById"
    params = {
        "access_token": COMMUNITY_TOKEN,
        "v": VK_API_VERSION,
        "group_id": VK_GROUP_ID,
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()
    
    if "error" in data:
        print(f"   ❌ Ошибка: {data['error']}")
    else:
        groups = data.get("response", [])
        if groups:
            group = groups[0]
            print(f"   ✅ Группа найдена: {group.get('name')}")
            print(f"   Описание: {group.get('description', 'нет')[:100]}...")
            print(f"   Участников: {group.get('members_count', 'неизвестно')}")
except Exception as e:
    print(f"   ❌ Ошибка запроса: {e}")

print()
print("="*70)
print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print("="*70)
