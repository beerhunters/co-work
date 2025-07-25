import os
import re
from datetime import datetime

import pytz
from aiogram import Router, Bot, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from utils.logger import setup_logger

logger = setup_logger(__name__)

load_dotenv()

router = Router()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")


def create_user_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для начала регистрации.
    """
    logger.debug("Создание инлайн-клавиатуры для пользователя")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📍 Забронировать", callback_data="booking")],
            [InlineKeyboardButton(text="❔ Информация", callback_data="info")],
        ]
    )
    return keyboard


def create_back_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для начала регистрации.
    """
    logger.debug("Создание инлайн-клавиатуры для возврата")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ]
    )
    return keyboard


class Booking(StatesGroup):
    """Состояния для процесса регистрации."""

    agreement = State()
    full_name = State()
    phone = State()
    email = State()


@router.callback_query(F.data == "booking")
async def info(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.message.delete()
    await callback_query.message.answer(
        f"Заглушка",
        reply_markup=create_user_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()


def register_book_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
