#!/bin/bash
# Установка Selenium и ChromeDriver для парсинга VK

echo "Установка Selenium и ChromeDriver..."

# Установка Python пакетов
pip3 install selenium

# Установка Chrome и ChromeDriver
apt-get update
apt-get install -y chromium-browser chromium-chromedriver

# Альтернатива: если не работает, можно скачать ChromeDriver вручную
# wget https://chromedriver.storage.googleapis.com/LATEST_RELEASE
# wget https://chromedriver.storage.googleapis.com/$(cat LATEST_RELEASE)/chromedriver_linux64.zip
# unzip chromedriver_linux64.zip
# chmod +x chromedriver
# mv chromedriver /usr/local/bin/

echo "✅ Установка завершена!"
echo "Теперь можно использовать vk_parser_selenium.py"
