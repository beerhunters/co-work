from sqlite3 import IntegrityError
from typing import Optional, Tuple, List
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    BigInteger,
    String,
    DateTime,
    text,
    Boolean,
    Float,
    ForeignKey,
    Date,
    Time,
    select,
    Enum,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session as SQLAlchemySession
from datetime import datetime
import pytz
import enum
from werkzeug.security import generate_password_hash, check_password_hash
from utils.logger import setup_logger

logger = setup_logger(__name__)

Base = declarative_base()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

engine = create_engine(
    "sqlite:////data/coworking.db", connect_args={"check_same_thread": False}
)
Session = sessionmaker(bind=engine)


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
    agreed_to_terms = Column(Boolean, default=False)
    avatar = Column(String, nullable=True)  # Путь к файлу аватара
    # tickets = relationship("Ticket", back_populates="user")  # Связь с тикетами


class Tariff(Base):
    """Модель тарифа."""

    __tablename__ = "tariffs"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, index=True)
    description = Column(String(255), default="Описание тарифа", nullable=False)
    price = Column(Float, nullable=False)
    purpose = Column(String(50), nullable=True)
    service_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, index=True)


class Promocode(Base):
    """Модель промокода."""

    __tablename__ = "promocodes"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    discount = Column(Integer, nullable=False)
    usage_quantity = Column(Integer, default=0)
    expiration_date = Column(DateTime(timezone=True), nullable=True, index=True)
    is_active = Column(Boolean, default=False, index=True)


class Booking(Base):
    """Модель бронирования."""

    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tariff_id = Column(Integer, ForeignKey("tariffs.id"), nullable=False)
    visit_date = Column(Date, nullable=False)
    visit_time = Column(Time, nullable=True)
    duration = Column(Integer, nullable=True)
    promocode_id = Column(Integer, ForeignKey("promocodes.id"), nullable=True)
    amount = Column(Float, nullable=False)
    payment_id = Column(String(100), nullable=True)
    paid = Column(Boolean, default=False)
    rubitime_id = Column(String(100), nullable=True)
    confirmed = Column(Boolean, default=False)
    user = relationship("User", backref="bookings")
    tariff = relationship("Tariff", backref="bookings")
    promocode = relationship("Promocode", backref="promocodes")


class Newsletter(Base):
    __tablename__ = "newsletters"
    id = Column(Integer, primary_key=True)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now(MOSCOW_TZ))
    recipient_count = Column(Integer, nullable=False)


class Notification(Base):
    """Модель уведомления."""

    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(MOSCOW_TZ), nullable=False
    )
    is_read = Column(Integer, default=0, nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    user = relationship("User", backref="notifications")
    booking = relationship("Booking", backref="notifications")
    ticket = relationship("Ticket", backref="notifications")


class TicketStatus(enum.Enum):
    """Перечисление для статусов заявки"""

    OPEN = "Открыта"
    IN_PROGRESS = "В работе"
    CLOSED = "Закрыта"


class Ticket(Base):
    """Модель заявки в системе Helpdesk"""

    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(String, nullable=False)
    photo_id = Column(String, nullable=True)  # ID фотографии в Telegram
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    comment = Column(String, nullable=True)  # Комментарий администратора
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", backref="users")  # Связь с таблицей пользователей

    def __repr__(self):
        return f"<Ticket(id={self.id}, user_id={self.user_id}, status={self.status})>"


def init_db() -> None:
    """Инициализация базы данных с WAL-режимом."""
    with engine.connect() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        logger.info("WAL-режим успешно включён")
        Base.metadata.create_all(engine)
        logger.info("Таблицы базы данных созданы")


def create_admin(admin_login: str, admin_password: str) -> None:
    """Создает или обновляет администратора в базе данных."""
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


def get_user_by_telegram_id(telegram_id) -> Optional[User]:
    session = Session()
    user = session.query(User).filter_by(telegram_id=telegram_id).first()
    session.close()
    return user


def check_and_add_user(
    telegram_id: int, username: Optional[str] = None
) -> Tuple[Optional[User], bool]:
    """Проверяет, существует ли пользователь в БД, и добавляет его, если не существует."""
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            is_complete = all([user.full_name, user.phone, user.email])
            return user, is_complete
        else:
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
    agreed_to_terms: Optional[bool] = None,
    avatar: Optional[str] = None,  # Добавляем параметр avatar
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
            if agreed_to_terms is not None:
                user.agreed_to_terms = agreed_to_terms
            if avatar is not None:
                user.avatar = avatar
                logger.debug(
                    f"Обновлён аватар для пользователя {telegram_id}: {avatar}"
                )
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
                agreed_to_terms=(
                    agreed_to_terms if agreed_to_terms is not None else False
                ),
                avatar=avatar,
            )
            session.add(user)
            session.flush()
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


def get_active_tariffs() -> List[Tariff]:
    """Возвращает список активных тарифов из базы данных."""
    session = Session()
    try:
        tariffs = session.query(Tariff).filter_by(is_active=True).all()
        logger.info(f"Получено {len(tariffs)} активных тарифов")
        return tariffs
    except Exception as e:
        logger.error(f"Ошибка при получении активных тарифов: {str(e)}")
        raise
    finally:
        session.close()


def create_booking(
    telegram_id: int,
    tariff_id: int,
    visit_date: datetime.date,
    visit_time: Optional[datetime.time] = None,
    duration: Optional[int] = None,
    promocode_id: Optional[int] = None,
    amount: Optional[float] = None,
    paid: Optional[bool] = False,
    confirmed: Optional[bool] = False,
    payment_id: Optional[str] = None,
) -> Tuple[Optional[Booking], Optional[str], Optional[SQLAlchemySession]]:
    """Создаёт запись бронирования и уведомление в базе данных."""
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            logger.warning(f"Пользователь с telegram_id {telegram_id} не найден")
            session.close()
            return None, "Пользователь не найден", None
        tariff = session.query(Tariff).filter_by(id=tariff_id, is_active=True).first()
        if not tariff:
            logger.warning(f"Тариф с ID {tariff_id} не найден или не активен")
            session.close()
            return None, "Тариф не найден", None
        booking = Booking(
            user_id=user.id,
            tariff_id=tariff.id,
            visit_date=visit_date,
            visit_time=visit_time,
            duration=duration,
            promocode_id=promocode_id,
            amount=amount or tariff.price,
            paid=paid,
            confirmed=confirmed,
            payment_id=payment_id,
        )
        session.add(booking)
        session.flush()
        notification = Notification(
            user_id=user.id,
            message=f"Новая бронь от {user.full_name or 'пользователя'}: тариф {tariff.name}, дата {visit_date}"
            + (
                f", время {visit_time}, длительность {duration} ч"
                if tariff.purpose == "Переговорная"
                else ""
            ),
            created_at=datetime.now(MOSCOW_TZ),
            is_read=0,
            booking_id=booking.id,
        )
        session.add(notification)
        session.commit()
        admin_message = (
            f"Новая бронь!\n"
            f"Пользователь: {user.full_name or 'Не указано'} (ID: {telegram_id})\n"
            f"Тариф: {tariff.name} ({tariff.price} ₽)\n"
            f"Дата: {visit_date}"
            + (
                f"\nВремя: {visit_time}\nПродолжительность: {duration} ч"
                if tariff.purpose == "Переговорная"
                else ""
            )
        )
        logger.info(
            f"Бронь создана: пользователь {telegram_id}, тариф {tariff.name}, дата {visit_date}, ID брони {booking.id}"
        )
        return booking, admin_message, session
    except IntegrityError as e:
        session.rollback()
        logger.error(
            f"Ошибка уникальности при создании брони для пользователя {telegram_id}: {str(e)}"
        )
        session.close()
        return None, "Ошибка при создании брони", None
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка создания брони для пользователя {telegram_id}: {str(e)}")
        session.close()
        return None, "Ошибка при создании брони", None


def get_promocode_by_name(promocode_name: str) -> Optional[Promocode]:
    session = Session()
    promocode = (
        session.execute(
            select(Promocode).where(
                Promocode.name == promocode_name, Promocode.is_active == True
            )
        )
    ).scalar_one_or_none()
    return promocode


def create_ticket(
    telegram_id: int,
    description: str,
    photo_id: Optional[str] = None,
    status: TicketStatus = TicketStatus.OPEN,
) -> Tuple[Optional[Ticket], Optional[str], Optional[SQLAlchemySession]]:
    """
    Создаёт запись заявки и уведомление в базе данных.

    Args:
        telegram_id: Telegram ID пользователя.
        description: Описание заявки.
        photo_id: ID фотографии в Telegram (если есть).
        status: Статус заявки (по умолчанию OPEN).

    Returns:
        Tuple[Optional[Ticket], Optional[str], Optional[SQLAlchemySession]]:
            - Объект заявки (или None при ошибке).
            - Сообщение для администратора (или сообщение об ошибке).
            - Открытая сессия SQLAlchemy (или None, если сессия закрыта).
    """
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            logger.warning(f"Пользователь с telegram_id {telegram_id} не найден")
            session.close()
            return None, "Пользователь не найден", None

        ticket = Ticket(
            user_id=user.id,
            description=description,
            photo_id=photo_id,
            status=status,
            created_at=datetime.now(MOSCOW_TZ),
            updated_at=datetime.now(MOSCOW_TZ),
        )
        session.add(ticket)
        session.flush()

        notification = Notification(
            user_id=user.id,
            message=f"Новая заявка #{ticket.id} от {user.full_name or 'пользователя'}: {description[:50]}{'...' if len(description) > 50 else ''}",
            created_at=datetime.now(MOSCOW_TZ),
            is_read=0,
            ticket_id=ticket.id,  # Указываем ticket_id
        )
        session.add(notification)
        session.commit()

        admin_message = (
            f"Новая заявка #{ticket.id}!\n"
            f"Пользователь: {user.full_name or 'Не указано'} (ID: {telegram_id})\n"
            f"Описание: {description}\n"
            f"Статус: {ticket.status.value}"
            + (f"\nФото: {'Есть' if photo_id else 'Отсутствует'}" if photo_id else "")
        )
        logger.info(
            f"Заявка создана: пользователь {telegram_id}, ID заявки {ticket.id}, photo_id={photo_id or 'без фото'}"
        )
        return ticket, admin_message, session
    except IntegrityError as e:
        session.rollback()
        logger.error(
            f"Ошибка уникальности при создании заявки для пользователя {telegram_id}: {str(e)}"
        )
        session.close()
        return None, "Ошибка при создании заявки", None
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка создания заявки для пользователя {telegram_id}: {str(e)}")
        session.close()
        return None, "Ошибка при создании заявки", None
