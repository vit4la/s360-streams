# Как получить cookies для парсинга закрытой группы VK

## Для чего нужны cookies

Для парсинга закрытой группы VK без API нужны cookies от авторизованной сессии. Это позволяет парсить страницу как авторизованный пользователь.

## Как получить cookies

### Способ 1: Через DevTools браузера (Chrome/Firefox)

1. **Войдите в VK** в браузере (под аккаунтом, который является участником группы `tennisprimesport`)

2. **Откройте DevTools:**
   - Chrome/Edge: F12 или Ctrl+Shift+I
   - Firefox: F12 или Ctrl+Shift+I

3. **Перейдите в раздел Cookies:**
   - Chrome: Application → Cookies → https://vk.com
   - Firefox: Storage → Cookies → https://vk.com

4. **Найдите и скопируйте важные cookies:**
   - `remixsid` - основной cookie сессии (обязательно!)
   - `remixstid` - дополнительный cookie
   - `remixlang` - язык интерфейса

5. **Создайте файл `vk_cookies.txt` на сервере:**
   ```bash
   nano /root/s360-streams/vk_cookies.txt
   ```
   
   Вставьте cookies в формате:
   ```
   remixsid=ваше_значение_remixsid
   remixstid=ваше_значение_remixstid
   remixlang=0
   ```

6. **Сохраните файл** (Ctrl+O, Enter, Ctrl+X)

### Способ 2: Через расширение браузера

1. Установите расширение для экспорта cookies (например, "Cookie-Editor" для Chrome)
2. Экспортируйте cookies для vk.com
3. Сохраните в файл `vk_cookies.txt` на сервере

### Способ 3: Через Python скрипт (автоматизация)

Можно создать скрипт, который авторизуется в VK и сохраняет cookies автоматически.

## Важно:

- **Cookies истекают** - обычно через несколько дней/недель
- **Cookies привязаны к IP** - могут не работать с другого IP (но реже, чем токены)
- **Нужно быть участником группы** - cookies должны быть от аккаунта, который подписан на группу
- **Безопасность** - не делитесь cookies, это как пароль от аккаунта

## После настройки cookies:

```bash
# Перезапустите сервис
systemctl restart vk-to-telegram.service

# Проверьте логи
tail -n 30 /root/s360-streams/vk_to_telegram.log
```

Если парсинг с cookies работает, в логах появится "Успешно получены посты через парсинг с авторизацией."
