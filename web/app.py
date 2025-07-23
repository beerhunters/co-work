import logging
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from typing import Optional
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Конфигурация Flask
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "your-secret-key-change-this")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///data/bot.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Инициализация расширений
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Пожалуйста, войдите для доступа к этой странице."
    login_manager.login_message_category = "info"

    with app.app_context():
        # Импортируем модели
        from models.models import Admin, init_db

        # Инициализируем базу данных
        init_db()

        # Создаем администратора по умолчанию
        admin_login = os.getenv("ADMIN_LOGIN", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

        try:
            admin = db.session.query(Admin).filter_by(login=admin_login).first()
            if not admin:
                # Хешируем пароль
                hashed_password = generate_password_hash(admin_password)
                admin = Admin(login=admin_login, password=hashed_password)
                db.session.add(admin)
                db.session.commit()
                logger.info(f"Создан администратор: {admin_login}")
            else:
                # Обновляем пароль существующего админа (на случай изменения в .env)
                admin.password = generate_password_hash(admin_password)
                db.session.commit()
                logger.info(f"Обновлен пароль для администратора: {admin_login}")
        except Exception as e:
            logger.error(f"Ошибка при создании/обновлении администратора: {e}")
            db.session.rollback()

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional["Admin"]:
        from models.models import Admin

        try:
            return db.session.get(Admin, int(user_id))
        except (ValueError, TypeError):
            return None

    # Регистрируем маршруты
    from .routes import init_routes

    init_routes(app)

    return app


app = create_app()
