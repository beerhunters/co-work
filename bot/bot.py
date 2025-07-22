from typing import Optional
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from .handlers import register_handlers
from .config import BOT_TOKEN
from models.models import init_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Инициализация и запуск Telegram-бота."""
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Инициализация базы данных
    init_db()

    # Регистрация обработчиков
    register_handlers(dp)

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
