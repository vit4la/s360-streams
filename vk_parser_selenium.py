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

# Файл с учетными данными (логин и пароль)
CREDENTIALS_FILE = Path("vk_credentials.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def load_credentials() -> Optional[Dict[str, str]]:
    """Загрузить логин и пароль из файла."""
    if CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                credentials = {}
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        credentials[key.strip()] = value.strip()
                return credentials if "login" in credentials and "password" in credentials else None
        except Exception as e:
            logging.error("Ошибка при загрузке учетных данных: %s", e)
    return None


def get_vk_posts_selenium() -> List[Dict[str, Any]]:
    """
    Получить посты через Selenium (автоматизация браузера).
    Требует установки selenium и драйвера браузера.
    Поддерживает авторизацию через логин/пароль или cookies.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.keys import Keys
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
    
    # Загружаем учетные данные (логин/пароль)
    credentials = load_credentials()
    
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
        driver.set_page_load_timeout(90)  # 90 секунд на загрузку страницы
        
        # Авторизация: сначала пробуем через логин/пароль, потом через cookies
        if credentials:
            logging.info("Авторизуюсь через логин/пароль...")
            try:
                driver.get("https://vk.com/")
                time.sleep(3)
                
                # Ищем поле ввода телефона/email
                try:
                    phone_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='login'], input[type='text'], input[placeholder*='телефон'], input[placeholder*='email']"))
                    )
                    phone_input.clear()
                    phone_input.send_keys(credentials["login"])
                    logging.info("Логин введен")
                except Exception as e:
                    logging.warning(f"Не удалось найти поле логина: {e}")
                
                # Ищем поле ввода пароля
                try:
                    password_input = driver.find_element(By.CSS_SELECTOR, "input[name='password'], input[type='password']")
                    password_input.clear()
                    password_input.send_keys(credentials["password"])
                    logging.info("Пароль введен")
                except Exception as e:
                    logging.warning(f"Не удалось найти поле пароля: {e}")
                
                # Ищем кнопку входа
                try:
                    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], .login_button, button:contains('Войти')")
                    login_button.click()
                    logging.info("Кнопка входа нажата")
                except Exception as e:
                    # Пробуем нажать Enter
                    try:
                        password_input.send_keys(Keys.RETURN)
                        logging.info("Нажата клавиша Enter")
                    except:
                        logging.warning(f"Не удалось нажать кнопку входа: {e}")
                
                # Ждем авторизации (проверяем, что мы не на странице входа)
                time.sleep(5)
                if "login" not in driver.current_url.lower() and "oauth" not in driver.current_url.lower():
                    logging.info("✅ Авторизация через логин/пароль успешна")
                else:
                    logging.warning("Возможно, требуется двухфакторная аутентификация или капча")
                    # Продолжаем - может быть, авторизация прошла, но есть редирект
            except Exception as e:
                logging.error(f"Ошибка при авторизации через логин/пароль: {e}")
                # Пробуем через cookies
                if cookies:
                    logging.info("Пробую авторизацию через cookies...")
                    driver.get("https://vk.com/")
                    time.sleep(2)
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
        elif cookies:
            # Если нет логина/пароля, используем cookies
            logging.info("Добавляю cookies...")
            driver.get("https://vk.com/")
            time.sleep(2)
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
        else:
            logging.warning("Нет ни логина/пароля, ни cookies. Пробую без авторизации...")
        
        # Переходим на страницу группы
        logging.info("Загружаю страницу группы...")
        try:
            driver.get(VK_GROUP_URL)
        except Exception as e:
            logging.warning(f"Таймаут при загрузке страницы, но продолжаю: {e}")
        
        # Ждем загрузки постов (VK может загружать их через AJAX)
        logging.info("Жду загрузки постов...")
        time.sleep(8)  # Уменьшил время ожидания
        
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
