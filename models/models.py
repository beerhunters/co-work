import time
from sqlite3 import IntegrityError, OperationalError
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

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)

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
    invited_count = Column(
        Integer, default=0
    )  # Поле для подсчёта приглашённых пользователей
    reg_date = Column(DateTime)
    agreed_to_terms = Column(Boolean, default=False)
    avatar = Column(String, nullable=True)
    referrer_id = Column(
        Integer, ForeignKey("users.telegram_id"), nullable=True
    )  # Поле для реферального ID
    notifications = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    bookings = relationship(
        "Booking",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tickets = relationship(
        "Ticket",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    referrer = relationship(
        "User", remote_side=[telegram_id], backref="invitees"
    )  # Связь для пригласившего пользователя

    def __repr__(self) -> str:
        return f"<User {self.telegram_id} - {self.full_name}>"


def update_invited_count(user_id: Optional[int]) -> None:
    """
    Обновляет количество приглашённых пользователей для пользователя.

    Args:
        user_id: ID пользователя, для которого обновляется invited_count.
    """
    if user_id:
        session = Session()
        try:
            referrer = session.query(User).filter_by(telegram_id=user_id).first()
            if referrer:
                referrer.invited_count = (
                    session.query(User).filter_by(referrer_id=user_id).count()
                )
                session.commit()
                logger.info(
                    f"Обновлён invited_count для пользователя {user_id}: {referrer.invited_count}"
                )
            else:
                logger.warning(
                    f"Пользователь с ID {user_id} не найден для обновления invited_count"
                )
        except Exception as e:
            session.rollback()
            logger.error(
                f"Ошибка при обновлении invited_count для пользователя {user_id}: {str(e)}"
            )
        finally:
            session.close()


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
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
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
    user = relationship("User", back_populates="bookings")
    tariff = relationship("Tariff", backref="bookings")
    promocode = relationship("Promocode", backref="promocodes")
    notifications = relationship(
        "Notification",
        back_populates="booking",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Newsletter(Base):
    __tablename__ = "newsletters"
    id = Column(Integer, primary_key=True)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(MOSCOW_TZ))
    recipient_count = Column(Integer, nullable=False)


class TicketStatus(enum.Enum):
    """Перечисление для статусов заявки."""

    OPEN = "Открыта"
    IN_PROGRESS = "В работе"
    CLOSED = "Закрыта"


class Ticket(Base):
    """Модель заявки в системе Helpdesk."""

    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    description = Column(String, nullable=False)
    photo_id = Column(String, nullable=True)
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    comment = Column(String, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(MOSCOW_TZ), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(MOSCOW_TZ),
        onupdate=lambda: datetime.now(MOSCOW_TZ),
        nullable=False,
    )
    user = relationship("User", back_populates="tickets")
    notifications = relationship(
        "Notification",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Notification(Base):
    """Модель уведомления."""

    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(MOSCOW_TZ), nullable=False
    )
    is_read = Column(Boolean, default=False, nullable=False)
    booking_id = Column(
        Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True
    )
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True
    )
    user = relationship("User", back_populates="notifications")
    booking = relationship("Booking", back_populates="notifications")
    ticket = relationship("Ticket", back_populates="notifications")


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


def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    session = Session()
    user = session.query(User).filter_by(telegram_id=telegram_id).first()
    session.close()
    return user


def check_and_add_user(
    telegram_id: int, username: Optional[str] = None, referrer_id: Optional[int] = None
) -> Tuple[Optional[User], bool]:
    """
    Проверяет, существует ли пользователь в БД, и добавляет его, если не существует.

    Args:
        telegram_id: Telegram ID пользователя.
        username: Имя пользователя в Telegram (опционально).
        referrer_id: ID реферера (опционально).

    Returns:
        Tuple[Optional[User], bool]: Пользователь и флаг завершенности регистрации.
    """
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            is_complete = all([user.full_name, user.phone, user.email])
            logger.debug(
                f"Пользователь {telegram_id} уже существует, завершенность регистрации: {is_complete}, referrer_id: {user.referrer_id}"
            )
            return user, is_complete
        else:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_join_time=datetime.now(MOSCOW_TZ),
                referrer_id=referrer_id,
                invited_count=0,
            )
            session.add(user)
            session.commit()
            logger.info(
                f"Создан новый пользователь {telegram_id} с referrer_id {referrer_id}"
            )
            return user, False
    except Exception as e:
        logger.error(f"Ошибка при проверке/добавлении пользователя {telegram_id}: {e}")
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
    avatar: Optional[str] = None,
    referrer_id: Optional[int] = None,
) -> None:
    """
    Добавление или обновление пользователя в БД и создание уведомления.

    Args:
        telegram_id: Telegram ID пользователя.
        full_name: Полное имя пользователя.
        phone: Номер телефона.
        email: Электронная почта.
        username: Имя пользователя в Telegram.
        reg_date: Дата регистрации.
        agreed_to_terms: Согласие с правилами.
        avatar: Аватар пользователя.
        referrer_id: ID реферера.
    """
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
            if referrer_id is not None:
                user.referrer_id = referrer_id
                logger.debug(
                    f"Обновлён referrer_id для пользователя {telegram_id}: {referrer_id}"
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
                invited_count=0,
                reg_date=reg_date or datetime.now(MOSCOW_TZ),
                agreed_to_terms=(
                    agreed_to_terms if agreed_to_terms is not None else False
                ),
                avatar=avatar,
                referrer_id=referrer_id,
            )
            session.add(user)
            session.flush()

        # Если регистрация завершена и есть referrer_id, увеличиваем invited_count реферера
        if full_name and phone and email and user.referrer_id:
            referrer = (
                session.query(User).filter_by(telegram_id=user.referrer_id).first()
            )
            if referrer:
                referrer.invited_count += 1
                session.add(referrer)
                logger.info(
                    f"Увеличен invited_count для реферера {referrer.telegram_id} "
                    f"до {referrer.invited_count} для пользователя {telegram_id}"
                )
            else:
                logger.warning(
                    f"Реферер с ID {user.referrer_id} не найден для пользователя {telegram_id}"
                )

        if full_name and phone and email:
            notification = Notification(
                user_id=user.id,
                message=f"Новый пользователь: {full_name}",
                created_at=datetime.now(MOSCOW_TZ),
                is_read=False,
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


def format_booking_notification(user, tariff, booking_data):
    """Форматирует красивое уведомление о новой брони для админа"""

    # Эмодзи для разных типов тарифов
    tariff_emojis = {
        "meeting": "🤝",
        "workspace": "💼",
        "event": "🎉",
        "office": "🏢",
        "coworking": "💻",
    }

    # Определяем эмодзи для тарифа
    purpose = booking_data.get("tariff_purpose", "").lower()
    tariff_emoji = tariff_emojis.get(purpose, "📋")

    # Форматируем дату и время
    visit_date = booking_data.get("visit_date")
    visit_time = booking_data.get("visit_time")

    if visit_time:
        datetime_str = (
            f"{visit_date.strftime('%d.%m.%Y')} в {visit_time.strftime('%H:%M')}"
        )
    else:
        datetime_str = f"{visit_date.strftime('%d.%m.%Y')} (весь день)"

    # Информация о скидке
    discount_info = ""
    if booking_data.get("discount", 0) > 0:
        promocode_name = booking_data.get("promocode_name", "Неизвестный")
        discount = booking_data.get("discount", 0)
        discount_info = (
            f"\n💰 <b>Скидка:</b> {discount}% (промокод: <code>{promocode_name}</code>)"
        )

    # Информация о продолжительности
    duration_info = ""
    if booking_data.get("duration"):
        duration_info = f"\n⏱ <b>Длительность:</b> {booking_data['duration']} час(ов)"

    # Основное сообщение
    message = f"""🎯 <b>НОВАЯ БРОНЬ!</b> {tariff_emoji}

👤 <b>Клиент:</b>
├ <b>Имя:</b> {user.full_name or 'Не указано'}
├ <b>Телефон:</b> {user.phone or 'Не указано'}
├ <b>Email:</b> {user.email or 'Не указано'}
└ <b>Telegram:</b> @{user.username or 'не указан'} (ID: <code>{user.telegram_id}</code>)

📋 <b>Детали брони:</b>
├ <b>Тариф:</b> {booking_data.get('tariff_name', 'Неизвестно')}
├ <b>Дата и время:</b> {datetime_str}{duration_info}
└ <b>Сумма:</b> {booking_data.get('amount', 0):.2f} ₽{discount_info}

🔗 <b>Rubitime ID:</b> <code>{booking_data.get('rubitime_id', 'Не создано')}</code>

📊 <b>Статистика клиента:</b>
└ <b>Успешных броней:</b> {user.successful_bookings}

⏰ <i>Время создания: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}</i>"""

    return message.strip()


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
) -> Tuple[Optional[Booking], Optional[str], Optional[Session]]:
    """
    Создаёт запись бронирования и уведомление в базе данных.

    Args:
        telegram_id: Telegram ID пользователя.
        tariff_id: ID тарифа.
        visit_date: Дата визита.
        visit_time: Время визита (для "Переговорной").
        duration: Продолжительность (для "Переговорной").
        promocode_id: ID промокода, если применён.
        amount: Итоговая сумма.
        paid: Флаг оплаты.
        confirmed: Флаг подтверждения.
        payment_id: ID платежа (для платных броней).

    Returns:
        Tuple[Optional[Booking], Optional[str], Optional[Session]]: Объект брони, сообщение для админа, сессия.
    """
    session = Session()
    retries = 3
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

        for attempt in range(retries):
            try:
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

                # Формируем данные для уведомления
                booking_data = {
                    "tariff_name": tariff.name,
                    "tariff_purpose": tariff.purpose.lower(),
                    "visit_date": visit_date,
                    "visit_time": visit_time,
                    "duration": duration,
                    "amount": amount or tariff.price,
                    "discount": 0,
                    "promocode_name": None,
                    "rubitime_id": getattr(booking, "rubitime_id", "Не создано"),
                }
                if promocode_id:
                    promocode = (
                        session.query(Promocode).filter_by(id=promocode_id).first()
                    )
                    if promocode:
                        booking_data["discount"] = promocode.discount
                        booking_data["promocode_name"] = promocode.name

                notification = Notification(
                    user_id=user.id,
                    message=f"Новая бронь от {user.full_name or 'пользователя'}: тариф {tariff.name}, дата {visit_date}"
                    + (
                        f", время {visit_time}, длительность {duration} ч"
                        if tariff.purpose == "Переговорная"
                        else ""
                    ),
                    created_at=datetime.now(MOSCOW_TZ),
                    is_read=False,
                    booking_id=booking.id,
                )
                session.add(notification)
                session.commit()

                admin_message = format_booking_notification(user, tariff, booking_data)
                logger.info(
                    f"Бронь создана: пользователь {telegram_id}, тариф {tariff.name}, дата {visit_date}, ID брони {booking.id}"
                )
                return booking, admin_message, session
            except OperationalError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    logger.warning(
                        f"Попытка {attempt + 1}: база данных заблокирована, повтор через 100 мс"
                    )
                    session.rollback()
                    time.sleep(0.1)
                    continue
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
        return None, "Ошибка при создания брони", None


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


def format_ticket_notification(user, ticket_data):
    """Форматирует красивое уведомление о новом тикете для админа"""

    # Эмодзи для статусов
    status_emojis = {"OPEN": "🟢", "IN_PROGRESS": "🟡", "CLOSED": "🔴"}

    status = ticket_data.get("status", "OPEN")
    status_emoji = status_emojis.get(status, "⚪")

    # Обрезаем описание если оно слишком длинное
    description = ticket_data.get("description", "")
    if len(description) > 200:
        description = description[:200] + "..."

    # Информация о фото
    photo_info = ""
    if ticket_data.get("photo_id"):
        photo_info = "\n📸 <b>Прикреплено фото</b>"

    message = f"""🎫 <b>НОВЫЙ ТИКЕТ!</b> {status_emoji}

👤 <b>От пользователя:</b>
├ <b>Имя:</b> {user.full_name or 'Не указано'}
├ <b>Телефон:</b> {user.phone or 'Не указано'}
├ <b>Email:</b> {user.email or 'Не указано'}
└ <b>Telegram:</b> @{user.username or 'не указан'} (ID: <code>{user.telegram_id}</code>)

📝 <b>Описание проблемы:</b>
{description}{photo_info}

🏷 <b>Тикет ID:</b> <code>#{ticket_data.get('ticket_id', 'Неизвестно')}</code>
📊 <b>Статус:</b> {status}

⏰ <i>Время создания: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}</i>"""

    return message.strip()


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
    retries = 3
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            logger.warning(f"Пользователь с telegram_id {telegram_id} не найден")
            session.close()
            return None, "Пользователь не найден", None

        for attempt in range(retries):
            try:
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
                    is_read=False,
                    ticket_id=ticket.id,
                )
                session.add(notification)
                session.commit()

                # Используем красивый шаблон для админского уведомления
                admin_message = format_ticket_notification(
                    user=user,
                    ticket_data={
                        "description": description,
                        "photo_id": photo_id,
                        "status": status.value,
                        "ticket_id": ticket.id,
                    },
                )

                logger.info(
                    f"Заявка создана: пользователь {telegram_id}, ID заявки {ticket.id}, photo_id={photo_id or 'без фото'}"
                )
                return ticket, admin_message, session

            except OperationalError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    logger.warning(
                        f"Попытка {attempt + 1}: база данных заблокирована, повтор через 100 мс"
                    )
                    session.rollback()
                    time.sleep(0.1)
                    continue
                else:
                    raise

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
