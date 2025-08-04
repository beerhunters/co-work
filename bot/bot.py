import os
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, Update
import traceback
from aiogram import BaseMiddleware

from typing import Any, Callable, Dict, Awaitable

from datetime import datetime
import pytz

from bot.hndlrs.ticket_hndlr import register_ticket_handlers
from utils.bot_instance import get_bot
from .hndlrs.registration_hndlr import register_reg_handlers
from .hndlrs.booking_hndlr import register_book_handlers
from models.models import init_db, create_admin
from dotenv import load_dotenv

from utils.logger import setup_application_logging, init_simple_logging

load_dotenv()

# Настраиваем логирование для всего приложения (показывает настройки)
logger = init_simple_logging("CoworkingBot")  # Покажет только "MyBot started"
# logger = setup_application_logging("CoworkingBot")  # Немного больше информации
# logger = setup_application_logging(
#     "CoworkingBot", verbose=True
# )  # Показывает все детали

# ID группы для логов ошибок
LOGS_CHAT_ID = os.getenv("FOR_LOGS")


class ErrorLoggingMiddleware(BaseMiddleware):
    """
    Middleware для перехвата и логирования ошибок в обработчиках сообщений и callback-запросов.
    Отправляет уведомления об ошибках в группу, указанную в FOR_LOGS.
    """

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        try:
            # Вызываем обработчик события
            return await handler(event, data)
        except Exception as e:
            # Формируем информацию об ошибке
            bot = data.get("bot") or get_bot()
            event_type = "unknown"
            user_id = "Неизвестно"
            username = "Неизвестно"
            event_text = "Неизвестно"

            if isinstance(event, Message):
                event_type = "message"
                user_id = str(event.from_user.id)
                username = (
                    event.from_user.username
                    or event.from_user.full_name
                    or "Не указано"
                )
                event_text = event.text or event.caption or "Пустое сообщение"
            elif isinstance(event, CallbackQuery):
                event_type = "callback_query"
                user_id = str(event.from_user.id)
                username = (
                    event.from_user.username
                    or event.from_user.full_name
                    or "Не указано"
                )
                event_text = event.data or "Пустой callback"

            # Формируем стек вызовов
            stack_trace = "".join(
                traceback.format_exception(type(e), e, e.__traceback__)
            )

            # Форматируем сообщение об ошибке
            moscow_tz = pytz.timezone("Europe/Moscow")
            error_time = datetime.now(moscow_tz).strftime("%Y-%m-%d %H:%M:%S")
            error_message = (
                f"❌ <b>Ошибка в боте</b>\n\n"
                f"📌 <b>Тип события:</b> {event_type}\n"
                f"👤 <b>Пользователь:</b> ID {user_id} ({username})\n"
                f"📝 <b>Событие:</b> <code>{event_text}</code>\n"
                f"⚠️ <b>Ошибка:</b> {type(e).__name__}: {str(e)}\n"
                f"📜 <b>Стек вызовов:</b>\n<code>{stack_trace}</code>\n"
                f"⏰ <b>Время:</b> {error_time}"
            )

            # Логируем ошибку
            logger.error(
                f"Ошибка при обработке {event_type} от пользователя {user_id}: {type(e).__name__}: {str(e)}",
                exc_info=True,
            )

            # Отправляем уведомление в группу, если FOR_LOGS задан
            if LOGS_CHAT_ID:
                try:
                    await bot.send_message(
                        chat_id=LOGS_CHAT_ID, text=error_message, parse_mode="HTML"
                    )
                except Exception as send_error:
                    logger.error(
                        f"Не удалось отправить ошибку в группу {LOGS_CHAT_ID}: {str(send_error)}"
                    )

            # Пропускаем исключение дальше
            raise


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

        bot = get_bot()
        dp = Dispatcher(storage=MemoryStorage())

        # Регистрируем middleware
        dp.message.middleware(ErrorLoggingMiddleware())
        dp.callback_query.middleware(ErrorLoggingMiddleware())

        # Регистрация обработчиков
        register_reg_handlers(dp)
        register_book_handlers(dp)
        register_ticket_handlers(dp)

        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
