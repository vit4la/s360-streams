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

## Получение нового токена VK (если токен потерян или ошибка 15)

### Ошибка 15: "Access denied: this wall available only for community members"

Эта ошибка означает, что:
- Группа стала приватной/закрытой, ИЛИ
- Токен не имеет прав администратора группы

### Решение: Получить токен администратора группы

**Вариант 1: Токен пользователя-администратора (рекомендуется)**

1. Войдите в VK под аккаунтом, который является администратором группы `tennisprimesport`
2. Перейдите на https://oauth.vk.com/authorize?client_id=YOUR_APP_ID&scope=wall,groups&response_type=token&redirect_uri=https://oauth.vk.com/blank.html
   - Замените `YOUR_APP_ID` на ID вашего приложения (можно получить на https://vk.com/dev)
   - Или используйте готовый URL для получения токена: https://oauth.vk.com/authorize?client_id=YOUR_APP_ID&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=wall,groups&response_type=token&v=5.199
3. Разрешите доступ приложению
4. Скопируйте `access_token` из URL (после `access_token=`)
5. Добавьте токен в `.env` файл

**Вариант 2: Токен сообщества (Community Token)**

1. Перейдите в настройки группы `tennisprimesport` в VK
2. Раздел "Работа с API" → "Ключи доступа"
3. Создайте ключ с правами: `wall`, `groups`
4. Скопируйте токен и добавьте в `.env` файл

**Вариант 3: Через VK Dev (Standalone-приложение)**

1. Перейдите на https://vk.com/dev
2. Создайте Standalone-приложение
3. Получите access_token с правами: `wall`, `groups`
4. **ВАЖНО**: Токен должен быть получен от пользователя, который является администратором группы
5. Добавьте токен в .env или в файл vk_to_telegram.py

## После добавления токена

```bash
systemctl restart vk-to-telegram.service
systemctl status vk-to-telegram.service
tail -n 20 /root/s360-streams/vk_to_telegram.log
```







