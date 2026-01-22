#!/usr/bin/env python3
"""
Проверка RSS фида для группы VK
"""

import requests
import xml.etree.ElementTree as ET
import re

VK_GROUP_DOMAIN = "tennisprimesport"
VK_GROUP_ID = 212808533

print("="*70)
print("ПРОВЕРКА RSS ФИДА VK")
print("="*70)
print(f"Группа: {VK_GROUP_DOMAIN} (ID: {VK_GROUP_ID})")
print()

# Пробуем разные варианты RSS URL
rss_urls = [
    f"https://vk.com/rss.php?domain={VK_GROUP_DOMAIN}",
    f"https://vk.com/rss.php?owner_id=-{VK_GROUP_ID}",
    f"https://vk.com/feeds/{VK_GROUP_DOMAIN}.xml",
]

for rss_url in rss_urls:
    print(f"Пробую: {rss_url}")
    print("-" * 70)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        resp = requests.get(rss_url, headers=headers, timeout=15)
        print(f"Статус: {resp.status_code}")
        
        if resp.status_code == 200:
            try:
                root = ET.fromstring(resp.text)
                items = root.findall(".//item")
                print(f"✅ RSS работает! Найдено {len(items)} постов")
                
                if items:
                    print("\nПервые 3 поста:")
                    for i, item in enumerate(items[:3], 1):
                        title = item.find("title")
                        link = item.find("link")
                        title_text = title.text if title is not None else "Нет заголовка"
                        link_text = link.text if link is not None else "Нет ссылки"
                        print(f"  {i}. {title_text[:50]}...")
                        print(f"     {link_text}")
                break
            except ET.ParseError as e:
                print(f"❌ Ошибка парсинга XML: {e}")
        elif resp.status_code == 404:
            print("❌ RSS недоступен (404) - группа может быть закрытой")
        else:
            print(f"❌ Ошибка: {resp.status_code}")
            print(f"   Ответ: {resp.text[:200]}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    print()

print()
print("="*70)
print("ПРОВЕРКА ЗАВЕРШЕНА")
print("="*70)
