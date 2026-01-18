#!/usr/bin/env python3
"""
Альтернативный парсер VK группы через веб-скрапинг (без API)
Используется когда API недоступен (закрытая группа, проблемы с токеном)
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

# Настройки
VK_GROUP_ID = 212808533
VK_GROUP_URL = "https://vk.com/tennisprimesport"
STATE_FILE = Path("vk_last_post_state.json")
POSTS_LIMIT = 20

# Логгирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def load_state() -> Dict[str, Any]:
    """Загрузить состояние из файла."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logging.exception("Не удалось загрузить файл состояния.")
    return {"last_post_id": 0, "initialized": False}


def save_state(state: Dict[str, Any]) -> None:
    """Сохранить состояние в файл."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Не удалось сохранить файл состояния.")


def get_vk_posts_scraping() -> List[Dict[str, Any]]:
    """
    Получить посты со стены группы VK через веб-скрапинг (без API).
    Парсит публичную страницу группы.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    try:
        # Загружаем страницу группы
        resp = requests.get(VK_GROUP_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        
        # Парсим HTML
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # VK использует JavaScript для загрузки постов, поэтому нужно искать JSON данные в скриптах
        posts = []
        
        # Ищем скрипты с данными постов
        scripts = soup.find_all("script")
        for script in scripts:
            if script.string:
                # Ищем JSON с постами (VK хранит данные в window.__initialData__ или подобных структурах)
                # Это упрощенный вариант - в реальности VK может использовать другие форматы
                text = script.string
                
                # Пытаемся найти данные постов в различных форматах
                # VK может использовать разные способы хранения данных
                if "wall" in text.lower() or "post" in text.lower():
                    # Пытаемся извлечь JSON данные
                    json_match = re.search(r'\{.*"items".*\}', text, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group())
                            if "response" in data and "items" in data["response"]:
                                posts = data["response"]["items"]
                                break
                        except:
                            pass
        
        # Если не нашли через скрипты, пытаемся парсить HTML напрямую
        if not posts:
            # Ищем посты в HTML (классы могут меняться)
            post_elements = soup.find_all("div", class_=re.compile(r".*post.*", re.I))
            for element in post_elements[:POSTS_LIMIT]:
                # Извлекаем данные поста из HTML
                post_id = element.get("data-post-id") or element.get("id", "")
                if post_id:
                    # Пытаемся извлечь текст поста
                    text_elem = element.find("div", class_=re.compile(r".*text.*", re.I))
                    text = text_elem.get_text(strip=True) if text_elem else ""
                    
                    # Пытаемся найти видео
                    video_elem = element.find("div", class_=re.compile(r".*video.*", re.I))
                    
                    posts.append({
                        "id": int(post_id.split("_")[-1]) if "_" in post_id else int(post_id) if post_id.isdigit() else 0,
                        "text": text,
                        "attachments": []  # Упрощенно, можно доработать
                    })
        
        logging.info("Получено %s пост(ов) через веб-скрапинг.", len(posts))
        return posts
        
    except Exception as e:
        logging.error("Ошибка при парсинге страницы VK: %s", e, exc_info=True)
        return []


def get_vk_posts_via_mobile_api() -> List[Dict[str, Any]]:
    """
    Альтернативный способ: использовать мобильную версию VK (m.vk.com).
    Мобильная версия часто проще парсить и менее защищена.
    """
    mobile_url = f"https://m.vk.com/tennisprimesport"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    try:
        resp = requests.get(mobile_url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        posts = []
        
        # Парсим мобильную версию (структура проще)
        # Нужно адаптировать под текущую структуру m.vk.com
        post_elements = soup.find_all("div", class_=re.compile(r".*post.*", re.I))
        
        for element in post_elements[:POSTS_LIMIT]:
            post_id = element.get("data-post-id") or ""
            if post_id:
                text_elem = element.find("div", class_=re.compile(r".*text.*", re.I))
                text = text_elem.get_text(strip=True) if text_elem else ""
                
                posts.append({
                    "id": int(post_id.split("_")[-1]) if "_" in post_id else 0,
                    "text": text,
                    "attachments": []
                })
        
        logging.info("Получено %s пост(ов) через мобильную версию.", len(posts))
        return posts
        
    except Exception as e:
        logging.error("Ошибка при парсинге мобильной версии VK: %s", e, exc_info=True)
        return []


if __name__ == "__main__":
    # Тест парсинга
    print("Тестирование парсинга VK без API...")
    posts = get_vk_posts_scraping()
    if not posts:
        print("Пробуем мобильную версию...")
        posts = get_vk_posts_via_mobile_api()
    
    print(f"Найдено постов: {len(posts)}")
    for post in posts[:3]:
        print(f"  Пост ID: {post.get('id')}, Текст: {post.get('text', '')[:50]}...")
