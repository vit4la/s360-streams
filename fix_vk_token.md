# Инструкция по исправлению ошибки VK API 15

## Проблема
Ошибка: `Access denied: this wall available only for community members` (код 15)

Это означает, что текущий токен VK не имеет доступа к стене группы `tennisprimesport`.

## Решение

### Шаг 1: Проверьте, является ли группа приватной

1. Откройте https://vk.com/tennisprimesport
2. Если группа закрыта/приватна, нужно либо:
   - Сделать группу публичной, ИЛИ
   - Получить токен от администратора группы

### Шаг 2: Получите новый токен с правами администратора

**Способ 1: Через браузер (самый простой)**

1. Войдите в VK под аккаунтом администратора группы `tennisprimesport`
2. Откройте в браузере (замените `YOUR_APP_ID` на ID приложения):
   ```
   https://oauth.vk.com/authorize?client_id=YOUR_APP_ID&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=wall,groups&response_type=token&v=5.199
   ```
   
   Или используйте универсальный способ:
   ```
   https://oauth.vk.com/authorize?client_id=YOUR_APP_ID&scope=wall,groups&response_type=token&redirect_uri=https://oauth.vk.com/blank.html
   ```

3. Нажмите "Разрешить"
4. После перенаправления в адресной строке будет URL вида:
   ```
   https://oauth.vk.com/blank.html#access_token=ВАШ_ТОКЕН&expires_in=86400&user_id=123456
   ```
5. Скопируйте значение `access_token` (часть между `access_token=` и `&`)

**Способ 2: Через настройки группы (если есть доступ)**

1. Откройте группу `tennisprimesport` в VK
2. Перейдите в "Управление" → "Работа с API"
3. Создайте ключ доступа с правами: `wall`, `groups`
4. Скопируйте токен

### Шаг 3: Добавьте токен на сервер

```bash
# На сервере откройте .env файл
nano /root/s360-streams/.env

# Найдите строку VK_TOKEN= и замените значение на новый токен
VK_TOKEN=ваш_новый_токен_здесь

# Сохраните файл (Ctrl+O, Enter, Ctrl+X)
```

### Шаг 4: Перезапустите сервис

```bash
# Перезапустите сервис
systemctl restart vk-to-telegram.service

# Проверьте статус
systemctl status vk-to-telegram.service

# Проверьте логи
tail -n 20 /root/s360-streams/vk_to_telegram.log
```

### Шаг 5: Проверьте работу

```bash
# Запустите диагностический скрипт
python3 check_vk_service.py
```

Если ошибка 15 исчезла и появилось "✅ VK API работает", значит проблема решена.

## Если проблема не решается

1. Убедитесь, что аккаунт, от которого получен токен, является администратором группы
2. Проверьте, что группа не стала приватной
3. Попробуйте получить токен через другой способ
4. Проверьте, что токен не истек (обычно токены действуют 24 часа, но можно получить бессрочный)
