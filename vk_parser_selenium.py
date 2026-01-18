#!/usr/bin/env python3
"""
Парсер VK группы через Selenium (автоматизация браузера)
Работает надежнее, чем простой парсинг HTML, так как выполняет JavaScript
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Настройки
VK_GROUP_ID = 212808533
VK_GROUP_URL = "https://vk.com/tennisprimesport"
POSTS_LIMIT = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def get_vk_posts_selenium() -> List[Dict[str, Any]]:
    """
    Получить посты через Selenium (автоматизация браузера).
    Требует установки selenium и драйвера браузера.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
    except ImportError:
        logging.error(
            "Selenium не установлен! Установите:\n"
            "  pip3 install selenium\n"
            "  apt-get install chromium-chromedriver  # или скачайте ChromeDriver"
        )
        return []
    
    # Настройка Chrome для обхода защиты VK
    chrome_options = Options()
    # НЕ используем headless - VK может блокировать headless браузеры
    # chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    # Убираем признаки автоматизации
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Загружаем cookies если есть
    cookies_file = Path("vk_cookies.txt")
    cookies = {}
    if cookies_file.exists():
        try:
            with open(cookies_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        key, value = line.split("=", 1)
                        cookies[key.strip()] = value.strip()
        except Exception as e:
            logging.warning("Не удалось загрузить cookies: %s", e)
    
    driver = None
    try:
        # Запускаем браузер
        logging.info("Запускаю Chrome...")
        driver = webdriver.Chrome(options=chrome_options)
        
        # Убираем признаки автоматизации через JavaScript
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            '''
        })
        
        # Увеличиваем таймауты
        driver.implicitly_wait(15)
        driver.set_page_load_timeout(60)  # 60 секунд на загрузку страницы
        
        # Если есть cookies, добавляем их
        if cookies:
            logging.info("Добавляю cookies...")
            driver.get("https://vk.com/")
            time.sleep(2)  # Ждем загрузки страницы
            for name, value in cookies.items():
                try:
                    driver.add_cookie({
                        "name": name, 
                        "value": value, 
                        "domain": ".vk.com",
                        "path": "/"
                    })
                except Exception as e:
                    logging.debug(f"Не удалось добавить cookie {name}: {e}")
            logging.info("Cookies добавлены")
        
        # Переходим на страницу группы
        logging.info("Загружаю страницу группы...")
        driver.get(VK_GROUP_URL)
        
        # Ждем загрузки постов (VK может загружать их через AJAX)
        logging.info("Жду загрузки постов...")
        time.sleep(10)  # Увеличил время ожидания
        
        # Пробуем найти посты в DOM
        posts = []
        
        # Прокручиваем страницу вниз, чтобы загрузить больше постов
        logging.info("Прокручиваю страницу для загрузки постов...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, 0);")  # Возвращаемся наверх
        time.sleep(2)
        
        # Ищем посты по разным селекторам (VK использует разные классы)
        post_selectors = [
            "div[data-post-id]",  # Основной селектор
            "div.wall_item",
            "div.post",
            "div[id*='post']",
            "div[class*='wall_item']",
            "div[class*='post']",
            "a[href*='wall-']"  # Ссылки на посты
        ]
        
        post_elements = []
        for selector in post_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    post_elements = elements
                    logging.info(f"✅ Найдено {len(elements)} элементов через селектор: {selector}")
                    break
            except Exception as e:
                logging.debug(f"Селектор {selector} не сработал: {e}")
                continue
        
        if not post_elements:
            # Пробуем найти любые ссылки на посты
            logging.info("Пробую найти посты через ссылки...")
            all_links = driver.find_elements(By.TAG_NAME, "a")
            post_links = [link for link in all_links if "wall-" in link.get_attribute("href") or ""]
            if post_links:
                post_elements = post_links[:POSTS_LIMIT]
                logging.info(f"✅ Найдено {len(post_elements)} постов через ссылки")
        
        # Извлекаем данные из постов
        for elem in post_elements[:POSTS_LIMIT]:
            try:
                # Получаем post_id
                post_id_attr = elem.get_attribute("data-post-id")
                if not post_id_attr:
                    # Пробуем найти в ссылке
                    link = elem.find_element(By.CSS_SELECTOR, "a[href*='wall']")
                    if link:
                        href = link.get_attribute("href")
                        match = re.search(r'wall-?\d+_(\d+)', href)
                        if match:
                            post_id_attr = match.group(1)
                
                if not post_id_attr:
                    continue
                
                post_id = int(post_id_attr) if post_id_attr.isdigit() else 0
                if not post_id:
                    continue
                
                # Получаем текст
                try:
                    text_elem = elem.find_element(By.CSS_SELECTOR, ".wall_post_text, .post_text")
                    text = text_elem.text.strip()
                except:
                    text = ""
                
                # Ищем видео
                attachments = []
                try:
                    video_elem = elem.find_element(By.CSS_SELECTOR, "a[href*='video']")
                    if video_elem:
                        attachments.append({"type": "video"})
                except:
                    pass
                
                posts.append({
                    "id": post_id,
                    "text": text,
                    "attachments": attachments
                })
            except Exception as e:
                logging.debug("Ошибка при извлечении поста: %s", e)
                continue
        
        logging.info(f"Получено {len(posts)} постов через Selenium")
        return posts
        
    except Exception as e:
        logging.error("Ошибка при работе с Selenium: %s", e, exc_info=True)
        return []
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    print("Тестирование парсера VK через Selenium...")
    posts = get_vk_posts_selenium()
    print(f"Найдено постов: {len(posts)}")
    for post in posts[:3]:
        print(f"  Пост ID: {post.get('id')}, Текст: {post.get('text', '')[:50]}...")
