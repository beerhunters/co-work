from typing import Any, Optional
from aiogram import Router, F, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import re
from models.models import User, add_user
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging

router = Router()
logger = logging.getLogger(__name__)


class Registration(StatesGroup):
    """Состояния для процесса регистрации."""

    full_name = State()
    phone = State()
    email = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик команды /start."""
    from models.models import init_db

    init_db()  # Инициализация базы данных
    logger.info(f"Пользователь {message.from_user.id} начал взаимодействие")

    # Проверка существования пользователя
    engine = create_engine(
        "sqlite:////data/coworking.db", connect_args={"check_same_thread": False}
    )
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
        if user:
            # Проверяем, есть ли недостающие данные
            if not all([user.full_name, user.phone, user.email]):
                await message.answer(
                    "Вы уже зарегистрированы, но некоторые данные отсутствуют. Введите ваше ФИО:"
                )
                await state.set_state(Registration.full_name)
                return
            else:
                await message.answer(
                    f"Добро пожаловать, {user.full_name}! Вы уже зарегистрированы."
                )
                return
        else:
            # Создаём нового пользователя с telegram_id, first_join_time, username
            add_user(
                telegram_id=message.from_user.id, username=message.from_user.username
            )
            await message.answer(
                "Добро пожаловать! Введите ваше ФИО для завершения регистрации:"
            )
            await state.set_state(Registration.full_name)
    finally:
        session.close()


@router.message(Registration.full_name)
async def process_full_name(message: Message, state: FSMContext) -> None:
    """Обработка ввода ФИО."""
    full_name = message.text.strip()
    if not full_name:
        await message.answer("ФИО не может быть пустым. Попробуйте снова:")
        return
    await state.update_data(full_name=full_name)
    await message.answer("Введите номер телефона (+79991112233 или 89991112233):")
    await state.set_state(Registration.phone)


@router.message(Registration.phone)
async def process_phone(message: Message, state: FSMContext) -> None:
    """Обработка ввода номера телефона."""
    phone = message.text.strip()
    if not re.match(r"^\+?8?\d{10}$", phone):
        await message.answer(
            "Неверный формат телефона. Используйте +79991112233 или 89991112233. Попробуйте снова:"
        )
        return
    await state.update_data(phone=phone)
    await message.answer("Введите email (например, user@domain.com):")
    await state.set_state(Registration.email)


@router.message(Registration.email)
async def process_email(message: Message, state: FSMContext) -> None:
    """Обработка ввода email и завершение регистрации."""
    email = message.text.strip()
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        await message.answer("Неверный формат email. Попробуйте снова:")
        return

    data = await state.get_data()
    try:
        add_user(
            telegram_id=message.from_user.id,
            full_name=data["full_name"],
            phone=data["phone"],
            email=email,
            username=message.from_user.username,
            reg_date=datetime.utcnow(),  # Устанавливаем reg_date при завершении регистрации
        )
        await message.answer("Регистрация завершена!")
        logger.info(f"Пользователь {message.from_user.id} успешно зарегистрирован")
    except Exception as e:
        await message.answer("Ошибка при регистрации. Попробуйте позже.")
        logger.error(f"Ошибка регистрации для {message.from_user.id}: {str(e)}")
    finally:
        await state.clear()


def register_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
