from sqlite3 import IntegrityError
from typing import Optional, Tuple
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    BigInteger,
    String,
    DateTime,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import pytz
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from utils.logger import setup_logger

logger = setup_logger(__name__)

# logger = logging.getLogger(__name__)
Base = declarative_base()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

# Инициализация базы данных один раз при импорте модуля
engine = create_engine(
    "sqlite:////data/coworking.db", connect_args={"check_same_thread": False}
)
Session = sessionmaker(bind=engine)


class User(Base):
    """Модель пользователя."""

    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    first_join_time = Column(
        DateTime, default=lambda: datetime.now(MOSCOW_TZ), nullable=False
    )
    full_name = Column(String)
    phone = Column(String)
    email = Column(String)
    username = Column(String)
    successful_bookings = Column(Integer, default=0)
    language_code = Column(String, default="ru")
    reg_date = Column(DateTime)


class Admin(Base):
    """Модель администратора."""

    __tablename__ = "admins"
    id = Column(Integer, primary_key=True)
    login = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)


class Notification(Base):
    """Модель уведомления."""

    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(MOSCOW_TZ), nullable=False
    )
    is_read = Column(Integer, default=0, nullable=False)


def init_db() -> None:
    """Инициализация базы данных с WAL-режимом."""
    with engine.connect() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        logger.info("WAL-режим успешно включён")
        Base.metadata.create_all(engine)
        logger.info("Таблицы базы данных созданы")


def create_admin(admin_login: str, admin_password: str) -> None:
    """
    Создает или обновляет администратора в базе данных.

    Args:
        admin_login: Логин администратора.
        admin_password: Пароль администратора.
    """
    session = Session()
    try:
        admin = session.query(Admin).filter_by(login=admin_login).first()
        if not admin:
            hashed_password = generate_password_hash(
                admin_password, method="pbkdf2:sha256"
            )
            admin = Admin(login=admin_login, password=hashed_password)
            session.add(admin)
            session.commit()
            logger.info(f"Создан администратор с логином: {admin_login}")
        else:
            if not check_password_hash(admin.password, admin_password):
                admin.password = generate_password_hash(
                    admin_password, method="pbkdf2:sha256"
                )
                session.commit()
                logger.info(
                    f"Обновлен пароль для администратора с логином: {admin_login}"
                )
            else:
                logger.info(
                    f"Администратор с логином {admin_login} уже существует с корректным паролем"
                )
    except IntegrityError as e:
        session.rollback()
        logger.error(f"Ошибка уникальности при создании администратора: {e}")
        logger.info("Администратор уже существует, пропускаем создание")
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при создании/обновлении администратора: {e}")
        raise
    finally:
        session.close()


def check_and_add_user(
    telegram_id: int, username: Optional[str] = None
) -> Tuple[Optional[User], bool]:
    """
    Проверяет, существует ли пользователь в БД, и добавляет его, если не существует.
    """
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            # Проверяем, заполнены ли все данные
            is_complete = all([user.full_name, user.phone, user.email])
            return user, is_complete
        else:
            # Создаем нового пользователя
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_join_time=datetime.now(MOSCOW_TZ),
            )
            session.add(user)
            session.commit()
            return user, False
    except Exception as e:
        logger.error(f"Ошибка при проверке/добавлении пользователя: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def add_user(
    telegram_id: int,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    username: Optional[str] = None,
    reg_date: Optional[datetime] = None,
) -> None:
    """Добавление или обновление пользователя в БД и создание уведомления."""
    session = Session()

    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            logger.info(f"Обновление пользователя {telegram_id}")
            if full_name is not None:
                user.full_name = full_name
            if phone is not None:
                user.phone = phone
            if email is not None:
                user.email = email
            if username is not None:
                user.username = username
            if reg_date is not None:
                user.reg_date = reg_date
        else:
            logger.info(f"Создание нового пользователя {telegram_id}")
            user = User(
                telegram_id=telegram_id,
                first_join_time=datetime.now(MOSCOW_TZ),
                full_name=full_name,
                phone=phone,
                email=email,
                username=username,
                successful_bookings=0,
                language_code="ru",
                reg_date=reg_date or datetime.now(MOSCOW_TZ),
            )
            session.add(user)
            session.flush()  # Получаем user.id до коммита
        # Создаём уведомление при полной регистрации
        if full_name and phone and email:
            notification = Notification(
                user_id=user.id,
                message=f"Новый пользователь: {full_name}",
                created_at=datetime.now(MOSCOW_TZ),
                is_read=0,
            )
            session.add(notification)
            logger.info(
                f"Уведомление создано для пользователя {user.id}: {notification.message}"
            )
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(
            f"Ошибка добавления/обновления пользователя {telegram_id}: {str(e)}"
        )
        raise
    finally:
        session.close()
