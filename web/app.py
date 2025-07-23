from typing import Optional
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import logging
import os
from werkzeug.security import generate_password_hash
from models.models import Admin, init_db
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)
db = SQLAlchemy()
login_manager = LoginManager()


def create_app() -> Flask:
    """Создает и настраивает экземпляр Flask-приложения."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/coworking.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "your-secret-key")

    # Инициализация базы данных
    db.init_app(app)
    with app.app_context():
        init_db()  # Создаем таблицы
        # Проверяем и создаем администратора
        admin_login = os.getenv("ADMIN_LOGIN", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        try:
            admin = db.session.query(Admin).filter_by(login=admin_login).first()
            if not admin:
                admin = Admin(
                    login=admin_login, password=generate_password_hash(admin_password)
                )
                db.session.add(admin)
                db.session.commit()
                logger.info(f"Создан администратор с логином '{admin_login}'")
            else:
                logger.info(f"Администратор с логином '{admin_login}' уже существует")
        except IntegrityError:
            db.session.rollback()
            logger.warning(
                f"Конфликт: администратор с логином '{admin_login}' уже существует"
            )
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при создании администратора: {e}")
            raise

    login_manager.init_app(app)
    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[Admin]:
        """Загружает пользователя для Flask-Login."""
        return db.session.query(Admin).filter_by(login=user_id).first()

    from .routes import init_routes

    init_routes(app)

    return app


app = create_app()
