import logging
import os
import re
from datetime import datetime

import pytz
from aiogram import Router, Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from dotenv import load_dotenv

from models.models import add_user, check_and_add_user
from utils.logger import setup_logger

logger = setup_logger(__name__)

load_dotenv()

router = Router()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")


class Registration(StatesGroup):
    """Состояния для процесса регистрации."""

    full_name = State()
    phone = State()
    email = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик команды /start."""
    # Проверяем пользователя и полноту его данных
    user, is_complete = check_and_add_user(
        telegram_id=message.from_user.id, username=message.from_user.username
    )
    if is_complete:
        await message.answer(
            f"Добро пожаловать, {user.full_name}! Вы уже зарегистрированы."
        )
    else:
        await message.answer(
            "Добро пожаловать! Введите ваше ФИО для завершения регистрации:"
        )
        await state.set_state(Registration.full_name)


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
    if not re.match(r"^(?:\+?\d{11})$", phone):
        await message.answer(
            "Неверный формат телефона. Используйте +79991112233 или 89991112233. Попробуйте снова:"
        )
        return
    await state.update_data(phone=phone)
    await message.answer("Введите email (например, user@domain.com):")
    await state.set_state(Registration.email)


@router.message(Registration.email)
async def process_email(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обработка ввода email и завершение регистрации."""
    email = message.text.strip()
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        await message.answer("Неверный формат email. Попробуйте снова:")
        return

    data = await state.get_data()
    full_name = data["full_name"]
    # Разделение ФИО на фамилию, имя и отчество
    name_parts = full_name.split()
    last_name = name_parts[0] if len(name_parts) > 0 else "Не указано"
    first_name = name_parts[1] if len(name_parts) > 1 else "Не указано"
    middle_name = name_parts[2] if len(name_parts) > 2 else "Не указано"

    try:
        add_user(
            telegram_id=message.from_user.id,
            full_name=full_name,
            phone=data["phone"],
            email=email,
            username=message.from_user.username,
            reg_date=datetime.now(MOSCOW_TZ),
        )
        await message.answer("Регистрация завершена!")
        logger.info(f"Пользователь {message.from_user.id} успешно зарегистрирован")
        # Отправка уведомления администратору
        if ADMIN_TELEGRAM_ID:
            try:
                notification = (
                    "<b>👤 Новый резидент ✅ ✅</b>\n"
                    "<b>📋 Данные пользователя:</b>\n\n"
                    f"Фамилия: <code>{last_name}</code>\n"
                    f"Имя: <code>{first_name}</code>\n"
                    f"Отчество: <code>{middle_name}</code>\n"
                    f"<b>🎟️ TG: </b>@{message.from_user.username or 'Не указано'}\n"
                    f"<b>☎️ Телефон: </b><code>{data['phone']}</code>\n"
                    f"<b>📨 Email: </b><code>{email}</code>"
                )
                await bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID, text=notification, parse_mode="HTML"
                )
                logger.info(
                    f"Уведомление отправлено администратору {ADMIN_TELEGRAM_ID}"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления администратору: {str(e)}")
    except Exception as e:
        await message.answer("Ошибка при регистрации. Попробуйте позже.")
        logger.error(f"Ошибка регистрации для {message.from_user.id}: {str(e)}")
    finally:
        await state.clear()


def register_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
