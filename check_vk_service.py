#!/usr/bin/env python3
"""
Диагностический скрипт для проверки работы VK to Telegram сервиса.
Проверяет:
1. Статус systemd сервиса
2. Логи сервиса
3. Наличие и валидность токенов
4. Работоспособность VK API
5. Работоспособность Telegram API
6. Состояние последнего поста
"""

import json
import os
import subprocess
import sys
from pathlib import Path

def run_command(cmd: list) -> tuple[str, int]:
    """Выполнить команду и вернуть вывод и код возврата."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "Timeout", 1
    except Exception as e:
        return str(e), 1

def check_service_status():
    """Проверить статус systemd сервиса."""
    print("=" * 60)
    print("1. ПРОВЕРКА СТАТУСА СЕРВИСА")
    print("=" * 60)
    
    output, code = run_command(["systemctl", "is-active", "vk-to-telegram.service"])
    if code == 0:
        print(f"✅ Сервис активен: {output}")
    else:
        print(f"❌ Сервис не активен: {output}")
    
    output, code = run_command(["systemctl", "is-enabled", "vk-to-telegram.service"])
    if code == 0:
        print(f"✅ Сервис включен в автозагрузку: {output}")
    else:
        print(f"⚠️  Сервис не включен в автозагрузку: {output}")
    
    print("\nПоследние строки статуса сервиса:")
    output, _ = run_command(["systemctl", "status", "vk-to-telegram.service", "--no-pager", "-l", "-n", "10"])
    print(output)
    print()

def check_logs():
    """Проверить логи сервиса."""
    print("=" * 60)
    print("2. ПРОВЕРКА ЛОГОВ")
    print("=" * 60)
    
    # Логи из journalctl
    print("\nПоследние 20 строк из journalctl:")
    output, _ = run_command(["journalctl", "-u", "vk-to-telegram.service", "-n", "20", "--no-pager"])
    print(output)
    
    # Логи из файла (если есть)
    log_file = Path("/root/s360-streams/vk_to_telegram.log")
    if log_file.exists():
        print(f"\nПоследние 20 строк из файла {log_file}:")
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                print("".join(lines[-20:]))
        except Exception as e:
            print(f"❌ Ошибка при чтении файла: {e}")
    else:
        print(f"\n⚠️  Файл логов {log_file} не найден")
    print()

def check_tokens():
    """Проверить наличие и валидность токенов."""
    print("=" * 60)
    print("3. ПРОВЕРКА ТОКЕНОВ")
    print("=" * 60)
    
    # Проверяем .env файл
    env_file = Path("/root/s360-streams/.env")
    if env_file.exists():
        print(f"✅ Файл .env найден: {env_file}")
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                env_vars = {}
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        value = value.strip('"\'')
                        env_vars[key] = value
                
                vk_token = env_vars.get("VK_TOKEN", "")
                telegram_token = env_vars.get("TELEGRAM_BOT_TOKEN", "")
                telegram_chat_id = env_vars.get("TELEGRAM_CHAT_ID", "")
                
                if vk_token and vk_token != "VK_ACCESS_TOKEN":
                    print(f"✅ VK_TOKEN найден (длина: {len(vk_token)})")
                else:
                    print("❌ VK_TOKEN не найден или не задан")
                
                if telegram_token and telegram_token != "TELEGRAM_BOT_TOKEN":
                    print(f"✅ TELEGRAM_BOT_TOKEN найден (длина: {len(telegram_token)})")
                else:
                    print("❌ TELEGRAM_BOT_TOKEN не найден или не задан")
                
                if telegram_chat_id:
                    print(f"✅ TELEGRAM_CHAT_ID найден: {telegram_chat_id}")
                else:
                    print("⚠️  TELEGRAM_CHAT_ID не найден (будет использован дефолтный)")
        except Exception as e:
            print(f"❌ Ошибка при чтении .env: {e}")
    else:
        print(f"❌ Файл .env не найден: {env_file}")
        print("   Проверяю переменные окружения...")
        vk_token = os.getenv("VK_TOKEN", "")
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if vk_token:
            print(f"✅ VK_TOKEN найден в переменных окружения (длина: {len(vk_token)})")
        else:
            print("❌ VK_TOKEN не найден в переменных окружения")
        if telegram_token:
            print(f"✅ TELEGRAM_BOT_TOKEN найден в переменных окружения (длина: {len(telegram_token)})")
        else:
            print("❌ TELEGRAM_BOT_TOKEN не найден в переменных окружения")
    print()

def check_vk_api():
    """Проверить работоспособность VK API."""
    print("=" * 60)
    print("4. ПРОВЕРКА VK API")
    print("=" * 60)
    
    import requests
    
    # Загружаем токен
    env_file = Path("/root/s360-streams/.env")
    vk_token = None
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("VK_TOKEN="):
                        vk_token = line.split("=", 1)[1].strip('"\'')
                        break
        except:
            pass
    
    if not vk_token:
        vk_token = os.getenv("VK_TOKEN", "")
    
    if not vk_token or vk_token == "VK_ACCESS_TOKEN":
        print("❌ VK_TOKEN не найден, пропускаю проверку API")
        print()
        return
    
    # Проверяем доступ к API
    url = "https://api.vk.com/method/wall.get"
    params = {
        "access_token": vk_token,
        "v": "5.199",
        "owner_id": -212808533,  # tennisprimesport
        "count": 1,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if "error" in data:
            error = data["error"]
            print(f"❌ Ошибка VK API: {error.get('error_msg', 'Unknown error')} (код: {error.get('error_code', '?')})")
            if error.get("error_code") == 5:
                print("   ⚠️  Токен недействителен или истек срок действия")
        else:
            items = data.get("response", {}).get("items", [])
            print(f"✅ VK API работает, получено {len(items)} пост(ов)")
            if items:
                post = items[0]
                print(f"   Последний пост ID: {post.get('id')}, дата: {post.get('date')}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при запросе к VK API: {e}")
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
    print()

def check_telegram_api():
    """Проверить работоспособность Telegram API."""
    print("=" * 60)
    print("5. ПРОВЕРКА TELEGRAM API")
    print("=" * 60)
    
    import requests
    
    # Загружаем токен
    env_file = Path("/root/s360-streams/.env")
    telegram_token = None
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        telegram_token = line.split("=", 1)[1].strip('"\'')
                        break
        except:
            pass
    
    if not telegram_token:
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    
    if not telegram_token or telegram_token == "TELEGRAM_BOT_TOKEN":
        print("❌ TELEGRAM_BOT_TOKEN не найден, пропускаю проверку API")
        print()
        return
    
    # Проверяем доступ к API
    url = f"https://api.telegram.org/bot{telegram_token}/getMe"
    
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("ok"):
            print(f"❌ Ошибка Telegram API: {data.get('description', 'Unknown error')}")
        else:
            bot_info = data.get("result", {})
            print(f"✅ Telegram API работает")
            print(f"   Бот: @{bot_info.get('username', '?')} ({bot_info.get('first_name', '?')})")
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при запросе к Telegram API: {e}")
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
    print()

def check_state_file():
    """Проверить файл состояния."""
    print("=" * 60)
    print("6. ПРОВЕРКА ФАЙЛА СОСТОЯНИЯ")
    print("=" * 60)
    
    state_file = Path("/root/s360-streams/vk_last_post_state.json")
    if state_file.exists():
        print(f"✅ Файл состояния найден: {state_file}")
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
                last_id = state.get("last_post_id", 0)
                initialized = state.get("initialized", False)
                print(f"   Последний отправленный post_id: {last_id}")
                print(f"   Инициализирован: {initialized}")
        except Exception as e:
            print(f"❌ Ошибка при чтении файла состояния: {e}")
    else:
        print(f"⚠️  Файл состояния не найден: {state_file}")
        print("   Это нормально при первом запуске")
    print()

def main():
    """Основная функция."""
    print("\n" + "=" * 60)
    print("ДИАГНОСТИКА СЕРВИСА VK TO TELEGRAM")
    print("=" * 60 + "\n")
    
    check_service_status()
    check_logs()
    check_tokens()
    check_vk_api()
    check_telegram_api()
    check_state_file()
    
    print("=" * 60)
    print("ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
