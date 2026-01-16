# Исправление ошибки "invalid scope" при получении токена VK

## Проблема
Ошибка: `{"error":"invalid_request", "error_description":"invalid scope"}`

Это означает, что приложение не поддерживает запрошенные права или они не настроены.

## Решение 1: Убрать `offline` из scope

Попробуйте URL без `offline`:

```
https://oauth.vk.com/authorize?client_id=54378163&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=wall,groups&response_type=token&v=5.199
```

**Важно:** Без `offline` токен будет действовать 24 часа, потом нужно будет обновлять.

## Решение 2: Использовать только `wall`

Если и это не работает, попробуйте только `wall`:

```
https://oauth.vk.com/authorize?client_id=54378163&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=wall&response_type=token&v=5.199
```

## Решение 3: Проверить настройки приложения

1. Перейдите на https://dev.vk.com/ru/admin/app-settings/54378163/info
2. Проверьте раздел **"Разработка"** (Development) в левом меню
3. Убедитесь, что приложение имеет тип, который поддерживает нужные права
4. Возможно, нужно изменить тип приложения на **"Standalone"**

## Решение 4: Создать новое Standalone приложение

Если текущее приложение не поддерживает нужные права:

1. Перейдите на https://vk.com/dev
2. Создайте новое **"Standalone приложение"**
3. Получите новый Application ID
4. Используйте его для получения токена

## После получения токена:

```bash
# На сервере
nano /root/s360-streams/.env
# Замените VK_TOKEN= на новый токен
VK_TOKEN=ваш_новый_токен

systemctl restart vk-to-telegram.service
tail -n 20 /root/s360-streams/vk_to_telegram.log
```
