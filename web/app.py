from typing import Optional
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from models.models import init_db, User, Admin
from werkzeug.security import generate_password_hash
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = "your-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/coworking.db"
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}}

db = SQLAlchemy()


def create_app() -> Flask:
    """Инициализация приложения Flask."""
    db.init_app(app)  # Инициализация SQLAlchemy с приложением

    login_manager = LoginManager(app)
    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[Admin]:
        """Загрузка пользователя для Flask-Login."""
        return db.session.get(Admin, int(user_id))

    with app.app_context():
        # Инициализация базы данных
        init_db()
        try:
            # Создание админа, если не существует
            if not db.session.query(Admin).first():
                admin = Admin(
                    login="admin", password=generate_password_hash("admin123")
                )
                db.session.add(admin)
                db.session.commit()
                logger.info("Админ создан")
        except Exception as e:
            logger.error(f"Ошибка при создании админа: {str(e)}")
            db.session.rollback()

    # Импортируем и инициализируем маршруты после создания приложения
    from .routes import init_routes

    init_routes(app)

    logger.info("Веб-приложение запущено")
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5001)
