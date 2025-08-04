# # import time
# # from datetime import datetime
# # from logging import Logger, getLogger, Formatter, StreamHandler, FileHandler
# # from os import makedirs, environ
# #
# # import pytz
# # from dotenv import load_dotenv
# #
# #
# # def setup_logger(name: str) -> Logger:
# #     """
# #     Настраивает и возвращает логгер с заданным именем, используя часовой пояс UTC+3.
# #
# #     Args:
# #         name: Имя логгера (обычно __name__ модуля).
# #
# #     Returns:
# #         Настроенный объект логгера.
# #     """
# #     # Загружаем переменные окружения из .env
# #     load_dotenv()
# #
# #     # Получаем уровень логирования из .env или устанавливаем INFO по умолчанию
# #     log_level_str = environ.get("LOG_LEVEL", "INFO").upper()
# #     log_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
# #     log_level = log_levels.get(log_level_str, 20)  # INFO по умолчанию
# #
# #     # Создаём логгер
# #     logger = getLogger(name)
# #     logger.setLevel(log_level)
# #
# #     # Проверяем, не добавлены ли уже обработчики, чтобы избежать дублирования
# #     if not logger.handlers:
# #         # Форматтер для логов с часовым поясом UTC+3 (Europe/Moscow)
# #         class MoscowFormatter(Formatter):
# #             def converter(self, timestamp: float) -> time.struct_time:
# #                 """
# #                 Преобразует временную метку в struct_time с учётом часового пояса UTC+3.
# #
# #                 Args:
# #                     timestamp: Временная метка в секундах (Unix timestamp).
# #
# #                 Returns:
# #                     Объект struct_time в часовом поясе Europe/Moscow.
# #                 """
# #                 moscow_tz = pytz.timezone("Europe/Moscow")
# #                 dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
# #                 dt_moscow = dt.astimezone(moscow_tz)
# #                 return dt_moscow.timetuple()
# #
# #         formatter = MoscowFormatter(
# #             "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
# #             datefmt="%Y-%m-%d %H:%M:%S",
# #         )
# #
# #         # Обработчик для консоли
# #         console_handler = StreamHandler()
# #         console_handler.setLevel(log_level)
# #         console_handler.setFormatter(formatter)
# #
# #         # Обработчик для файла
# #         makedirs("logs", exist_ok=True)  # Создаём директорию logs, если не существует
# #         file_handler = FileHandler("logs/app.log", encoding="utf-8")
# #         file_handler.setLevel(log_level)
# #         file_handler.setFormatter(formatter)
# #
# #         # Добавляем обработчики к логгеру
# #         logger.addHandler(console_handler)
# #         logger.addHandler(file_handler)
# #
# #     return logger
# import os
# import time
# import sys
# from datetime import datetime
# from logging import Logger, getLogger, Formatter, StreamHandler
# from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
# from os import makedirs, environ
# from pathlib import Path
# import pytz
# from dotenv import load_dotenv
#
# # Глобальная переменная для отслеживания настроенных логгеров
# _configured_loggers = set()
#
#
# def setup_logger(
#     name: str,
#     log_dir: str = "logs",
#     max_bytes: int = 10 * 1024 * 1024,  # 10MB
#     backup_count: int = 5,
#     use_timed_rotation: bool = False,
#     rotation_interval: str = "midnight",
#     silent_setup: bool = True,  # Тихая настройка по умолчанию
# ) -> Logger:
#     """
#     Настраивает и возвращает логгер с заданным именем, используя часовой пояс UTC+3.
#
#     Args:
#         name: Имя логгера (обычно __name__ модуля).
#         log_dir: Директория для логов (по умолчанию "logs").
#         max_bytes: Максимальный размер файла лога в байтах (по умолчанию 10MB).
#         backup_count: Количество резервных копий логов (по умолчанию 5).
#         use_timed_rotation: Использовать ротацию по времени вместо размера.
#         rotation_interval: Интервал ротации по времени ('midnight', 'H', 'D').
#         silent_setup: Не выводить информацию о настройке логгера.
#
#     Returns:
#         Настроенный объект логгера.
#     """
#     # Загружаем переменные окружения из .env
#     load_dotenv()
#
#     # Глобальная переменная для отслеживания настроенных логгеров
#     global _configured_loggers
#
#     # Получаем уровень логирования из .env или устанавливаем INFO по умолчанию
#     # log_level_str = environ.get("LOG_LEVEL", "INFO").upper()
#     log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
#     log_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
#     log_level = log_levels.get(log_level_str, 20)  # INFO по умолчанию
#
#     # Создаём логгер
#     logger = getLogger(name)
#     logger.setLevel(log_level)
#
#     # Проверяем, не добавлены ли уже обработчики, чтобы избежать дублирования
#     if not logger.handlers:
#         # Форматтер для логов с часовым поясом UTC+3 (Europe/Moscow)
#         class MoscowFormatter(Formatter):
#             def converter(self, timestamp: float) -> time.struct_time:
#                 """
#                 Преобразует временную метку в struct_time с учётом часового пояса UTC+3.
#
#                 Args:
#                     timestamp: Временная метка в секундах (Unix timestamp).
#
#                 Returns:
#                     Объект struct_time в часовом поясе Europe/Moscow.
#                 """
#                 moscow_tz = pytz.timezone("Europe/Moscow")
#                 dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
#                 dt_moscow = dt.astimezone(moscow_tz)
#                 return dt_moscow.timetuple()
#
#             def format(self, record):
#                 """
#                 Расширенное форматирование с добавлением информации о файле и строке.
#                 """
#                 # Добавляем информацию о файле и строке для уровней WARNING и выше
#                 if record.levelno >= 30:  # WARNING и выше
#                     record.location = f"{record.filename}:{record.lineno}"
#                 else:
#                     record.location = ""
#
#                 # Добавляем информацию о функции для ERROR и CRITICAL
#                 if record.levelno >= 40:  # ERROR и CRITICAL
#                     record.func_info = f" in {record.funcName}()"
#                 else:
#                     record.func_info = ""
#
#                 return super().format(record)
#
#         # Форматы для разных уровней логирования
#         detailed_format = "[%(asctime)s] [%(levelname)s] [%(name)s] [%(location)s%(func_info)s] %(message)s"
#         simple_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
#
#         # Консольный форматтер (упрощённый для читаемости)
#         console_formatter = MoscowFormatter(simple_format, datefmt="%Y-%m-%d %H:%M:%S")
#
#         # Файловый форматтер (детальный)
#         file_formatter = MoscowFormatter(detailed_format, datefmt="%Y-%m-%d %H:%M:%S")
#
#         # Обработчик для консоли
#         console_handler = StreamHandler(sys.stdout)
#         console_handler.setLevel(log_level)
#         console_handler.setFormatter(console_formatter)
#
#         # Создаём директорию logs, если не существует
#         log_path = Path(log_dir)
#         log_path.mkdir(exist_ok=True)
#
#         # Выбираем тип ротации
#         log_file_path = log_path / "app.log"
#
#         if use_timed_rotation:
#             # Ротация по времени
#             file_handler = TimedRotatingFileHandler(
#                 log_file_path,
#                 when=rotation_interval,
#                 interval=1,
#                 backupCount=backup_count,
#                 encoding="utf-8",
#                 utc=False,  # Используем местное время
#             )
#             file_handler.suffix = "%Y-%m-%d"  # Формат суффикса для архивных файлов
#         else:
#             # Ротация по размеру
#             file_handler = RotatingFileHandler(
#                 log_file_path,
#                 maxBytes=max_bytes,
#                 backupCount=backup_count,
#                 encoding="utf-8",
#             )
#
#         file_handler.setLevel(log_level)
#         file_handler.setFormatter(file_formatter)
#
#         # Добавляем обработчики к логгеру
#         logger.addHandler(console_handler)
#         logger.addHandler(file_handler)
#
#         # Определяем, нужно ли логировать настройку
#         logger_key = f"{name}_{log_level_str}_{log_dir}"
#         is_first_setup = logger_key not in _configured_loggers
#
#         # Логируем информацию о настройке только если:
#         # 1. Не тихий режим И
#         # 2. (Это главный модуль ИЛИ первая настройка этого логгера)
#         should_log_setup = not silent_setup and (
#             name == "__main__" or "main" in name.lower() or is_first_setup
#         )
#
#         if should_log_setup:
#             logger.info(
#                 f"Logging system initialized for '{name}' (level: {log_level_str})"
#             )
#             if is_first_setup:
#                 logger.info(f"Log directory: {log_path.absolute()}")
#                 if use_timed_rotation:
#                     logger.info(
#                         f"Rotation: {rotation_interval} (keep {backup_count} files)"
#                     )
#                 else:
#                     logger.info(
#                         f"Rotation: {max_bytes / 1024 / 1024:.0f}MB files (keep {backup_count})"
#                     )
#
#             # Помечаем логгер как настроенный
#             _configured_loggers.add(logger_key)
#
#     return logger
#
#
# def get_caller_info():
#     """
#     Вспомогательная функция для получения информации о вызывающем коде.
#     Полезна для ручного добавления контекста в логи.
#
#     Returns:
#         tuple: (filename, line_number, function_name)
#     """
#     import inspect
#
#     frame = inspect.currentframe().f_back.f_back
#     return frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name
#
#
# def setup_application_logging(
#     app_name: str = "Application",
#     log_level: str = None,
#     log_dir: str = "logs",
#     max_bytes: int = 10 * 1024 * 1024,
#     backup_count: int = 5,
#     use_timed_rotation: bool = False,
#     rotation_interval: str = "midnight",
#     verbose: bool = False,  # Подробный вывод настроек
# ) -> Logger:
#     """
#     Централизованная настройка логирования для всего приложения.
#     Выводит минимум информации о настройке.
#
#     Args:
#         app_name: Имя приложения для основного логгера.
#         log_level: Уровень логирования (если None, берется из .env).
#         log_dir: Директория для логов.
#         max_bytes: Максимальный размер файла лога.
#         backup_count: Количество резервных копий.
#         use_timed_rotation: Использовать ротацию по времени.
#         rotation_interval: Интервал ротации по времени.
#         verbose: Показывать подробную информацию о настройке.
#
#     Returns:
#         Основной логгер приложения.
#     """
#     # Принудительно устанавливаем уровень если передан
#     if log_level:
#         environ["LOG_LEVEL"] = log_level.upper()
#
#     # Создаем основной логгер приложения
#     main_logger = setup_logger(
#         app_name,
#         log_dir=log_dir,
#         max_bytes=max_bytes,
#         backup_count=backup_count,
#         use_timed_rotation=use_timed_rotation,
#         rotation_interval=rotation_interval,
#         silent_setup=not verbose,  # Показываем детали только если verbose=True
#     )
#
#     # Простое сообщение о готовности
#     main_logger.info(f"{app_name} started")
#     return main_logger
#
#
# def get_logger(name: str) -> Logger:
#     """
#     Получение логгера для модуля с тихой настройкой.
#
#     Args:
#         name: Имя логгера (обычно __name__ модуля).
#
#     Returns:
#         Настроенный логгер.
#     """
#     return setup_logger(name, silent_setup=True)
#
#
# def init_simple_logging(app_name: str = "App", log_level: str = "INFO") -> Logger:
#     """
#     Максимально простая инициализация логирования без лишнего вывода.
#     Показывает только одно сообщение о старте приложения.
#
#     Args:
#         app_name: Имя приложения.
#         log_level: Уровень логирования.
#
#     Returns:
#         Основной логгер приложения.
#     """
#     if log_level:
#         environ["LOG_LEVEL"] = log_level.upper()
#
#     # Создаем логгер полностью тихо
#     main_logger = setup_logger(app_name, silent_setup=True)
#     main_logger.info(f"{app_name} started")
#
#     return main_logger
#
#
# # Пример использования с контекстным менеджером для логирования исключений
# class LoggerContext:
#     """
#     Контекстный менеджер для автоматического логирования исключений.
#     """
#
#     def __init__(self, logger: Logger, message: str = "Operation failed"):
#         self.logger = logger
#         self.message = message
#
#     def __enter__(self):
#         return self
#
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         if exc_type:
#             self.logger.error(
#                 f"{self.message}: {exc_type.__name__}: {exc_val}", exc_info=True
#             )
#         return False  # Не подавляем исключение
import os
import time
import sys
from datetime import datetime
from logging import Logger, getLogger, Formatter, StreamHandler
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from os import makedirs
from pathlib import Path
import pytz
from dotenv import load_dotenv

# Глобальная переменная для отслеживания настроенных логгеров
_configured_loggers = set()


def setup_logger(
    name: str,
    log_dir: str = "logs",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    use_timed_rotation: bool = False,
    rotation_interval: str = "midnight",
    silent_setup: bool = True,  # Тихая настройка по умолчанию
) -> Logger:
    """
    Настраивает и возвращает логгер с заданным именем, используя часовой пояс UTC+3.

    Args:
        name: Имя логгера (обычно __name__ модуля).
        log_dir: Директория для логов (по умолчанию "logs").
        max_bytes: Максимальный размер файла лога в байтах (по умолчанию 10MB).
        backup_count: Количество резервных копий логов (по умолчанию 5).
        use_timed_rotation: Использовать ротацию по времени вместо размера.
        rotation_interval: Интервал ротации по времени ('midnight', 'H', 'D').
        silent_setup: Не выводить информацию о настройке логгера.

    Returns:
        Logger: Настроенный объект логгера.
    """
    # Загружаем переменные окружения из .env
    load_dotenv()

    # Получаем уровень логирования из .env или устанавливаем INFO по умолчанию
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

    # Проверяем валидность уровня логирования
    if log_level_str not in log_levels:
        default_level = "INFO"
        # Создаём временный логгер для вывода предупреждения
        temp_logger = getLogger(name)
        temp_logger.warning(
            f"Недопустимый уровень логирования '{log_level_str}' в LOG_LEVEL. "
            f"Используется уровень по умолчанию: {default_level}"
        )
        log_level_str = default_level

    log_level = log_levels[log_level_str]

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
                    time.struct_time: Объект struct_time в часовом поясе Europe/Moscow.
                """
                moscow_tz = pytz.timezone("Europe/Moscow")
                dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
                dt_moscow = dt.astimezone(moscow_tz)
                return dt_moscow.timetuple()

            def format(self, record):
                """
                Расширенное форматирование с добавлением информации о файле и строке.
                """
                # Добавляем информацию о файле и строке для уровней WARNING и выше
                if record.levelno >= 30:  # WARNING и выше
                    record.location = f"{record.filename}:{record.lineno}"
                else:
                    record.location = ""
                # Добавляем информацию о функции для ERROR и CRITICAL
                if record.levelno >= 40:  # ERROR и CRITICAL
                    record.func_info = f" in {record.funcName}()"
                else:
                    record.func_info = ""
                return super().format(record)

        # Форматы для разных уровней логирования
        detailed_format = "[%(asctime)s] [%(levelname)s] [%(name)s] [%(location)s%(func_info)s] %(message)s"
        simple_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"

        # Консольный форматтер (упрощённый для читаемости)
        console_formatter = MoscowFormatter(simple_format, datefmt="%Y-%m-%d %H:%M:%S")
        # Файловый форматтер (детальный)
        file_formatter = MoscowFormatter(detailed_format, datefmt="%Y-%m-%d %H:%M:%S")

        # Обработчик для консоли
        console_handler = StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(console_formatter)

        # Создаём директорию logs, если не существует
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True)

        # Выбираем тип ротации
        log_file_path = log_path / "app.log"
        if use_timed_rotation:
            # Ротация по времени
            file_handler = TimedRotatingFileHandler(
                log_file_path,
                when=rotation_interval,
                interval=1,
                backupCount=backup_count,
                encoding="utf-8",
                utc=False,  # Используем местное время
            )
            file_handler.suffix = "%Y-%m-%d"  # Формат суффикса для архивных файлов
        else:
            # Ротация по размеру
            file_handler = RotatingFileHandler(
                log_file_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(file_formatter)

        # Добавляем обработчики к логгеру
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

        # Определяем, нужно ли логировать настройку
        logger_key = f"{name}_{log_level_str}_{log_dir}"
        is_first_setup = logger_key not in _configured_loggers
        # Логируем информацию о настройке только если:
        # 1. Не тихий режим И
        # 2. (Это главный модуль ИЛИ первая настройка этого логгера)
        should_log_setup = not silent_setup and (
            name == "__main__" or "main" in name.lower() or is_first_setup
        )
        if should_log_setup:
            logger.info(
                f"Logging system initialized for '{name}' (level: {log_level_str})"
            )
            if is_first_setup:
                logger.info(f"Log directory: {log_path.absolute()}")
                if use_timed_rotation:
                    logger.info(
                        f"Rotation: {rotation_interval} (keep {backup_count} files)"
                    )
                else:
                    logger.info(
                        f"Rotation: {max_bytes / 1024 / 1024:.0f}MB files (keep {backup_count})"
                    )
            # Помечаем логгер как настроенный
            _configured_loggers.add(logger_key)

    return logger


def get_caller_info():
    """
    Вспомогательная функция для получения информации о вызывающем коде.
    Полезна для ручного добавления контекста в логи.

    Returns:
        tuple: (filename, line_number, function_name)
    """
    import inspect

    frame = inspect.currentframe().f_back.f_back
    return frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name


def setup_application_logging(
    app_name: str = "Application",
    log_level: str = None,
    log_dir: str = "logs",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    use_timed_rotation: bool = False,
    rotation_interval: str = "midnight",
    verbose: bool = False,  # Подробный вывод настроек
) -> Logger:
    """
    Централизованная настройка логирования для всего приложения.
    Выводит минимум информации о настройке.

    Args:
        app_name: Имя приложения для основного логгера.
        log_level: Уровень логирования (если None, берется из .env).
        log_dir: Директория для логов.
        max_bytes: Максимальный размер файла лога.
        backup_count: Количество резервных копий.
        use_timed_rotation: Использовать ротацию по времени.
        rotation_interval: Интервал ротации по времени.
        verbose: Показывать подробную информацию о настройке.

    Returns:
        Logger: Основной логгер приложения.
    """
    # Если передан log_level, устанавливаем его в окружение
    if log_level:
        log_level = log_level.upper()
        log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if log_level not in log_levels:
            temp_logger = getLogger(app_name)
            temp_logger.warning(
                f"Недопустимый уровень логирования '{log_level}'. "
                f"Используется уровень из окружения или INFO"
            )
            log_level = None
        else:
            os.environ["LOG_LEVEL"] = log_level

    # Создаем основной логгер приложения
    main_logger = setup_logger(
        app_name,
        log_dir=log_dir,
        max_bytes=max_bytes,
        backup_count=backup_count,
        use_timed_rotation=use_timed_rotation,
        rotation_interval=rotation_interval,
        silent_setup=not verbose,  # Показываем детали только если verbose=True
    )

    # Простое сообщение о готовности
    main_logger.info(f"{app_name} started")
    return main_logger


def get_logger(name: str) -> Logger:
    """
    Получение логгера для модуля с тихой настройкой.

    Args:
        name: Имя логгера (обычно __name__ модуля).

    Returns:
        Logger: Настроенный логгер.
    """
    return setup_logger(name, silent_setup=True)


def init_simple_logging(app_name: str = "App", log_level: str = None) -> Logger:
    """
    Максимально простая инициализация логирования без лишнего вывода.
    Показывает только одно сообщение о старте приложения.

    Args:
        app_name: Имя приложения.
        log_level: Уровень логирования (если None, берется из .env).

    Returns:
        Logger: Основной логгер приложения.
    """
    # Если передан log_level, устанавливаем его в окружение
    if log_level:
        log_level = log_level.upper()
        log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if log_level not in log_levels:
            temp_logger = getLogger(app_name)
            temp_logger.warning(
                f"Недопустимый уровень логирования '{log_level}'. "
                f"Используется уровень из окружения или INFO"
            )
            log_level = None
        else:
            os.environ["LOG_LEVEL"] = log_level

    # Создаем логгер полностью тихо
    main_logger = setup_logger(app_name, silent_setup=True)
    main_logger.info(f"{app_name} started")
    return main_logger


class LoggerContext:
    """
    Контекстный менеджер для автоматического логирования исключений.
    """

    def __init__(self, logger: Logger, message: str = "Operation failed"):
        self.logger = logger
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.logger.error(
                f"{self.message}: {exc_type.__name__}: {exc_val}", exc_info=True
            )
        return False  # Не подавляем исключение
