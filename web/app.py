from typing import Optional
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import logging
import os
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv
import time
from utils.logger import setup_logger

logger = setup_logger(__name__)
db = SQLAlchemy()
login_manager = LoginManager()


def create_app() -> Flask:
    """
    Создает и конфигурирует приложение Flask.

    Returns:
        Flask: Настроенное приложение Flask.
    """
    load_dotenv()  # Загружаем переменные из .env
    # logging.basicConfig(level=logging.INFO)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/coworking.db"
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "default-secret-key")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Отключаем стандартное логирование Flask
    logging.getLogger("werkzeug").handlers.clear()
    logging.getLogger("werkzeug").setLevel(logging.CRITICAL)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"

    with app.app_context():
        from models.models import Admin

        # Проверяем, что переменные окружения заданы
        admin_login = os.getenv("ADMIN_LOGIN", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

        if not admin_login or not admin_password:
            logger.error("ADMIN_LOGIN или ADMIN_PASSWORD не заданы в .env")
            raise ValueError("ADMIN_LOGIN и ADMIN_PASSWORD должны быть заданы в .env")

        # Проверяем наличие администратора с повторными попытками
        max_retries = 10
        retry_delay = 1  # секунды
        for attempt in range(max_retries):
            try:
                admin = db.session.query(Admin).filter_by(login=admin_login).first()
                if not admin:
                    logger.warning(
                        f"Администратор с логином {admin_login} не найден в базе данных на попытке {attempt + 1}/{max_retries}"
                    )
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Администратор с логином {admin_login} не создан ботом после {max_retries} попыток"
                        )
                        raise ValueError(
                            f"Администратор с логином {admin_login} должен быть создан ботом"
                        )
                    time.sleep(retry_delay)
                    continue
                break  # Успешно, выходим из цикла
            except OperationalError as e:
                if "no such table" in str(e):
                    logger.warning(
                        f"Таблицы еще не созданы, попытка {attempt + 1}/{max_retries}. Ждем {retry_delay} сек."
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Ошибка базы данных при инициализации: {e}")
                    raise
            except Exception as e:
                logger.error(f"Неожиданная ошибка при инициализации: {e}")
                raise

    from web.routes import init_routes

    init_routes(app)

    return app


@login_manager.user_loader
def load_user(user_id: str) -> Optional["Admin"]:
    """
    Загружает администратора по его ID для Flask-Login.

    Args:
        user_id: ID администратора в виде строки.

    Returns:
        Admin or None: Объект администратора или None, если не найден.
    """
    from models.models import Admin

    return db.session.get(Admin, int(user_id))


app = create_app()
