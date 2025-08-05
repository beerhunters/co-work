import asyncio
import os
import re
from datetime import datetime, date, timedelta
from typing import Optional

import pytz
from aiogram import Router, Bot, Dispatcher, F
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv
from yookassa import Payment, Refund

from bot.config import (
    create_payment,
    rubitime,
    check_payment_status,
    create_user_keyboard,
    create_back_keyboard,
)
from models.models import (
    get_active_tariffs,
    create_booking,
    User,
    get_user_by_telegram_id,
    get_promocode_by_name,
    Promocode,
    format_booking_notification,
    Tariff,
)

from utils.logger import get_logger

# Тихая настройка логгера для модуля
load_dotenv()

router = Router()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
logger = get_logger(__name__)


class Booking(StatesGroup):
    """Состояния для процесса бронирования."""

    SELECT_TARIFF = State()
    ENTER_DATE = State()
    ENTER_TIME = State()
    ENTER_DURATION = State()
    ENTER_PROMOCODE = State()
    PAYMENT = State()
    STATUS_PAYMENT = State()


def format_payment_notification(user, booking_data, status="SUCCESS"):
    """Форматирует красивое уведомление об оплате для админа.

    Args:
        user: Объект пользователя.
        booking_data: Данные бронирования (словарь с tariff_name, visit_date, amount, payment_id).
        status: Статус платежа ("SUCCESS", "FAILED", "PENDING", "CANCELLED").

    Returns:
        str: Отформатированное сообщение.
    """
    status_emojis = {
        "SUCCESS": "✅",
        "FAILED": "❌",
        "PENDING": "⏳",
        "CANCELLED": "🚫",
    }

    status_emoji = status_emojis.get(status, "❓")
    status_texts = {
        "SUCCESS": "УСПЕШНО ОПЛАЧЕНО",
        "FAILED": "ОШИБКА ОПЛАТЫ",
        "PENDING": "ОЖИДАЕТ ОПЛАТЫ",
        "CANCELLED": "ОПЛАТА ОТМЕНЕНА",
    }
    status_text = status_texts.get(status, "НЕИЗВЕСТНЫЙ СТАТУС")

    message = f"""💳 <b>{status_text}</b> {status_emoji}

👤 <b>Клиент:</b> {user.full_name or 'Не указано'}
📞 <b>Телефон:</b> {user.phone or 'Не указано'}

💰 <b>Детали платежа:</b>
├ <b>Сумма:</b> {booking_data.get('amount', 0):.2f} ₽
├ <b>Тариф:</b> {booking_data.get('tariff_name', 'Неизвестно')}
├ <b>Дата брони:</b> {booking_data.get('visit_date', '').strftime('%d.%m.%Y') if booking_data.get('visit_date') else 'Неизвестно'}
└ <b>Payment ID:</b> <code>{booking_data.get('payment_id', 'Неизвестно')}</code>

⏰ <i>Время: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}</i>"""

    return message.strip()


def format_user_booking_notification(user, booking_data, confirmed: bool) -> str:
    """Форматирует красивое уведомление о бронировании для пользователя.

    Args:
        user: Объект пользователя.
        booking_data: Данные бронирования (словарь с tariff_name, tariff_purpose, visit_date, visit_time, duration, amount, discount, promocode_name).
        confirmed: Флаг подтверждения брони (True для "Опенспейс", False для "Переговорной").

    Returns:
        str: Отформатированное сообщение.
    """
    tariff_emojis = {
        "meeting": "🤝",
        "workspace": "💼",
        "event": "🎉",
        "office": "🏢",
        "coworking": "💻",
    }

    purpose = booking_data.get("tariff_purpose", "").lower()
    tariff_emoji = tariff_emojis.get(purpose, "📋")
    visit_date = booking_data.get("visit_date")
    visit_time = booking_data.get("visit_time")

    if visit_time:
        datetime_str = (
            f"{visit_date.strftime('%d.%m.%Y')} в {visit_time.strftime('%H:%M')}"
        )
    else:
        datetime_str = f"{visit_date.strftime('%d.%m.%Y')} (весь день)"

    discount_info = ""
    if booking_data.get("discount", 0) > 0:
        promocode_name = booking_data.get("promocode_name", "Неизвестный")
        discount = booking_data.get("discount", 0)
        discount_info = (
            f"\n💰 <b>Скидка:</b> {discount}% (промокод: <code>{promocode_name}</code>)"
        )

    duration_info = ""
    if booking_data.get("duration"):
        duration_info = f"\n⏱ <b>Длительность:</b> {booking_data['duration']} час(ов)"

    status_text = "Бронь подтверждена ✅" if confirmed else "Ожидайте подтверждения ⏳"
    status_instruction = (
        "" if confirmed else "\n📩 Мы свяжемся с вами для подтверждения брони."
    )

    message = f"""🎉 <b>Ваша бронь создана!</b> {tariff_emoji}

📋 <b>Детали брони:</b>
├ <b>Тариф:</b> {booking_data.get('tariff_name', 'Неизвестно')}
├ <b>Дата и время:</b> {datetime_str}{duration_info}
└ <b>Сумма:</b> {booking_data.get('amount', 0):.2f} ₽{discount_info}

📌 <b>Статус:</b> {status_text}{status_instruction}

⏰ <i>Время создания: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}</i>"""

    return message.strip()


def create_tariff_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру с активными тарифами, исключая 'Тестовый день' для пользователей с успешными бронированиями.

    Args:
        telegram_id: Telegram ID пользователя.

    Returns:
        InlineKeyboardMarkup: Клавиатура с тарифами и кнопкой отмены.
    """
    try:
        user = get_user_by_telegram_id(telegram_id)
        successful_bookings = user.successful_bookings
        tariffs = get_active_tariffs()
        buttons = []
        for tariff in tariffs:
            if tariff.service_id == 47890 and successful_bookings > 0:
                continue
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{tariff.name} ({tariff.price} {'₽/ч' if tariff.purpose == 'Переговорная' else '₽'})",
                        callback_data=f"tariff_{tariff.id}",
                    )
                ]
            )
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


def create_date_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру с датами (сегодня + 7 дней).

    Returns:
        InlineKeyboardMarkup: Клавиатура с датами и кнопкой отмены.
    """
    today = datetime.now(MOSCOW_TZ).date()
    buttons = []
    for i in range(8):  # Сегодня + 7 дней
        date = today + timedelta(days=i)
        buttons.append(
            [
                InlineKeyboardButton(
                    text=date.strftime("%d.%m.%Y"),
                    callback_data=f"date_{date.strftime('%Y-%m-%d')}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    logger.debug("Создана клавиатура с датами")
    return keyboard


def create_payment_keyboard(
    confirmation_url: str, amount: float
) -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с кнопкой оплаты и отмены.

    Args:
        confirmation_url: URL для оплаты через YooKassa.
        amount: Сумма платежа.

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками оплаты и отмены.
    """
    logger.debug(f"Создание клавиатуры для оплаты, сумма: {amount}")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Оплатить {amount:.2f} ₽", url=confirmation_url
                ),
                InlineKeyboardButton(text="Отмена", callback_data="cancel_payment"),
            ]
        ]
    )
    return keyboard


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
        await callback_query.message.edit_text(
            # await callback_query.message.answer(
            "Нет доступных тарифов для бронирования.",
            reply_markup=create_back_keyboard(),
        )
        logger.info(
            f"Пользователь {callback_query.from_user.id} попытался забронировать, "
            f"но нет активных тарифов"
        )
        # try:
        #     await callback_query.message.delete()
        # except TelegramBadRequest as e:
        #     logger.warning(
        #         f"Не удалось удалить сообщение для пользователя {callback_query.from_user.id}: {str(e)}"
        #     )
        await callback_query.answer()
        return

    await state.set_state(Booking.SELECT_TARIFF)
    await callback_query.message.edit_text(
        # await callback_query.message.answer(
        "Выберите тариф:",
        reply_markup=create_tariff_keyboard(callback_query.from_user.id),
    )
    logger.info(
        f"Пользователь {callback_query.from_user.id} начал процесс бронирования"
    )
    # try:
    #     await callback_query.message.delete()
    # except TelegramBadRequest as e:
    #     logger.warning(
    #         f"Не удалось удалить сообщение для пользователя {callback_query.from_user.id}: {str(e)}"
    #     )
    await callback_query.answer()


@router.callback_query(Booking.SELECT_TARIFF, F.data.startswith("tariff_"))
async def process_tariff_selection(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка выбора тарифа. Показывает клавиатуру с датами.

    Args:
        callback_query: Callback-запрос с выбранным тарифом.
        state: Контекст состояния FSM.
    """
    tariff_id = int(callback_query.data.split("_")[1])
    tariffs = get_active_tariffs()
    tariff = next((t for t in tariffs if t.id == tariff_id), None)
    if not tariff:
        await callback_query.message.edit_text(
            text="Тариф не найден. Попробуйте снова.",
            reply_markup=create_tariff_keyboard(callback_query.from_user.id),
        )
        logger.warning(
            f"Пользователь {callback_query.from_user.id} выбрал несуществующий тариф: {tariff_id}"
        )
        await callback_query.answer()
        return

    await state.update_data(
        tariff_id=tariff.id,
        tariff_name=tariff.name,
        tariff_purpose=tariff.purpose.lower(),
        tariff_service_id=tariff.service_id,
        tariff_price=tariff.price,
    )
    await state.set_state(Booking.ENTER_DATE)
    await callback_query.message.edit_text(
        text=f"Вы выбрали тариф: {tariff.name}\nВыберите дату визита:",
        reply_markup=create_date_keyboard(),
    )
    logger.info(
        f"Пользователь {callback_query.from_user.id} выбрал тариф {tariff.name}"
    )
    await callback_query.answer()


@router.callback_query(Booking.ENTER_DATE, F.data.startswith("date_"))
async def process_date_selection(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка выбора даты через инлайн-клавиатуру.

    Args:
        callback_query: Callback-запрос с выбранной датой.
        state: Контекст состояния FSM.
    """
    try:
        visit_date = datetime.strptime(
            callback_query.data.split("_")[1], "%Y-%m-%d"
        ).date()
        today = datetime.now(MOSCOW_TZ).date()
        if visit_date < today:
            await callback_query.message.edit_text(
                text="Дата не может быть в прошлом. Выберите снова:",
                reply_markup=create_date_keyboard(),
            )
            logger.warning(
                f"Пользователь {callback_query.from_user.id} выбрал прошедшую дату: {visit_date}"
            )
            await callback_query.answer()
            return

        data = await state.get_data()
        tariff_purpose = data["tariff_purpose"]
        tariff_name = data["tariff_name"]
        await state.update_data(visit_date=visit_date)
        if tariff_purpose == "переговорная":
            await state.set_state(Booking.ENTER_TIME)
            await callback_query.message.edit_text(
                text="Введите время визита (чч:мм, например, 14:30):",
                reply_markup=create_back_keyboard(),
            )
            logger.info(
                f"Пользователь {callback_query.from_user.id} выбрал дату {visit_date} для тарифа {tariff_name} через клавиатуру"
            )
        else:
            await state.set_state(Booking.ENTER_PROMOCODE)
            await callback_query.message.edit_text(
                text="Введите промокод (или /skip для пропуска):",
                reply_markup=create_back_keyboard(),
            )
            logger.info(
                f"Пользователь {callback_query.from_user.id} выбрал дату {visit_date} для тарифа {tariff_name} через клавиатуру"
            )
        await callback_query.answer()
    except ValueError as e:
        await callback_query.message.edit_text(
            text="Ошибка при обработке даты. Попробуйте снова:",
            reply_markup=create_date_keyboard(),
        )
        logger.error(
            f"Ошибка при обработке даты для пользователя {callback_query.from_user.id}: {str(e)}"
        )
        await callback_query.answer()


@router.message(Booking.ENTER_DATE)
async def process_date(message: Message, state: FSMContext) -> None:
    """
    Обработка введённой даты текстом. Проверяет формат и запрашивает время для 'Переговорной' или промокод.

    Args:
        message: Входящее сообщение с датой.
        state: Контекст состояния FSM.
    """
    try:
        visit_date = datetime.strptime(message.text, "%Y-%m-%d").date()
        today = datetime.now(MOSCOW_TZ).date()
        if visit_date < today:
            await message.answer(
                text="Дата не может быть в прошлом. Введите снова (гггг-мм-дд) или выберите из календаря:",
                reply_markup=create_date_keyboard(),
            )
            logger.warning(
                f"Пользователь {message.from_user.id} ввёл прошедшую дату: {message.text}"
            )
            return
    except ValueError:
        await message.answer(
            text="Неверный формат даты. Введите в формате гггг-мм-дд (например, 2025-07-25) или выберите из календаря:",
            reply_markup=create_date_keyboard(),
        )
        logger.warning(
            f"Пользователь {message.from_user.id} ввёл неверный формат даты: {message.text}"
        )
        return

    data = await state.get_data()
    tariff_purpose = data["tariff_purpose"]
    tariff_name = data["tariff_name"]
    await state.update_data(visit_date=visit_date)
    if tariff_purpose == "переговорная":
        await state.set_state(Booking.ENTER_TIME)
        await message.answer(
            text="Введите время визита (чч:мм, например, 14:30):",
            reply_markup=create_back_keyboard(),
        )
        logger.info(
            f"Пользователь {message.from_user.id} ввёл дату {visit_date} для тарифа {tariff_name} текстом"
        )
    else:
        await state.set_state(Booking.ENTER_PROMOCODE)
        await message.answer(
            text="Введите промокод (или /skip для пропуска):",
            reply_markup=create_back_keyboard(),
        )
        logger.info(
            f"Пользователь {message.from_user.id} ввёл дату {visit_date} для тарифа {tariff_name} текстом"
        )


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
    Обработка введённой продолжительности. Запрашивает промокод.

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

    await state.update_data(duration=duration)
    await state.set_state(Booking.ENTER_PROMOCODE)
    await message.answer(
        "Введите промокод (или /skip для пропуска):",
        reply_markup=create_back_keyboard(),
    )
    logger.info(
        f"Пользователь {message.from_user.id} ввёл продолжительность {duration} ч"
    )


@router.message(Booking.ENTER_PROMOCODE)
async def process_promocode(message: Message, state: FSMContext) -> None:
    """
    Обработка введённого промокода или его пропуска. Создаёт платёж или бронь в зависимости от тарифа.

    Args:
        message: Входящее сообщение с промокодом.
        state: Контекст состояния FSM.
    """
    data = await state.get_data()
    tariff_purpose = data["tariff_purpose"]
    tariff_name = data["tariff_name"]
    tariff_price = data["tariff_price"]
    promocode_id: Optional[int] = None
    promocode_name: Optional[str] = None
    discount: float = 0

    if message.text != "/skip":
        promocode_name = message.text.strip()
        promocode = get_promocode_by_name(promocode_name)

        if not promocode:
            await message.answer(
                "Промокод не найден или неактивен. Введите другой или используйте /skip для продолжения.",
                reply_markup=create_back_keyboard(),
            )
            logger.warning(
                f"Пользователь {message.from_user.id} ввёл несуществующий или неактивный промокод: {promocode_name}"
            )
            return

        if promocode.expiration_date and promocode.expiration_date < datetime.now(
            MOSCOW_TZ
        ):
            await message.answer(
                "Срок действия промокода истёк. Введите другой или используйте /skip для продолжения.",
                reply_markup=create_back_keyboard(),
            )
            logger.warning(
                f"Пользователь {message.from_user.id} ввёл просроченный промокод: {promocode_name}"
            )
            return

        if promocode.usage_quantity <= 0:
            await message.answer(
                "Промокод исчерпал лимит использований. Введите другой или используйте /skip для продолжения.",
                reply_markup=create_back_keyboard(),
            )
            logger.warning(
                f"Пользователь {message.from_user.id} ввёл исчерпанный промокод: {promocode_name}"
            )
            return

        discount = promocode.discount
        promocode_id = promocode.id
        await message.answer(
            f"Промокод '{promocode_name}' применён! Скидка: {discount}%",
            reply_markup=create_back_keyboard(),
        )
        logger.info(
            f"Пользователь {message.from_user.id} применил промокод {promocode_name} со скидкой {discount}%"
        )
    else:
        logger.info(f"Пользователь {message.from_user.id} пропустил промокод")

    duration = data.get("duration")
    if tariff_purpose == "переговорная" and duration:
        amount = tariff_price * duration
        if duration >= 3:
            additional_discount = 10
            total_discount = min(100, discount + additional_discount)
            amount *= 1 - total_discount / 100
            logger.info(
                f"Применена скидка {total_discount}% (промокод: {discount}%, "
                f"дополнительно: {additional_discount}%) для бронирования на {duration} ч, "
                f"итоговая сумма: {amount:.2f}"
            )
        else:
            amount *= 1 - discount / 100
            logger.info(
                f"Применена скидка {discount}% для бронирования на {duration} ч, "
                f"итоговая сумма: {amount:.2f}"
            )
    else:
        amount = tariff_price * (1 - discount / 100)
        logger.info(
            f"Применена скидка {discount}% для тарифа {tariff_name}, "
            f"итоговая сумма: {amount:.2f}"
        )

    description = f"Бронь: {tariff_name}, дата: {data['visit_date']}"
    if tariff_purpose == "переговорная":
        description += f", время: {data.get('visit_time')}, длительность: {duration} ч, сумма: {amount:.2f} ₽"
    else:
        description += f", сумма: {amount:.2f} ₽"
    if promocode_name:
        description += f", промокод: {promocode_name} ({discount}%)"

    await state.update_data(
        amount=amount,
        promocode_id=promocode_id,
        promocode_name=promocode_name,
        discount=discount,
    )

    if tariff_purpose == "переговорная":
        await handle_free_booking(message, state, bot=message.bot, paid=False)
    elif amount == 0:
        await handle_free_booking(message, state, bot=message.bot, paid=True)
    else:
        payment_id, confirmation_url = await create_payment(description, amount)
        if not payment_id or not confirmation_url:
            await message.answer(
                "Ошибка при создании платежа. Попробуйте позже.",
                reply_markup=create_user_keyboard(),
            )
            logger.error(
                f"Не удалось создать платёж для пользователя {message.from_user.id}"
            )
            await state.clear()
            return

        await state.update_data(payment_id=payment_id)
        payment_message = await message.answer(
            f"Оплатите бронирование:\n{description}",
            reply_markup=create_payment_keyboard(confirmation_url, amount),
        )
        await state.update_data(payment_message_id=payment_message.message_id)
        await state.set_state(Booking.STATUS_PAYMENT)

        task = asyncio.create_task(poll_payment_status(message, state, bot=message.bot))
        await state.update_data(payment_task=task)
        logger.info(
            f"Создан платёж {payment_id} для пользователя {message.from_user.id}, "
            f"сумма: {amount:.2f}"
        )


def format_phone_for_rubitime(phone: str) -> str:
    """
    Форматирует номер телефона для Rubitime в формате +7**********.

    Args:
        phone: Исходный номер телефона.

    Returns:
        str: Форматированный номер или "Не указано", если номер некорректен.
    """
    if not phone or phone == "Не указано":
        return "Не указано"

    digits = re.sub(r"[^0-9]", "", phone)
    if digits.startswith("8") or digits.startswith("+7"):
        if len(digits) >= 11:
            return f"+7{digits[-10:]}"
    logger.warning(f"Некорректный формат номера телефона: {phone}")
    return "Не указано"


async def handle_free_booking(
    message: Message, state: FSMContext, bot: Bot, paid: bool = True
) -> None:
    """
    Обработка бронирования без оплаты (для "Переговорной" или если сумма после скидки = 0).

    Args:
        message: Входящее сообщение.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
        paid: Флаг, указывающий, оплачена ли бронь (True для бесплатных, False для "Переговорной").
    """
    data = await state.get_data()
    tariff_id = data["tariff_id"]
    tariff_name = data["tariff_name"]
    tariff_purpose = data["tariff_purpose"]
    tariff_service_id = data["tariff_service_id"]
    visit_date = data["visit_date"]
    visit_time = data.get("visit_time")
    duration = data.get("duration")
    amount = data["amount"]
    promocode_id = data.get("promocode_id")
    promocode_name = data.get("promocode_name", "-")
    discount = data.get("discount", 0)

    booking, admin_message, session = create_booking(
        telegram_id=message.from_user.id,
        tariff_id=tariff_id,
        visit_date=visit_date,
        visit_time=visit_time,
        duration=duration,
        promocode_id=promocode_id,
        amount=amount,
        paid=paid,
        confirmed=(False if tariff_purpose == "переговорная" else True),
    )
    if not booking:
        if session:
            session.close()
        await message.answer(
            admin_message or "Ошибка при создании брони.",
            reply_markup=create_user_keyboard(),
        )
        logger.warning(
            f"Не удалось создать бронь для пользователя {message.from_user.id}"
        )
        await state.clear()
        return

    try:
        user = session.query(User).filter_by(telegram_id=message.from_user.id).first()

        # Уменьшаем количество использований промокода, если он применён
        if promocode_id:
            promocode = session.query(Promocode).filter_by(id=promocode_id).first()
            if promocode:
                promocode.usage_quantity -= 1
                session.add(promocode)
                logger.info(
                    f"Промокод {promocode_name} использован, "
                    f"осталось использований: {promocode.usage_quantity}"
                )

        # Увеличиваем счетчик успешных бронирований для тарифов "Опенспейс" при успешной брони
        if tariff_purpose == "опенспейс" and booking.confirmed:
            user.successful_bookings += 1
            logger.info(
                f"Увеличен счетчик successful_bookings для пользователя {user.telegram_id} "
                f"до {user.successful_bookings}"
            )

        session.commit()

        # Формируем дату и время для Rubitime
        if tariff_purpose == "переговорная" and visit_time and duration:
            rubitime_date = datetime.combine(visit_date, visit_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            rubitime_duration = duration * 60
        else:
            rubitime_date = visit_date.strftime("%Y-%m-%d") + " 09:00:00"
            rubitime_duration = None

        formatted_phone = format_phone_for_rubitime(user.phone or "Не указано")
        rubitime_params = {
            "service_id": tariff_service_id,
            "name": user.full_name or "Не указано",
            "email": user.email or "Не указано",
            "phone": formatted_phone,
            "record": rubitime_date,
            "comment": f"Промокод: {promocode_name}, скидка: {discount}%",
            "coupon": promocode_name,
            "coupon_discount": f"{discount}%",
            "price": amount,
        }
        if rubitime_duration:
            rubitime_params["duration"] = rubitime_duration

        rubitime_id = await rubitime("create_record", rubitime_params)
        if rubitime_id:
            booking.rubitime_id = rubitime_id
            session.commit()
            logger.info(
                f"Запись в Rubitime создана: ID {rubitime_id}, date={rubitime_date}, "
                f"duration={rubitime_duration}, price={amount}"
            )

            # Обновляем admin_message с актуальным rubitime_id
            updated_booking_data = {
                **data,
                "rubitime_id": rubitime_id,
            }
            admin_message = format_booking_notification(
                user,
                session.query(Tariff).filter_by(id=tariff_id).first(),
                updated_booking_data,
            )

        await bot.send_message(
            ADMIN_TELEGRAM_ID,
            admin_message,
            parse_mode="HTML",
        )

        # Формируем сообщение для пользователя
        response_text = format_user_booking_notification(
            user,
            {**data, "rubitime_id": rubitime_id or "Не создано"},
            confirmed=(tariff_purpose != "переговорная"),
        )
        await message.answer(
            response_text,
            parse_mode="HTML",
            reply_markup=create_user_keyboard(),
        )
        logger.info(
            f"Бронь создана для пользователя {message.from_user.id}, "
            f"ID брони {booking.id}, paid={paid}, amount={amount}"
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке брони: {str(e)}")
        session.rollback()
        await message.answer(
            "Ошибка при создании брони. Попробуйте позже.",
            reply_markup=create_user_keyboard(),
        )
    finally:
        if session:
            session.close()
        await state.clear()


async def poll_payment_status(message: Message, state: FSMContext, bot: Bot) -> None:
    """
    Проверка статуса платежа с ограничением по времени.

    Args:
        message: Входящее сообщение.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
    """
    data = await state.get_data()
    payment_id = data["payment_id"]
    payment_message_id = data["payment_message_id"]
    tariff_id = data["tariff_id"]
    tariff_name = data["tariff_name"]
    tariff_purpose = data["tariff_purpose"]
    tariff_service_id = data["tariff_service_id"]
    visit_date = data["visit_date"]
    visit_time = data.get("visit_time")
    duration = data.get("duration")
    amount = data["amount"]
    promocode_id = data.get("promocode_id")
    promocode_name = data.get("promocode_name", "-")
    discount = data.get("discount", 0)

    max_attempts = 60
    delay = 5
    user = None
    for _ in range(max_attempts):
        status = await check_payment_status(payment_id)
        if status == "succeeded":
            booking, admin_message, session = create_booking(
                telegram_id=message.from_user.id,
                tariff_id=tariff_id,
                visit_date=visit_date,
                visit_time=visit_time,
                duration=duration,
                promocode_id=promocode_id,
                amount=amount,
                paid=True,
                confirmed=(True if duration is None else False),
                payment_id=payment_id,
            )
            if not booking:
                if session:
                    session.close()
                await bot.edit_message_text(
                    text="Ошибка при создании брони. Попробуйте позже.",
                    chat_id=message.chat.id,
                    message_id=payment_message_id,
                    reply_markup=create_user_keyboard(),
                )
                logger.warning(
                    f"Не удалось создать бронь после оплаты для пользователя {message.from_user.id}"
                )
                await state.clear()
                return
            try:
                user = (
                    session.query(User)
                    .filter_by(telegram_id=message.from_user.id)
                    .first()
                )

                # Уменьшаем количество использований промокода, если он применён
                if promocode_id:
                    promocode = (
                        session.query(Promocode).filter_by(id=promocode_id).first()
                    )
                    if promocode:
                        promocode.usage_quantity -= 1
                        session.add(promocode)
                        logger.info(
                            f"Промокод {promocode_name} использован, "
                            f"осталось использований: {promocode.usage_quantity}"
                        )

                # Увеличиваем счетчик успешных бронирований для тарифов "Опенспейс" при успешной брони
                if tariff_purpose == "опенспейс" and booking.confirmed:
                    user.successful_bookings += 1
                    logger.info(
                        f"Увеличен счетчик successful_bookings для пользователя {user.telegram_id} "
                        f"до {user.successful_bookings}"
                    )

                session.commit()

                # Формируем дату и время для Rubitime
                if tariff_purpose == "переговорная" and visit_time and duration:
                    rubitime_date = datetime.combine(visit_date, visit_time).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    rubitime_duration = duration * 60
                else:
                    rubitime_date = visit_date.strftime("%Y-%m-%d") + " 09:00:00"
                    rubitime_duration = None

                formatted_phone = format_phone_for_rubitime(user.phone or "Не указано")
                rubitime_params = {
                    "service_id": tariff_service_id,
                    "name": user.full_name or "Не указано",
                    "email": user.email or "Не указано",
                    "phone": formatted_phone,
                    "record": rubitime_date,
                    "comment": f"Промокод: {promocode_name}, скидка: {discount}%",
                    "coupon": promocode_name,
                    "coupon_discount": f"{discount}%",
                    "price": amount,
                }
                if rubitime_duration:
                    rubitime_params["duration"] = rubitime_duration

                rubitime_id = await rubitime("create_record", rubitime_params)
                if rubitime_id:
                    booking.rubitime_id = rubitime_id
                    session.commit()
                    logger.info(
                        f"Запись в Rubitime создана: ID {rubitime_id}, date={rubitime_date}, "
                        f"duration={rubitime_duration}, price={amount}"
                    )

                    # Обновляем admin_message с актуальным rubitime_id
                    updated_booking_data = {
                        **data,
                        "rubitime_id": rubitime_id,
                    }
                    admin_message = format_booking_notification(
                        user,
                        session.query(Tariff).filter_by(id=tariff_id).first(),
                        updated_booking_data,
                    )

                # Отправляем уведомление об успешной оплате
                payment_notification = format_payment_notification(
                    user, data, status="SUCCESS"
                )
                await bot.send_message(
                    ADMIN_TELEGRAM_ID,
                    payment_notification,
                    parse_mode="HTML",
                )
                await bot.send_message(
                    ADMIN_TELEGRAM_ID,
                    admin_message,
                    parse_mode="HTML",
                )

                # Формируем сообщение для пользователя
                response_text = format_user_booking_notification(
                    user,
                    {**data, "rubitime_id": rubitime_id or "Не создано"},
                    confirmed=(tariff_purpose != "переговорная"),
                )
                await bot.edit_message_text(
                    text=response_text,
                    chat_id=message.chat.id,
                    message_id=payment_message_id,
                    parse_mode="HTML",
                    reply_markup=create_user_keyboard(),
                )
                logger.info(
                    f"Бронь создана после оплаты для пользователя {message.from_user.id}, "
                    f"ID брони {booking.id}, amount={amount}"
                )
            except Exception as e:
                logger.error(f"Ошибка после успешной оплаты: {str(e)}")
                session.rollback()
                # Отправляем уведомление об ошибке
                # payment_notification = format_payment_notification(
                #     user, data, status="FAILED"
                # )
                if user:
                    payment_notification = format_payment_notification(
                        user, data, status="FAILED"
                    )
                else:
                    payment_notification = (
                        f"⚠️ Ошибка: не удалось создать бронь. Пользователь не найден.\n"
                        f"Payment ID: {payment_id}\n"
                        f"Сумма: {amount} руб."
                    )
                await bot.send_message(
                    ADMIN_TELEGRAM_ID,
                    payment_notification,
                    parse_mode="HTML",
                )
                await bot.edit_message_text(
                    text="Ошибка при создании брони. Попробуйте позже.",
                    chat_id=message.chat.id,
                    message_id=payment_message_id,
                    reply_markup=create_user_keyboard(),
                )
            finally:
                if session:
                    session.close()
                await state.clear()
            return
        elif status == "canceled":
            payment_notification = format_payment_notification(
                user, data, status="CANCELLED"
            )
            await bot.send_message(
                ADMIN_TELEGRAM_ID,
                payment_notification,
                parse_mode="HTML",
            )
            await bot.edit_message_text(
                text="Платёж отменён.",
                chat_id=message.chat.id,
                message_id=payment_message_id,
                reply_markup=create_user_keyboard(),
            )
            await state.clear()
            return
        await asyncio.sleep(delay)

    payment_notification = format_payment_notification(user, data, status="FAILED")
    await bot.send_message(
        ADMIN_TELEGRAM_ID,
        payment_notification,
        parse_mode="HTML",
    )
    await bot.edit_message_text(
        text="Время оплаты истекло. Попробуйте снова.",
        chat_id=message.chat.id,
        message_id=payment_message_id,
        reply_markup=create_user_keyboard(),
    )
    await state.clear()
    logger.warning(f"Время оплаты истекло для payment_id {payment_id}")


@router.callback_query(Booking.STATUS_PAYMENT, F.data == "cancel_payment")
async def cancel_payment(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка отмены платежа.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
    """
    data = await state.get_data()
    payment_id = data.get("payment_id")
    payment_message_id = data.get("payment_message_id")
    payment_task = data.get("payment_task")

    user = get_user_by_telegram_id(callback_query.from_user.id)

    if payment_task and not payment_task.done():
        payment_task.cancel()
        logger.info(f"Задача проверки платежа {payment_id} отменена")

    if payment_id:
        try:
            status = await check_payment_status(payment_id)
            if status == "succeeded":
                refund = Refund.create(
                    {
                        "amount": {
                            "value": f"{data['amount']:.2f}",
                            "currency": "RUB",
                        },
                        "payment_id": payment_id,
                        "description": f"Возврат для брони {payment_id}",
                    }
                )
                logger.info(
                    f"Возврат создан для платежа {payment_id}, refund_id={refund.id}"
                )
            elif status == "pending":
                Payment.cancel(payment_id)
                logger.info(f"Платёж {payment_id} отменён в YooKassa")
            else:
                logger.info(
                    f"Платёж {payment_id} уже в статусе {status}, отмена не требуется"
                )
        except Exception as e:
            logger.warning(f"Не удалось обработать платёж {payment_id}: {str(e)}")
            logger.info(f"Завершаем отмену без дополнительного обращения к YooKassa")

    payment_notification = format_payment_notification(user, data, status="CANCELLED")
    await callback_query.message.bot.send_message(
        ADMIN_TELEGRAM_ID,
        payment_notification,
        parse_mode="HTML",
    )
    await callback_query.message.edit_text(
        text="Платёж отменён.",
        reply_markup=create_user_keyboard(),
    )
    await state.clear()
    logger.info(f"Платёж отменён для пользователя {callback_query.from_user.id}")
    await callback_query.answer()


@router.callback_query(
    F.data == "cancel",
    StateFilter(
        Booking.SELECT_TARIFF,
        Booking.ENTER_DATE,
        Booking.ENTER_TIME,
        Booking.ENTER_DURATION,
        Booking.ENTER_PROMOCODE,
    ),
)
@router.callback_query(
    F.data == "main_menu",
    StateFilter(
        Booking.SELECT_TARIFF,
        Booking.ENTER_DATE,
        Booking.ENTER_TIME,
        Booking.ENTER_DURATION,
        Booking.ENTER_PROMOCODE,
    ),
)
async def cancel_booking(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка нажатия кнопки 'Главное меню' в состояниях бронирования.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
    """
    await state.clear()
    await callback_query.message.edit_text(
        text="Бронирование отменено.", reply_markup=create_user_keyboard()
    )
    logger.info(f"Пользователь {callback_query.from_user.id} вернулся в главное меню")
    await callback_query.answer()


def register_book_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
