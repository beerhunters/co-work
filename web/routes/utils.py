import asyncio
import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Any

from aiogram import Bot
from sqlalchemy import desc

from models.models import Notification
from utils.bot_instance import get_bot

from web.app import db

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "mp4", "mov"}
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
ALLOWED_HTML_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "a",
    "code",
    "pre",
    "tg-spoiler",
    "tg-emoji",
    "blockquote",
}
AVATAR_FOLDER = "/app/static/avatars"


def allowed_file(filename: str) -> bool:
    """
    Проверяет, допустимое ли расширение файла.

    Args:
        filename: Имя файла.

    Returns:
        True, если расширение допустимо, иначе False.

    Example:
        >>> allowed_file("image.png")
        True
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_avatar_file(filename: str) -> bool:
    """
    Проверяет, допустимое ли расширение для аватара.

    Args:
        filename: Имя файла.

    Returns:
        True, если расширение допустимо, иначе False.

    Example:
        >>> allowed_avatar_file("avatar.jpg")
        True
    """
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS
    )


def custom_secure_filename(filename: str) -> str:
    """
    Очищает имя файла, сохраняя кириллические символы и заменяя недопустимые на подчеркивание.

    Args:
        filename: Исходное имя файла.

    Returns:
        Очищенное имя файла.

    Example:
        >>> custom_secure_filename("фото пользователя.jpg")
        'фото_пользователя.jpg'
    """
    filename = re.sub(r"[^\w\-\.\u0400-\u04FF]", "_", filename)
    filename = re.sub(r"_+", "_", filename)
    filename = filename.strip("_")
    return filename or "unnamed"


def check_file_exists(filename: Optional[str]) -> bool:
    """
    Проверяет, существует ли файл по указанному пути.

    Args:
        filename: Имя файла.

    Returns:
        True, если файл существует и читаем, иначе False.

    Example:
        >>> check_file_exists("avatars/photo.jpg")
        True
    """
    if not filename:
        logger.info("check_file_exists: Пустое имя файла")
        return False
    clean_filename = (
        filename.replace("avatars/", "")
        if filename.startswith("avatars/")
        else filename
    )
    file_path = os.path.join(AVATAR_FOLDER, clean_filename)
    try:
        exists = os.path.exists(file_path)
        readable = os.access(file_path, os.R_OK) if exists else False
        logger.info(
            f"check_file_exists: Проверка пути {file_path}, существует: {exists}, читаем: {readable}"
        )
        if exists and not readable:
            logger.warning(f"Файл {file_path} существует, но не читаем")
        return exists and readable
    except Exception as e:
        logger.error(f"Ошибка при проверке файла {file_path}: {str(e)}")
        return False


def get_unread_notifications_count() -> int:
    """
    Получение количества непрочитанных уведомлений.

    Returns:
        Количество непрочитанных уведомлений.

    Example:
        >>> get_unread_notifications_count()
        5
    """
    count = db.session.query(Notification).filter_by(is_read=False).count()
    logger.info(f"Количество непрочитанных уведомлений: {count}")
    return count


def get_recent_notifications(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Возвращает последние уведомления в формате, подходящем для шаблона и AJAX.

    Args:
        limit: Максимальное количество уведомлений (по умолчанию 5).

    Returns:
        Список словарей с данными уведомлений.

    Example:
        >>> get_recent_notifications(2)
        [{'id': 1, 'message': 'Новая заявка #1', 'created_at': '2025-07-30 13:00', ...}, ...]
    """
    notifications = (
        db.session.query(Notification)
        .order_by(desc(Notification.created_at))
        .limit(limit)
        .all()
    )
    result = []
    for n in notifications:
        notification_type = "general"
        target_url = "/notifications"
        if "Новый пользователь:" in n.message and n.user_id:
            notification_type = "user"
            target_url = f"/user/{n.user_id}"
        elif "Новая бронь" in n.message and n.booking_id:
            notification_type = "booking"
            target_url = f"/booking/{n.booking_id}"
        elif "Новая заявка" in n.message and n.ticket_id:
            notification_type = "ticket"
            target_url = f"/ticket/{n.ticket_id}"

        result.append(
            {
                "id": n.id,
                "message": n.message,
                "created_at": (
                    n.created_at.strftime("%Y-%m-%d %H:%M")
                    if isinstance(n.created_at, datetime)
                    else n.created_at
                ),
                "is_read": n.is_read,
                "type": notification_type,
                "target_url": target_url,
            }
        )
    return result


def clean_html(text: str) -> str:
    """
    Очищает HTML-текст от неподдерживаемых Telegram тегов, сохраняя разрешенные теги и переносы строк.

    Args:
        text: Входной HTML-текст.

    Returns:
        Очищенный текст.

    Example:
        >>> clean_html("<p>Test</p><b>Bold</b><script>alert()</script>")
        'Test\nBold'
    """
    text = re.sub(r"<p\s*[^>]*>|</p>", "\n", text, flags=re.IGNORECASE)
    allowed_tags_pattern = "|".join(rf"(?:{tag})" for tag in ALLOWED_HTML_TAGS)
    cleaned_text = re.sub(
        rf"<(?!/?({allowed_tags_pattern})(?: [^>]*)?>).*?>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    lines = cleaned_text.split("\n")
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    return "\n".join(cleaned_lines)


_bot_instance: Optional[Bot] = None


async def send_telegram_message_async(telegram_id: int, message: str, bot: Bot) -> bool:
    """
    Асинхронно отправляет сообщение в Telegram.

    Args:
        telegram_id: ID пользователя в Telegram.
        message: Текст сообщения.
        bot: Экземпляр aiogram.Bot.

    Returns:
        bool: True, если сообщение отправлено, иначе False.
    """
    try:
        await bot.send_message(chat_id=telegram_id, text=message, parse_mode="HTML")
        logger.info(f"Сообщение отправлено пользователю {telegram_id}")
        return True
    except Exception as e:
        logger.error(
            f"Не удалось отправить сообщение пользователю {telegram_id}: {str(e)}"
        )
        return False


def send_telegram_message_sync(telegram_id: int, message: str) -> bool:
    """
    Отправляет сообщение пользователю через Telegram в синхронном контексте.

    Args:
        telegram_id: ID пользователя в Telegram.
        message: Текст сообщения.

    Returns:
        bool: True, если сообщение отправлено, иначе False.

    Example:
        >>> send_telegram_message_sync(123456, "Hello!")
        True
    """
    bot = get_bot()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(
            send_telegram_message_async(telegram_id, message, bot)
        )
        return success
    except Exception as e:
        logger.error(
            f"Ошибка в синхронной отправке сообщения пользователю {telegram_id}: {str(e)}"
        )
        return False
    finally:
        try:
            loop.run_until_complete(bot.session.close())  # Закрываем сессию
            loop.close()
        except Exception as e:
            logger.warning(f"Ошибка при закрытии сессии или цикла: {str(e)}")
