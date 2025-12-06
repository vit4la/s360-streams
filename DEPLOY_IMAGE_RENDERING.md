# Инструкция по деплою системы стилизации картинок

## Быстрый старт на сервере

### 1. Обновить код

```bash
cd /root/s360-streams
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Обновить `.env`

Добавь в `.env`:

```bash
PEXELS_API_KEY=2sEQzxTl8QPLIJ3YFCZpNwDtGe4KqRvys7fg5CQKBXosSmkYcS4F0EXN
IMAGE_RENDER_SERVICE_URL=http://80.87.102.103:8000
```

### 3. Запустить сервис стилизации

**Вариант А: Вручную (для теста)**

```bash
cd /root/s360-streams
source venv/bin/activate
python image_render_service.py
```

**Вариант Б: Через systemd (для постоянной работы)**

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
sudo systemctl daemon-reload
sudo systemctl enable image-render
sudo systemctl start image-render
sudo systemctl status image-render
```

### 4. Проверить работу

```bash
curl http://80.87.102.103:8000/health
```

Должен вернуть: `{"status": "ok"}`

### 5. Перезапустить основные сервисы

```bash
sudo systemctl restart moderation-bot
sudo systemctl restart gpt-worker
```

---

## Проверка логов

```bash
# Сервис стилизации
sudo journalctl -u image-render -f

# Бот модерации
tail -f /root/s360-streams/logs/moderation_bot.log

# GPT воркер
tail -f /root/s360-streams/logs/moderation_bot.log
```

---

## Если что-то не работает

1. **Сервис стилизации не отвечает:**
   - Проверь, что он запущен: `sudo systemctl status image-render`
   - Проверь порт: `netstat -tlnp | grep 8000`
   - Проверь firewall: `sudo ufw allow 8000`

2. **Картинки не стилизуются:**
   - Проверь логи GPT воркера
   - Проверь, что Pexels API ключ правильный
   - Проверь, что сервис доступен: `curl http://80.87.102.103:8000/health`

3. **Telegram не принимает картинки:**
   - Убедись, что URL доступен извне (не localhost)
   - Проверь, что сервис возвращает полный URL с IP сервера

