# Как получить токен VK API из VK ID приложения

## Важно: Разница между VK ID и VK API

- **VK ID** (id.vk.com) - для авторизации пользователей через VK
- **VK API** (vk.com/dev) - для работы с API (wall.get, groups.get и т.д.)

Для парсинга постов через `wall.get` нужен токен **VK API**, а не VK ID.

## Вариант 1: Использовать "Сервисный ключ доступа" из VK ID

На скриншоте видно "Сервисный ключ доступа" (Service access key). Попробуйте:

1. **Нажмите на иконку глаза** рядом с "Сервисный ключ доступа" чтобы увидеть ключ
2. **Скопируйте ключ**
3. **Проверьте, работает ли он для wall.get:**

```bash
# На сервере проверьте токен
curl "https://api.vk.com/method/wall.get?owner_id=-212808533&access_token=ВАШ_СЕРВИСНЫЙ_КЛЮЧ&v=5.199"
```

Если работает - используйте его. Если нет - переходите к Варианту 2.

## Вариант 2: Получить токен через классическое VK API приложение

Если сервисный ключ VK ID не работает для wall.get, нужно получить токен через классическое VK API:

### Шаг 1: Перейдите на https://vk.com/dev

**ВАЖНО:** Это другой раздел, не VK ID!

### Шаг 2: Создайте или найдите приложение

1. Войдите в https://vk.com/dev
2. Перейдите в **"Мои приложения"**
3. Если приложения нет - создайте **"Standalone приложение"**
4. Скопируйте **Application ID** (ID приложения)

### Шаг 3: Получите токен через OAuth

Откройте в браузере (замените `YOUR_APP_ID` на ID приложения):

```
https://oauth.vk.com/authorize?client_id=YOUR_APP_ID&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=wall,groups,offline&response_type=token&v=5.199
```

Нажмите "Разрешить" и скопируйте `access_token` из URL.

### Шаг 4: Сохраните токен

```bash
nano /root/s360-streams/.env
# Замените VK_TOKEN= на новый токен
VK_TOKEN=ваш_новый_токен

systemctl restart vk-to-telegram.service
```

## Проверка

```bash
python3 check_vk_service.py
```

Если в разделе "4. ПРОВЕРКА VK API" появится "✅ VK API работает", проблема решена.
