import os
from typing import Optional
from aiogram import Bot
from utils.logger import setup_logger
from dotenv import load_dotenv


load_dotenv()
logger = setup_logger(__name__)
BOT_TOKEN = os.getenv("BOT_TOKEN")

_bot: Optional[Bot] = None


def init_bot() -> Bot:
    """
    Инициализирует и возвращает экземпляр бота.

    Returns:
        Bot: Инициализированный экземпляр aiogram.Bot.

    Raises:
        ValueError: Если BOT_TOKEN не указан в конфигурации.
    """
    global _bot
    if _bot is None:
        bot_token = BOT_TOKEN
        if not bot_token:
            logger.error("BOT_TOKEN не указан в конфигурации")
            raise ValueError("BOT_TOKEN не указан")
        _bot = Bot(token=bot_token)
        logger.info("Экземпляр бота успешно инициализирован")
    return _bot


def get_bot() -> Bot:
    """
    Возвращает существующий экземпляр бота или инициализирует новый.

    Returns:
        Bot: Экземпляр aiogram.Bot.

    Raises:
        ValueError: Если бот не был инициализирован.
    """
    if _bot is None:
        return init_bot()
    return _bot
