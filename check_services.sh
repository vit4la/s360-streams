#!/bin/bash
# Скрипт для проверки статуса сервисов

echo "=========================================="
echo "Проверка статуса сервисов"
echo "=========================================="
echo ""

echo "1. Модерационный бот (moderation-bot.service):"
systemctl is-active moderation-bot.service > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Сервис активен"
    systemctl status moderation-bot.service --no-pager -l | head -n 5
else
    echo "   ❌ Сервис не активен"
    systemctl status moderation-bot.service --no-pager -l | head -n 5
fi
echo ""

echo "2. VK to Telegram (vk-to-telegram.service):"
systemctl is-active vk-to-telegram.service > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Сервис активен"
    systemctl status vk-to-telegram.service --no-pager -l | head -n 5
else
    echo "   ❌ Сервис не активен"
    systemctl status vk-to-telegram.service --no-pager -l | head -n 5
fi
echo ""

echo "3. Последние логи модерационного бота:"
journalctl -u moderation-bot.service -n 10 --no-pager | tail -n 5
echo ""

echo "4. Последние логи VK to Telegram:"
journalctl -u vk-to-telegram.service -n 10 --no-pager | tail -n 5
echo ""

echo "5. Проверка файлов логов:"
if [ -f "/root/s360-streams/logs/moderation_bot.log" ]; then
    echo "   ✅ Лог модерационного бота существует"
    echo "   Последние строки:"
    tail -n 3 /root/s360-streams/logs/moderation_bot.log
else
    echo "   ❌ Лог модерационного бота не найден"
fi
echo ""

if [ -f "/root/s360-streams/vk_to_telegram.log" ]; then
    echo "   ✅ Лог VK to Telegram существует"
    echo "   Последние строки:"
    tail -n 3 /root/s360-streams/vk_to_telegram.log
else
    echo "   ❌ Лог VK to Telegram не найден"
fi
echo ""

echo "=========================================="

