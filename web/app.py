import os
from typing import Optional
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import logging
from models.models import Admin
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

db = SQLAlchemy()
login_manager = LoginManager()


def create_app() -> Flask:
    """Создание и конфигурация Flask-приложения."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = "your-secret-key"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/coworking.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)

    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[Admin]:
        """Загрузка пользователя для Flask-Login."""
        return db.session.get(Admin, int(user_id))

    # Создание таблиц и добавление тестового админа
    with app.app_context():
        db.create_all()
        admin = db.session.query(Admin).filter_by(login="admin").first()
        if not admin:
            from werkzeug.security import generate_password_hash

            admin = (
                Admin(
                    login=os.getenv("ADMIN_LOGIN"),
                    password=generate_password_hash(os.getenv("ADMIN_PASSWORD")),
                ),
            )
            db.session.add(admin)
            db.session.commit()
            logger.info("Тестовый администратор создан")

    from .routes import init_routes

    init_routes(app)

    return app


# Создаём приложение на уровне модуля
app = create_app()
