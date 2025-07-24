from logging import Logger, getLogger, Formatter, StreamHandler, FileHandler
from os import makedirs, environ
from typing import Optional
from dotenv import load_dotenv
from datetime import datetime
import pytz
import time


def setup_logger(name: str) -> Logger:
    """
    Настраивает и возвращает логгер с заданным именем, используя часовой пояс UTC+3.

    Args:
        name: Имя логгера (обычно __name__ модуля).

    Returns:
        Настроенный объект логгера.
    """
    # Загружаем переменные окружения из .env
    load_dotenv()

    # Получаем уровень логирования из .env или устанавливаем INFO по умолчанию
    log_level_str = environ.get("LOG_LEVEL", "INFO").upper()
    log_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    log_level = log_levels.get(log_level_str, 20)  # INFO по умолчанию

    # Создаём логгер
    logger = getLogger(name)
    logger.setLevel(log_level)

    # Проверяем, не добавлены ли уже обработчики, чтобы избежать дублирования
    if not logger.handlers:
        # Форматтер для логов с часовым поясом UTC+3 (Europe/Moscow)
        class MoscowFormatter(Formatter):
            def converter(self, timestamp: float) -> time.struct_time:
                """
                Преобразует временную метку в struct_time с учётом часового пояса UTC+3.

                Args:
                    timestamp: Временная метка в секундах (Unix timestamp).

                Returns:
                    Объект struct_time в часовом поясе Europe/Moscow.
                """
                moscow_tz = pytz.timezone("Europe/Moscow")
                dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
                dt_moscow = dt.astimezone(moscow_tz)
                return dt_moscow.timetuple()

        formatter = MoscowFormatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Обработчик для консоли
        console_handler = StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)

        # Обработчик для файла
        makedirs("logs", exist_ok=True)  # Создаём директорию logs, если не существует
        file_handler = FileHandler("logs/app.log", encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)

        # Добавляем обработчики к логгеру
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger
