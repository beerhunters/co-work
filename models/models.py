from typing import Optional
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
from werkzeug.security import generate_password_hash
import pytz
import logging

logger = logging.getLogger(__name__)
Base = declarative_base()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


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
        """Активен ли пользователь."""
        return True

    @property
    def is_authenticated(self) -> bool:
        """Аутентифицирован ли пользователь."""
        return True

    @property
    def is_anonymous(self) -> bool:
        """Является ли пользователь анонимным."""
        return False

    def get_id(self) -> str:
        """Получение идентификатора пользователя."""
        return str(self.id)


def init_db() -> None:
    """Инициализация базы данных с WAL-режимом."""
    engine = create_engine(
        "sqlite:////data/coworking.db", connect_args={"check_same_thread": False}
    )
    with engine.connect() as connection:
        # Настройка WAL-режима
        connection.execute(text("PRAGMA journal_mode=WAL"))
        logger.info("WAL-режим успешно включён")

        # Создание таблиц
        Base.metadata.create_all(engine)
        logger.info("Таблицы базы данных созданы")


def add_user(
    telegram_id: int,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    username: Optional[str] = None,
    reg_date: Optional[datetime] = None,
) -> None:
    """Добавление или обновление пользователя в БД."""
    engine = create_engine(
        "sqlite:////data/coworking.db", connect_args={"check_same_thread": False}
    )
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            # Обновляем существующие поля, если они переданы
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
            # Создаём нового пользователя
            user = User(
                telegram_id=telegram_id,
                first_join_time=datetime.now(MOSCOW_TZ),
                full_name=full_name,
                phone=phone,
                email=email,
                username=username,
                successful_bookings=0,
                language_code="ru",
                reg_date=reg_date,
            )
            session.add(user)
        session.commit()
        logger.info(f"Пользователь {telegram_id} добавлен или обновлён в БД")
    except Exception as e:
        session.rollback()
        logger.error(
            f"Ошибка добавления/обновления пользователя {telegram_id}: {str(e)}"
        )
        raise
    finally:
        session.close()
