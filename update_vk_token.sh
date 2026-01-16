#!/bin/bash
# Скрипт для обновления VK токена на сервере

NEW_TOKEN="vk1.a.LSaMaMv9ZuMr9a1VNgV8nbnxcbJ2sTsak-9r-NEzNxvQRH2S37JX3ctrsB1vAnmAAmJRBatzNMHkPnhHXzY-V-MNPiH96istX1cOzcTk3AKr-aWQwymLRILWp0YiZSsWgwolbz2yAFxXygOlvpdV1KjKcWVxzbqHSp-nZ3cL8_x1ceaa51bQPq4h9bRoTW0IUlJKtEpZoZGwMWZCmhuEgg"

ENV_FILE="/root/s360-streams/.env"

echo "Обновление VK токена..."

# Проверяем, существует ли .env файл
if [ ! -f "$ENV_FILE" ]; then
    echo "Создаю .env файл..."
    touch "$ENV_FILE"
fi

# Обновляем или добавляем VK_TOKEN
if grep -q "^VK_TOKEN=" "$ENV_FILE"; then
    # Заменяем существующий токен
    sed -i "s|^VK_TOKEN=.*|VK_TOKEN=$NEW_TOKEN|" "$ENV_FILE"
    echo "✅ Токен обновлен в .env файле"
else
    # Добавляем новый токен
    echo "VK_TOKEN=$NEW_TOKEN" >> "$ENV_FILE"
    echo "✅ Токен добавлен в .env файл"
fi

echo ""
echo "Токен обновлен. Перезапускаю сервис..."
systemctl restart vk-to-telegram.service

echo ""
echo "Проверяю статус сервиса..."
systemctl status vk-to-telegram.service --no-pager -l | head -n 10

echo ""
echo "Последние логи:"
tail -n 20 /root/s360-streams/vk_to_telegram.log
