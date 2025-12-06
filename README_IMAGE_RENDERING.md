# Автоматизация новостей с подбором и стилизацией картинок

## Обзор

Система автоматически обрабатывает новости из Telegram-каналов:
1. **Источник** → текст из `@elitetennis`, `@primetennis`
2. **GPT** → генерирует заголовок, текст, хэштеги и `image_query` для поиска картинки
3. **Pexels API** → находит 3 картинки по запросу
4. **Сервис стилизации** → накладывает фирменный шаблон (1320×1320, JPEG, надпись "setka360")
5. **Модерация** → оператор видит стилизованную картинку, может выбрать другую из 3 вариантов
6. **Публикация** → в `@S360streams` с картинкой

---

## Компоненты системы

### 1. `telethon_listener.py`
Слушает исходные каналы, сохраняет посты в БД.

### 2. `gpt_worker.py`
Обрабатывает посты через GPT, запрашивает картинки в Pexels, стилизует первую через сервис.

### 3. `image_render_service.py`
Микросервис Flask для стилизации изображений:
- Принимает: `POST /render` с `{image_url, title, template}`
- Возвращает: `{final_image_url}`
- Раздаёт готовые картинки: `GET /rendered/<filename>`

### 4. `moderation_bot.py`
Бот для модерации:
- Показывает черновики со стилизованными картинками
- Кнопка "♻️ Другая картинка" → показывает 3 варианта для выбора
- Публикует в `@S360streams` с выбранной картинкой

---

## Установка и настройка

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Настроить `.env` файл

Создай `.env` в корне проекта:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=твой_токен_бота_модерации
TELEGRAM_API_ID=твой_api_id
TELEGRAM_API_HASH=твой_api_hash

# OpenAI
OPENAI_API_KEY=твой_openai_ключ
OPENAI_PROXY=  # Опционально, если нужен прокси

# Pexels
PEXELS_API_KEY=2sEQzxTl8QPLIJ3YFCZpNwDtGe4KqRvys7fg5CQKBXosSmkYcS4F0EXN

# Сервис стилизации (опционально, если не localhost:8000)
IMAGE_RENDER_SERVICE_URL=http://localhost:8000
```

### 3. Запустить сервис стилизации

```bash
python image_render_service.py
```

Сервис запустится на `http://localhost:8000` (или на IP сервера, если запускаешь на VPS).

**Важно:** Если запускаешь на сервере, убедись, что порт 8000 открыт в firewall.

### 4. Запустить основные сервисы

В отдельных терминалах:

```bash
# 1. Слушатель исходных каналов
python telethon_listener.py

# 2. GPT воркер (обработка постов)
python gpt_worker.py

# 3. Бот модерации
python moderation_bot.py
```

---

## Запуск через systemd (на сервере)

### Сервис стилизации

Создай `/etc/systemd/system/image-render.service`:

```ini
[Unit]
Description=Image Render Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/s360-streams
Environment="IMAGE_RENDER_SERVICE_URL=http://80.87.102.103:8000"
ExecStart=/root/s360-streams/venv/bin/python /root/s360-streams/image_render_service.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Запуск:

```bash
sudo systemctl enable image-render
sudo systemctl start image-render
sudo systemctl status image-render
```

---

## Проверка работы

### 1. Проверить сервис стилизации

```bash
curl http://localhost:8000/health
```

Должен вернуть: `{"status": "ok"}`

### 2. Тест стилизации

```bash
curl -X POST http://localhost:8000/render \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://images.pexels.com/photos/123456/pexels-photo-123456.jpeg",
    "title": "Тест",
    "template": "default"
  }'
```

Должен вернуть JSON с `final_image_url`.

### 3. Проверить логи

```bash
# Логи GPT воркера
tail -f logs/moderation_bot.log

# Логи сервиса стилизации (если запущен через systemd)
sudo journalctl -u image-render -f
```

---

## Структура файлов

```
/root/s360-streams/
├── telethon_listener.py      # Слушатель исходных каналов
├── gpt_worker.py             # Обработка через GPT + Pexels
├── image_render_service.py   # Микросервис стилизации
├── moderation_bot.py         # Бот модерации
├── database.py               # Работа с БД
├── config_moderation.py     # Конфигурация
├── rendered_images/          # Стилизованные картинки (создаётся автоматически)
├── posts.db                  # SQLite база данных
└── .env                      # Секреты (не коммитить!)
```

---

## Как это работает

1. **Новый пост в исходном канале** → `telethon_listener.py` сохраняет в БД
2. **GPT воркер** видит новый пост → отправляет в GPT → получает `image_query`
3. **Запрос к Pexels** → получает 3 картинки
4. **Стилизация первой** → запрос к `/render` → получает `final_image_url`
5. **Сохранение в черновик** → `final_image_url` записывается в БД
6. **Бот модерации** → отправляет оператору черновик со стилизованной картинкой
7. **Оператор нажимает "Другая картинка"** → бот показывает все 3 варианта
8. **Оператор выбирает** → обновляется `final_image_url` в БД
9. **Публикация** → бот отправляет в `@S360streams` с `final_image_url`

---

## Возможные проблемы

### Сервис стилизации не отвечает

- Проверь, что он запущен: `ps aux | grep image_render_service`
- Проверь порт: `netstat -tlnp | grep 8000`
- Проверь логи: `sudo journalctl -u image-render -n 50`

### Картинки не стилизуются

- Проверь, что Pexels API возвращает картинки (смотри логи `gpt_worker.py`)
- Проверь, что сервис стилизации доступен по URL из `IMAGE_RENDER_SERVICE_URL`
- Проверь права на запись в папку `rendered_images/`

### Telegram не принимает картинки

- Убедись, что URL картинки доступен извне (не localhost)
- Если на сервере, используй внешний IP: `IMAGE_RENDER_SERVICE_URL=http://80.87.102.103:8000`

---

## Дальнейшие улучшения

- [ ] Добавить больше шаблонов стилизации
- [ ] Перенести картинки на CDN (Cloudflare R2, S3)
- [ ] Добавить кэширование запросов к Pexels
- [ ] Оптимизировать размер картинок перед сохранением

