from typing import Optional
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from .routes import init_routes
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = "your-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/coworking.db"
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

from models.models import User, Admin


@login_manager.user_loader
def load_user(user_id: str) -> Optional[Admin]:
    """Загрузка пользователя для Flask-Login."""
    return db.session.get(Admin, int(user_id))


def create_app() -> Flask:
    """Инициализация приложения Flask."""
    with app.app_context():
        db.create_all()
        # Создание админа, если не существует
        if not db.session.query(Admin).first():
            admin = Admin(login="admin", password="admin123")  # Замените пароль
            db.session.add(admin)
            db.session.commit()
        init_routes(app)
    logger.info("Веб-приложение запущено")
    return app
