#!/usr/bin/env python3
"""
Микросервис для стилизации изображений в фирменном стиле.
Принимает URL картинки, накладывает шаблон с брендингом, возвращает URL готовой картинки.
"""

import logging
import os
from pathlib import Path
from typing import Optional
import uuid

from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
import httpx
from io import BytesIO

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
RENDERED_IMAGES_DIR = Path(__file__).parent / "rendered_images"
RENDERED_IMAGES_DIR.mkdir(exist_ok=True)

# Базовый URL сервиса (для формирования полных URL картинок)
SERVICE_BASE_URL = os.getenv("IMAGE_RENDER_SERVICE_URL", "http://localhost:8000")

# Размер итоговой картинки
FINAL_WIDTH = 1320
FINAL_HEIGHT = 1320

# Цвет бренда (лаймовый/салатовый) - как на скриншоте
BRAND_COLOR = "#7FFF00"  # Chartreuse (салатовый/лаймовый)
# Толщина рамки в пикселях
BORDER_WIDTH = 8
# Путь к логотипу
LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def download_image(url: str) -> Optional[Image.Image]:
    """Скачать изображение по URL.

    Args:
        url: URL изображения

    Returns:
        Объект PIL Image или None при ошибке
    """
    try:
        logger.info("Скачивание изображения: %s", url)
        # Используем httpx с поддержкой SOCKS5 прокси
        proxy_url = os.getenv("OPENAI_PROXY") or os.getenv("HTTP_PROXY")
        if proxy_url and proxy_url.startswith("http://"):
            proxy_url = proxy_url.replace("http://", "socks5://", 1)
        
        logger.info("Используется прокси: %s", proxy_url if proxy_url else "нет")
        
        with httpx.Client(proxy=proxy_url, timeout=30.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            # Конвертируем в RGB, если нужно (для JPEG)
            if img.mode != "RGB":
                img = img.convert("RGB")
            logger.info("Изображение успешно скачано: %sx%s, mode=%s", img.width, img.height, img.mode)
            return img
    except Exception as e:
        logger.error("Ошибка при скачивании изображения %s: %s", url, e, exc_info=True)
        return None


def resize_and_crop(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """Изменить размер изображения с сохранением пропорций и обрезкой до нужного размера.

    Args:
        img: Исходное изображение
        target_width: Целевая ширина
        target_height: Целевая высота

    Returns:
        Изображение нужного размера
    """
    # Вычисляем соотношение сторон
    target_ratio = target_width / target_height
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        # Изображение шире - обрезаем по ширине
        new_height = target_height
        new_width = int(new_height * img_ratio)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        # Обрезаем по центру
        left = (new_width - target_width) // 2
        img = img.crop((left, 0, left + target_width, target_height))
    else:
        # Изображение выше - обрезаем по высоте
        new_width = target_width
        new_height = int(new_width / img_ratio)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        # Обрезаем по центру
        top = (new_height - target_height) // 2
        img = img.crop((0, top, target_width, top + target_height))

    return img


def apply_brand_template(img: Image.Image) -> Image.Image:
    """Наложить фирменный шаблон на изображение.

    Args:
        img: Изображение 1320x1320

    Returns:
        Изображение с наложенным шаблоном
    """
    # Создаём новое изображение с рамкой
    # Внутренний размер (без рамки)
    inner_width = FINAL_WIDTH - (BORDER_WIDTH * 2)
    inner_height = FINAL_HEIGHT - (BORDER_WIDTH * 2)
    
    # Изменяем размер изображения до внутреннего размера
    img_resized = img.resize((inner_width, inner_height), Image.Resampling.LANCZOS)
    
    # Создаём новое изображение с рамкой
    result = Image.new("RGB", (FINAL_WIDTH, FINAL_HEIGHT), BRAND_COLOR)
    
    # Вставляем изображение в центр (с рамкой вокруг)
    paste_x = BORDER_WIDTH
    paste_y = BORDER_WIDTH
    result.paste(img_resized, (paste_x, paste_y))

    # Создаём полупрозрачный градиент (сверху вниз, от прозрачного к чёрному)
    overlay = Image.new("RGBA", (FINAL_WIDTH, FINAL_HEIGHT), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)

    # Градиент сверху (лёгкая затемнённость)
    for y in range(FINAL_HEIGHT // 3):
        alpha = int(30 * (1 - y / (FINAL_HEIGHT // 3)))
        draw_overlay.rectangle(
            [(0, y), (FINAL_WIDTH, y + 1)],
            fill=(0, 0, 0, alpha)
        )

    # Накладываем градиент
    result = Image.alpha_composite(
        result.convert("RGBA"),
        overlay
    ).convert("RGB")

    # Добавляем логотип внизу по центру
    draw = ImageDraw.Draw(result)
    
    # Пытаемся загрузить логотип
    logo_img = None
    if LOGO_PATH.exists():
        try:
            logo_img = Image.open(LOGO_PATH)
            # Конвертируем в RGBA если нужно
            if logo_img.mode != "RGBA":
                logo_img = logo_img.convert("RGBA")
            logger.info("Логотип загружен: %sx%s", logo_img.width, logo_img.height)
        except Exception as e:
            logger.warning("Не удалось загрузить логотип: %s", e)
    
    if logo_img:
        # Масштабируем логотип (максимальная высота 120px, сохраняем пропорции)
        max_logo_height = 120
        logo_ratio = logo_img.width / logo_img.height
        if logo_img.height > max_logo_height:
            logo_height = max_logo_height
            logo_width = int(logo_height * logo_ratio)
            logo_img = logo_img.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
        
        # Позиция: внизу по центру
        logo_x = (FINAL_WIDTH - logo_img.width) // 2
        logo_y = FINAL_HEIGHT - logo_img.height - 40
        
        # Вставляем логотип
        result.paste(logo_img, (logo_x, logo_y), logo_img if logo_img.mode == "RGBA" else None)
        logger.info("Логотип размещен: x=%s, y=%s", logo_x, logo_y)
    else:
        # Fallback: текст "SETKA360" если логотип не найден
        try:
            font_size = 60
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
            except:
                font = ImageFont.load_default()

        text = "SETKA360"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Позиция: внизу по центру
        x = (FINAL_WIDTH - text_width) // 2
        y = FINAL_HEIGHT - text_height - 40

        # Рисуем текст с обводкой для читаемости
        for adj in range(-2, 3):
            for adj2 in range(-2, 3):
                if adj != 0 or adj2 != 0:
                    draw.text(
                        (x + adj, y + adj2),
                        text,
                        font=font,
                        fill=(0, 0, 0, 200)
                    )

        # Сам текст лаймовым цветом
        draw.text(
            (x, y),
            text,
            font=font,
            fill=BRAND_COLOR
        )
        logger.info("Использован текстовый логотип (файл логотипа не найден)")

    return result


@app.route("/render", methods=["POST"])
def render_image():
    """Обработать запрос на стилизацию изображения.

    Ожидает JSON:
    {
        "image_url": "https://...",
        "title": "Заголовок",
        "template": "default"
    }

    Возвращает JSON:
    {
        "final_image_url": "http://localhost:8000/rendered/abc123.jpg"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        image_url = data.get("image_url")
        title = data.get("title", "")
        template = data.get("template", "default")

        if not image_url:
            return jsonify({"error": "image_url is required"}), 400

        logger.info("Запрос на стилизацию: image_url=%s, title=%.50s, template=%s", 
                   image_url[:100], title, template)

        # Скачиваем изображение
        img = download_image(image_url)
        if not img:
            return jsonify({"error": "Failed to download image"}), 500

        # Изменяем размер до 1320x1320
        img = resize_and_crop(img, FINAL_WIDTH, FINAL_HEIGHT)

        # Накладываем шаблон
        if template == "default":
            img = apply_brand_template(img)
        else:
            logger.warning("Неизвестный шаблон: %s, используем default", template)
            img = apply_brand_template(img)

        # Сохраняем как JPEG
        filename = f"{uuid.uuid4().hex}.jpg"
        filepath = RENDERED_IMAGES_DIR / filename
        img.save(filepath, "JPEG", quality=90)

        # Формируем полный URL
        final_image_url = f"{SERVICE_BASE_URL}/rendered/{filename}"

        logger.info("Изображение стилизовано: %s, URL: %s", filename, final_image_url)

        return jsonify({
            "final_image_url": final_image_url,
            "filename": filename
        })

    except Exception as e:
        logger.error("Ошибка при обработке запроса: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/rendered/<filename>", methods=["GET"])
def serve_rendered_image(filename: str):
    """Отдать стилизованное изображение.

    Args:
        filename: Имя файла
    """
    filepath = RENDERED_IMAGES_DIR / filename
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    from flask import send_file
    return send_file(filepath, mimetype="image/jpeg")


@app.route("/health", methods=["GET"])
def health():
    """Проверка здоровья сервиса."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    logger.info("Запуск сервиса стилизации изображений...")
    logger.info("Директория для сохранения: %s", RENDERED_IMAGES_DIR)
    app.run(host="0.0.0.0", port=8000, debug=False)

