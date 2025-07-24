import os
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from .hndlrs.registration_hndlr import register_handlers
from models.models import init_db, create_admin
from dotenv import load_dotenv
from utils.logger import setup_logger

logger = setup_logger(__name__)

load_dotenv()


async def main() -> None:
    """Инициализация и запуск Telegram-бота."""
    try:
        # Инициализация базы данных
        init_db()
        logger.info("База данных для бота инициализирована")

        # Создание администратора
        admin_login = os.getenv("ADMIN_LOGIN", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        if not admin_login or not admin_password:
            logger.error("ADMIN_LOGIN или ADMIN_PASSWORD не заданы в .env")
            raise ValueError("ADMIN_LOGIN и ADMIN_PASSWORD должны быть заданы в .env")

        create_admin(admin_login, admin_password)
        logger.info(f"Проверена/создана запись администратора с логином: {admin_login}")

        # Создаем файл-маркер для healthcheck
        with open("/data/bot_initialized", "w") as f:
            f.write("initialized")
        logger.info("Файл-маркер инициализации создан: /data/bot_initialized")

        bot = Bot(token=os.getenv("BOT_TOKEN"))
        dp = Dispatcher(storage=MemoryStorage())

        # Регистрация обработчиков
        register_handlers(dp)

        logger.info("Бот запущен")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
