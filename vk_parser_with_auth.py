#!/usr/bin/env python3
"""
Парсер VK группы с авторизацией (для закрытых групп)
Использует cookies для авторизации и парсит страницу как авторизованный пользователь
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Настройки
VK_GROUP_ID = 212808533
VK_GROUP_URL = "https://vk.com/tennisprimesport"
STATE_FILE = Path("vk_last_post_state.json")
POSTS_LIMIT = 20

# Файл для хранения cookies
COOKIES_FILE = Path("vk_cookies.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def load_cookies() -> Optional[Dict[str, str]]:
    """Загрузить cookies из файла."""
    if COOKIES_FILE.exists():
        try:
            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                cookies = {}
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        key, value = line.split("=", 1)
                        cookies[key.strip()] = value.strip()
                return cookies if cookies else None
        except Exception as e:
            logging.error("Ошибка при загрузке cookies: %s", e)
    return None


def get_vk_posts_with_auth() -> List[Dict[str, Any]]:
    """
    Получить посты через парсинг страницы с авторизацией.
    Требует cookies от авторизованной сессии VK.
    """
    cookies = load_cookies()
    
    if not cookies:
        logging.error(
            "Cookies не найдены! Создайте файл vk_cookies.txt с cookies от авторизованной сессии VK.\n"
            "Инструкция:\n"
            "1. Войдите в VK в браузере (как участник группы)\n"
            "2. Откройте DevTools (F12) -> Application/Storage -> Cookies\n"
            "3. Скопируйте cookies (особенно remixsid, remixstid, remixlang)\n"
            "4. Сохраните в формате: remixsid=значение в файл vk_cookies.txt"
        )
        return []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://vk.com/",
    }
    
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update(headers)
    
    try:
        # Сначала проверяем авторизацию на главной странице
        main_resp = session.get("https://vk.com/feed", timeout=15)
        if "login" in main_resp.url.lower() or "Вход" in main_resp.text or "id=" not in main_resp.text:
            logging.error("Не удалось авторизоваться. Проверьте cookies в vk_cookies.txt")
            logging.error("Cookies должны быть от аккаунта, который является участником группы tennisprimesport")
            return []
        
        logging.info("Авторизация успешна, загружаю страницу группы...")
        
        # Загружаем страницу группы
        resp = session.get(VK_GROUP_URL, timeout=15)
        resp.raise_for_status()
        
        # Проверяем, что мы на странице группы (не редирект на логин)
        if "login" in resp.url.lower() or "Вход" in resp.text:
            logging.error("Не удалось получить доступ к группе. Возможно, вы не участник группы.")
            return []
        
        # Используем мобильную версию VK - она проще для парсинга
        logging.info("Пробую мобильную версию VK...")
        mobile_url = f"https://m.vk.com/tennisprimesport"
        mobile_resp = session.get(mobile_url, timeout=20)
        
        posts = []
        
        # Пробуем найти данные в мобильной версии через HTML парсинг
        if mobile_resp.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(mobile_resp.text, "html.parser")
            
            # В мобильной версии посты обычно в div с классом wall_item или в ссылках
            # Ищем все ссылки на посты
            post_links = soup.find_all("a", href=re.compile(r'wall-?\d+_\d+'))
            
            seen_ids = set()
            for link in post_links[:POSTS_LIMIT * 2]:  # Берем больше, так как могут быть дубли
                try:
                    href = link.get("href", "")
                    # Извлекаем post_id из ссылки вида wall-212808533_12345 или /wall-212808533_12345
                    post_id_match = re.search(r'wall-?\d+_(\d+)', href)
                    if post_id_match:
                        post_id = int(post_id_match.group(1))
                        if post_id in seen_ids:
                            continue
                        seen_ids.add(post_id)
                        
                        # Ищем родительский элемент поста
                        post_elem = link
                        for _ in range(5):  # Поднимаемся на 5 уровней вверх
                            post_elem = post_elem.parent
                            if post_elem and post_elem.name == "div":
                                break
                        
                        # Извлекаем текст поста
                        text = ""
                        if post_elem:
                            # Ищем текст в разных местах
                            text_elem = post_elem.find("div", class_=re.compile(r"text|content", re.I))
                            if not text_elem:
                                # Пробуем найти все текстовые элементы
                                text_parts = []
                                for p in post_elem.find_all(["div", "p", "span"]):
                                    txt = p.get_text(strip=True)
                                    if txt and len(txt) > 10:  # Игнорируем короткие тексты
                                        text_parts.append(txt)
                                text = " ".join(text_parts[:3])  # Берем первые 3 части
                            else:
                                text = text_elem.get_text(strip=True)
                        
                        # Ищем видео
                        attachments = []
                        video_link = post_elem.find("a", href=re.compile(r"video")) if post_elem else None
                        if video_link:
                            attachments.append({"type": "video"})
                        
                        posts.append({
                            "id": post_id,
                            "text": text,
                            "attachments": attachments
                        })
                        
                        if len(posts) >= POSTS_LIMIT:
                            break
                except Exception as e:
                    logging.debug("Ошибка при парсинге поста: %s", e)
                    continue
            
            if posts:
                logging.info(f"✅ Найдено {len(posts)} постов в мобильной версии через HTML парсинг")
        
        # Если не нашли через HTML, пробуем найти JSON в скриптах
        if not posts and mobile_resp.status_code == 200:
            script_patterns = [
                re.compile(r'var\s+wall\s*=\s*(\{.*?\});', re.DOTALL),
                re.compile(r'window\.wall\s*=\s*(\{.*?\});', re.DOTALL),
                re.compile(r'"wall":\s*(\{.*?"items":\s*\[.*?\]\})', re.DOTALL),
            ]
            
            for pattern in script_patterns:
                match = pattern.search(mobile_resp.text)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        if "items" in data:
                            posts = data["items"][:POSTS_LIMIT]
                            logging.info("✅ Найдены посты в JSON данных мобильной версии")
                            break
                    except (json.JSONDecodeError, KeyError, TypeError) as e:
                        logging.debug("Ошибка при парсинге JSON: %s", e)
                        continue
        
        # Если все еще не нашли, пробуем парсить HTML напрямую
        if not posts:
            # Ищем посты по классам (структура может меняться)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Ищем элементы постов
            post_elements = soup.find_all("div", {"class": re.compile(r".*post.*", re.I)})
            
            for elem in post_elements[:POSTS_LIMIT]:
                try:
                    # Извлекаем post_id из data-атрибутов или ID
                    post_id_attr = elem.get("data-post-id") or elem.get("id", "")
                    if not post_id_attr:
                        # Пытаемся найти в ссылках
                        link = elem.find("a", href=re.compile(r"wall"))
                        if link:
                            href = link.get("href", "")
                            post_id_match = re.search(r'wall-?\d+_(\d+)', href)
                            if post_id_match:
                                post_id_attr = post_id_match.group(1)
                    
                    if post_id_attr:
                        # Извлекаем текст
                        text_elem = elem.find("div", class_=re.compile(r".*text.*", re.I))
                        text = text_elem.get_text(strip=True) if text_elem else ""
                        
                        # Ищем видео
                        video_elem = elem.find("div", class_=re.compile(r".*video.*", re.I))
                        attachments = []
                        if video_elem:
                            attachments.append({"type": "video"})
                        
                        post_id = int(post_id_attr) if post_id_attr.isdigit() else 0
                        if post_id:
                            posts.append({
                                "id": post_id,
                                "text": text,
                                "attachments": attachments
                            })
                except Exception as e:
                    logging.debug("Ошибка при парсинге HTML поста: %s", e)
                    continue
        
        logging.info("Получено %s пост(ов) через парсинг с авторизацией.", len(posts))
        return posts
        
    except Exception as e:
        logging.error("Ошибка при парсинге страницы VK: %s", e, exc_info=True)
        return []


if __name__ == "__main__":
    print("Тестирование парсинга VK с авторизацией...")
    posts = get_vk_posts_with_auth()
    print(f"Найдено постов: {len(posts)}")
    for post in posts[:3]:
        print(f"  Пост ID: {post.get('id')}, Текст: {post.get('text', '')[:50]}...")
