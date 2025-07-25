import os
from datetime import datetime
import pytz
from aiogram import Router, Bot, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv

from models.models import get_active_tariffs, create_booking
from utils.logger import setup_logger

logger = setup_logger(__name__)
load_dotenv()
router = Router()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")


class Booking(StatesGroup):
    """Состояния для процесса бронирования."""

    SELECT_TARIFF = State()
    ENTER_DATE = State()
    ENTER_TIME = State()
    ENTER_DURATION = State()


def create_user_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для главного меню.
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
    Создаёт инлайн-клавиатуру для возврата в главное меню.
    """
    logger.debug("Создание инлайн-клавиатуры для возврата")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ]
    )
    return keyboard


def create_tariff_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру с активными тарифами.
    """
    try:
        tariffs = get_active_tariffs()
        buttons = [
            [
                InlineKeyboardButton(
                    text=f"{tariff.name} ({tariff.price} ₽)",
                    callback_data=f"tariff_{tariff.id}",
                )
            ]
            for tariff in tariffs
        ]
        buttons.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        logger.debug("Создана клавиатура с тарифами")
        return keyboard
    except Exception as e:
        logger.error(f"Ошибка при создании клавиатуры тарифов: {str(e)}")
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
            ]
        )


@router.callback_query(F.data == "booking")
async def start_booking(
    callback_query: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    """
    Обработчик нажатия кнопки 'Забронировать'. Показывает активные тарифы.

    Args:
        callback_query: Callback-запрос от кнопки.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
    """
    tariffs = get_active_tariffs()
    if not tariffs:
        await callback_query.message.answer(
            "Нет доступных тарифов для бронирования.",
            reply_markup=create_back_keyboard(),
        )
        logger.info(
            f"Пользователь {callback_query.from_user.id} попытался забронировать, но нет активных тарифов"
        )
        await callback_query.message.delete()
        await callback_query.answer()
        return

    await state.set_state(Booking.SELECT_TARIFF)
    await callback_query.message.answer(
        "Выберите тариф:", reply_markup=create_tariff_keyboard()
    )
    logger.info(
        f"Пользователь {callback_query.from_user.id} начал процесс бронирования"
    )
    await callback_query.message.delete()
    await callback_query.answer()


@router.callback_query(Booking.SELECT_TARIFF, F.data.startswith("tariff_"))
async def process_tariff_selection(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка выбора тарифа. Запрашивает дату или дату и время.

    Args:
        callback_query: Callback-запрос с выбранным тарифом.
        state: Контекст состояния FSM.
    """
    if callback_query.data == "cancel":
        await state.clear()
        await callback_query.message.answer(
            "Бронирование отменено.", reply_markup=create_user_keyboard()
        )
        logger.info(f"Пользователь {callback_query.from_user.id} отменил бронирование")
        await callback_query.message.delete()
        await callback_query.answer()
        return

    tariff_id = int(callback_query.data.split("_")[1])
    tariffs = get_active_tariffs()
    tariff = next((t for t in tariffs if t.id == tariff_id), None)
    if not tariff:
        await callback_query.message.answer(
            "Тариф не найден. Попробуйте снова.", reply_markup=create_tariff_keyboard()
        )
        logger.warning(
            f"Пользователь {callback_query.from_user.id} выбрал несуществующий тариф: {tariff_id}"
        )
        await callback_query.message.delete()
        await callback_query.answer()
        return

    await state.update_data(tariff_id=tariff.id)
    await state.set_state(Booking.ENTER_DATE)
    await callback_query.message.answer(
        f"Вы выбрали тариф: {tariff.name}\nВведите дату визита (гггг-мм-дд, например, 2025-07-25):",
        reply_markup=create_back_keyboard(),
    )
    logger.info(
        f"Пользователь {callback_query.from_user.id} выбрал тариф {tariff.name}"
    )
    await callback_query.message.delete()
    await callback_query.answer()


@router.message(Booking.ENTER_DATE)
async def process_date(message: Message, state: FSMContext) -> None:
    """
    Обработка введённой даты. Проверяет формат и запрашивает время для 'Переговорной'.

    Args:
        message: Входящее сообщение с датой.
        state: Контекст состояния FSM.
    """
    try:
        visit_date = datetime.strptime(message.text, "%Y-%m-%d").date()
        if visit_date < datetime.now(MOSCOW_TZ).date():
            await message.answer(
                "Дата не может быть в прошлом. Введите снова:",
                reply_markup=create_back_keyboard(),
            )
            logger.warning(
                f"Пользователь {message.from_user.id} ввёл прошедшую дату: {message.text}"
            )
            return
    except ValueError:
        await message.answer(
            "Неверный формат даты. Введите в формате гггг-мм-дд (например, 2025-07-25):",
            reply_markup=create_back_keyboard(),
        )
        logger.warning(
            f"Пользователь {message.from_user.id} ввёл неверный формат даты: {message.text}"
        )
        return

    data = await state.get_data()
    tariffs = get_active_tariffs()
    tariff = next((t for t in tariffs if t.id == data["tariff_id"]), None)
    if not tariff:
        await message.answer(
            "Тариф не найден. Попробуйте снова.", reply_markup=create_user_keyboard()
        )
        logger.warning(f"Тариф {data['tariff_id']} не найден при обработке даты")
        await state.clear()
        return

    await state.update_data(visit_date=visit_date)
    if tariff.purpose == "Переговорная":
        await state.set_state(Booking.ENTER_TIME)
        await message.answer(
            "Введите время визита (чч:мм, например, 14:30):",
            reply_markup=create_back_keyboard(),
        )
        logger.info(
            f"Пользователь {message.from_user.id} ввёл дату {visit_date} для тарифа {tariff.name}"
        )
    else:
        # Для "Опенспейс" создаём бронирование
        booking, admin_message, session = create_booking(
            telegram_id=message.from_user.id, tariff_id=tariff.id, visit_date=visit_date
        )
        if booking:
            try:
                await message.bot.send_message(ADMIN_TELEGRAM_ID, admin_message)
                logger.info(
                    f"Отправлено сообщение администратору о брони: {booking.id}"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения администратору: {str(e)}")
            finally:
                if session:
                    session.close()
            await message.answer(
                f"Бронь создана!\n"
                f"Тариф: {tariff.name}\n"
                f"Дата: {visit_date}\n"
                f"Бронь подтверждена.",
                reply_markup=create_user_keyboard(),
            )
            logger.info(
                f"Пользователь {message.from_user.id} завершил бронирование Опенспейс: {visit_date}"
            )
        else:
            if session:
                session.close()
            await message.answer(admin_message, reply_markup=create_user_keyboard())
            logger.warning(
                f"Не удалось создать бронь для пользователя {message.from_user.id}"
            )
        await state.clear()


@router.message(Booking.ENTER_TIME)
async def process_time(message: Message, state: FSMContext) -> None:
    """
    Обработка введённого времени для 'Переговорной'. Запрашивает продолжительность.

    Args:
        message: Входящее сообщение с временем.
        state: Контекст состояния FSM.
    """
    try:
        visit_time = datetime.strptime(message.text, "%H:%M").time()
    except ValueError:
        await message.answer(
            "Неверный формат времени. Введите в формате чч:мм (например, 14:30):",
            reply_markup=create_back_keyboard(),
        )
        logger.warning(
            f"Пользователь {message.from_user.id} ввёл неверный формат времени: {message.text}"
        )
        return

    await state.update_data(visit_time=visit_time)
    await state.set_state(Booking.ENTER_DURATION)
    await message.answer(
        "Введите продолжительность бронирования в часах (например, 2):",
        reply_markup=create_back_keyboard(),
    )
    logger.info(f"Пользователь {message.from_user.id} ввёл время {visit_time}")


@router.message(Booking.ENTER_DURATION)
async def process_duration(message: Message, state: FSMContext) -> None:
    """
    Обработка введённой продолжительности. Создаёт бронирование для 'Переговорной'.

    Args:
        message: Входящее сообщение с продолжительностью.
        state: Контекст состояния FSM.
    """
    try:
        duration = int(message.text)
        if duration <= 0:
            await message.answer(
                "Продолжительность должна быть больше 0. Введите снова:",
                reply_markup=create_back_keyboard(),
            )
            logger.warning(
                f"Пользователь {message.from_user.id} ввёл некорректную продолжительность: {message.text}"
            )
            return
    except ValueError:
        await message.answer(
            "Введите целое число часов (например, 2):",
            reply_markup=create_back_keyboard(),
        )
        logger.warning(
            f"Пользователь {message.from_user.id} ввёл неверный формат продолжительности: {message.text}"
        )
        return

    data = await state.get_data()
    tariffs = get_active_tariffs()
    tariff = next((t for t in tariffs if t.id == data["tariff_id"]), None)
    if not tariff:
        await message.answer(
            "Тариф не найден. Попробуйте снова.", reply_markup=create_user_keyboard()
        )
        logger.warning(
            f"Тариф {data['tariff_id']} не найден при обработке продолжительности"
        )
        await state.clear()
        return

    booking, admin_message, session = create_booking(
        telegram_id=message.from_user.id,
        tariff_id=tariff.id,
        visit_date=data["visit_date"],
        visit_time=data["visit_time"],
        duration=duration,
    )
    if booking:
        try:
            await message.bot.send_message(ADMIN_TELEGRAM_ID, admin_message)
            logger.info(f"Отправлено сообщение администратору о брони: {booking.id}")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения администратору: {str(e)}")
        finally:
            if session:
                session.close()
        await message.answer(
            f"Бронь создана!\n"
            f"Тариф: {tariff.name}\n"
            f"Дата: {data['visit_date']}\n"
            f"Время: {data['visit_time']}\n"
            f"Продолжительность: {duration} ч\n"
            f"Ожидайте подтверждения.",
            reply_markup=create_user_keyboard(),
        )
        logger.info(
            f"Пользователь {message.from_user.id} завершил бронирование Переговорной: {data['visit_date']}, {duration} ч"
        )
    else:
        if session:
            session.close()
        await message.answer(admin_message, reply_markup=create_user_keyboard())
        logger.warning(
            f"Не удалось создать бронь для пользователя {message.from_user.id}"
        )
    await state.clear()


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Возврат в главное меню.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
    """
    await state.clear()
    await callback_query.message.answer(
        "Главное меню:", reply_markup=create_user_keyboard()
    )
    logger.info(f"Пользователь {callback_query.from_user.id} вернулся в главное меню")
    await callback_query.message.delete()
    await callback_query.answer()


def register_book_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
