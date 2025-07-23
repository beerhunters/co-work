from typing import Optional
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from werkzeug.security import generate_password_hash, check_password_hash
import logging
import os
from sqlalchemy.exc import IntegrityError, OperationalError
from dotenv import load_dotenv
import time

logger = logging.getLogger(__name__)
db = SQLAlchemy()
login_manager = LoginManager()


def create_app() -> Flask:
    """
    Создает и конфигурирует приложение Flask.

    Returns:
        Flask: Настроенное приложение Flask.
    """
    load_dotenv()  # Загружаем переменные из .env

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/coworking.db"
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "default-secret-key")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"

    with app.app_context():
        from models.models import Admin

        # Проверяем, что переменные окружения заданы
        admin_login = os.getenv("ADMIN_LOGIN")
        admin_password = os.getenv("ADMIN_PASSWORD")

        if not admin_login or not admin_password:
            logger.error("ADMIN_LOGIN или ADMIN_PASSWORD не заданы в .env")
            raise ValueError("ADMIN_LOGIN и ADMIN_PASSWORD должны быть заданы в .env")

        # Создаем таблицы перед любыми запросами
        try:
            db.create_all()
            logger.info("Таблицы базы данных созданы в веб-приложении")
        except Exception as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

        # Проверяем и создаем/обновляем администратора
        max_retries = 5
        retry_delay = 1  # секунды
        for attempt in range(max_retries):
            try:
                admin = db.session.query(Admin).filter_by(login=admin_login).first()
                if not admin:
                    # Создаем нового администратора
                    hashed_password = generate_password_hash(
                        admin_password, method="pbkdf2:sha256"
                    )
                    admin = Admin(login=admin_login, password=hashed_password)
                    db.session.add(admin)
                    db.session.commit()
                    logger.info(f"Создан администратор с логином: {admin_login}")
                else:
                    # Проверяем и обновляем пароль, если он отличается
                    if not check_password_hash(admin.password, admin_password):
                        admin.password = generate_password_hash(
                            admin_password, method="pbkdf2:sha256"
                        )
                        db.session.commit()
                        logger.info(
                            f"Обновлен пароль для администратора с логином: {admin_login}"
                        )
                    else:
                        logger.info(
                            f"Администратор с логином {admin_login} уже существует с корректным паролем"
                        )
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
            except IntegrityError as e:
                logger.error(f"Ошибка уникальности при создании администратора: {e}")
                db.session.rollback()
                logger.info("Администратор уже существует, пропускаем создание")
                break
            except Exception as e:
                logger.error(f"Неожиданная ошибка при инициализации: {e}")
                raise

    from .routes import init_routes

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
