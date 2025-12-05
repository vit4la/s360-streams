# Восстановление VK_TOKEN

Если сервис vk-to-telegram не работает из-за отсутствия VK_TOKEN, выполните на сервере:

## Вариант 1: Добавить токен в .env файл (рекомендуется)

```bash
# Откройте .env файл
nano /root/s360-streams/.env

# Добавьте строку:
VK_TOKEN=ваш_vk_токен_здесь
```

## Вариант 2: Добавить токен прямо в vk_to_telegram.py

```bash
# Откройте файл
nano /root/s360-streams/vk_to_telegram.py

# Найдите строку 44:
VK_TOKEN = os.getenv("VK_TOKEN") or "VK_ACCESS_TOKEN"

# Замените на:
VK_TOKEN = os.getenv("VK_TOKEN") or "ваш_реальный_vk_токен_здесь"
```

## Получение нового токена VK (если токен потерян)

1. Перейдите на https://vk.com/dev
2. Создайте Standalone-приложение
3. Получите access_token с правами: `wall`, `groups`
4. Добавьте токен в .env или в файл vk_to_telegram.py

## После добавления токена

```bash
systemctl restart vk-to-telegram.service
systemctl status vk-to-telegram.service
tail -n 20 /root/s360-streams/vk_to_telegram.log
```

