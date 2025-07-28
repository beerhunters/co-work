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
from yookassa import Payment, Refund
import asyncio
from typing import Optional
import re

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
)
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
    ENTER_PROMOCODE = State()
    PAYMENT = State()
    STATUS_PAYMENT = State()


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
            # Пропускаем тариф 'Тестовый день', если у пользователя есть успешные бронирования
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
                InlineKeyboardButton(text=f"Оплатить {amount} ₽", url=confirmation_url),
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
        "Выберите тариф:",
        reply_markup=create_tariff_keyboard(callback_query.from_user.id),
    )
    logger.info(
        f"Пользователь {callback_query.from_user.id} начал процесс бронирования"
    )
    await callback_query.message.delete()
    await callback_query.answer()


@router.callback_query(Booking.SELECT_TARIFF, F.data == "cancel")
async def cancel_tariff_selection(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка нажатия кнопки 'Отмена' в состоянии выбора тарифа.
    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
    """
    await state.clear()
    await callback_query.message.edit_text(
        text="Бронирование отменено.", reply_markup=create_user_keyboard()
    )
    logger.info(f"Пользователь {callback_query.from_user.id} отменил выбор тарифа")
    await callback_query.answer()


@router.callback_query(
    Booking.ENTER_DATE
    or Booking.ENTER_TIME
    or Booking.ENTER_DURATION
    or Booking.ENTER_PROMOCODE,
    F.data == "main_menu",
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


@router.callback_query(Booking.SELECT_TARIFF, F.data.startswith("tariff_"))
async def process_tariff_selection(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка выбора тарифа. Запрашивает дату.
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

    await state.update_data(tariff_id=tariff.id)
    await state.set_state(Booking.ENTER_DATE)
    await callback_query.message.edit_text(
        text=f"Вы выбрали тариф: {tariff.name}\nВведите дату визита (гггг-мм-дд, например, 2025-07-25):",
        reply_markup=create_back_keyboard(),
    )
    logger.info(
        f"Пользователь {callback_query.from_user.id} выбрал тариф {tariff.name}"
    )
    await callback_query.answer()


@router.message(Booking.ENTER_DATE)
async def process_date(message: Message, state: FSMContext) -> None:
    """
    Обработка введённой даты. Проверяет формат и запрашивает время для 'Переговорной' или промокод.
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
        await state.set_state(Booking.ENTER_PROMOCODE)
        await message.answer(
            "Введите промокод (или /skip для пропуска):",
            reply_markup=create_back_keyboard(),
        )
        logger.info(
            f"Пользователь {message.from_user.id} ввёл дату {visit_date} для тарифа {tariff.name}"
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
    tariffs = get_active_tariffs()
    tariff = next((t for t in tariffs if t.id == data["tariff_id"]), None)
    if not tariff:
        await message.answer(
            "Тариф не найден. Попробуйте снова.", reply_markup=create_user_keyboard()
        )
        logger.warning(f"Тариф {data['tariff_id']} не найден при обработке промокода")
        await state.clear()
        return

    promocode = message.text.strip()
    discount = 0
    promocode_name = None
    if promocode != "/skip":
        await message.answer(
            "Промокоды пока не поддерживаются. Продолжаем без скидки.",
            reply_markup=create_back_keyboard(),
        )
        logger.warning(
            f"Попытка использовать промокод {promocode}, но функционал не реализован"
        )
    else:
        logger.info(f"Пользователь {message.from_user.id} пропустил промокод")

    # Рассчитываем стоимость с учетом продолжительности для "Переговорной"
    duration = data.get("duration")
    if tariff.purpose == "Переговорная" and duration:
        amount = tariff.price * duration
        if duration > 3:
            discount = 10  # Скидка 10% для бронирований более 3 часов
            amount *= 1 - discount / 100
            logger.info(
                f"Применена скидка 10% для бронирования на {duration} ч, итоговая сумма: {amount}"
            )
    else:
        amount = tariff.price * (1 - discount / 100)

    description = f"Бронь: {tariff.name}, дата: {data['visit_date']}" + (
        f", время: {data['visit_time']}, длительность: {duration} ч, сумма: {amount:.2f} ₽"
        if tariff.purpose == "Переговорная"
        else ""
    )

    await state.update_data(
        amount=amount, promocode_name=promocode_name, discount=discount
    )

    if tariff.purpose == "Переговорная":
        await state.update_data(tariff_purpose=tariff.purpose)
        # Для "Переговорной" создаём бронь без оплаты
        await handle_free_booking(message, state, bot=message.bot, paid=False)
    elif amount == 0:
        # Для бесплатных бронирований (не "Переговорная") с нулевой суммой
        await handle_free_booking(message, state, bot=message.bot, paid=True)
    else:
        # Для остальных тарифов создаём платёж
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
            f"Оплатите бронирование:\n{description}\nСумма: {amount:.2f} ₽",
            reply_markup=create_payment_keyboard(confirmation_url, amount),
        )
        await state.update_data(payment_message_id=payment_message.message_id)
        await state.set_state(Booking.STATUS_PAYMENT)

        task = asyncio.create_task(poll_payment_status(message, state, bot=message.bot))
        await state.update_data(payment_task=task)
        logger.info(
            f"Создан платёж {payment_id} для пользователя {message.from_user.id}, сумма: {amount:.2f}"
        )


def format_phone_for_rubitime(phone: str) -> str:
    """
    Форматирует номер телефона для Rubitime в формате +7**********.
    Args:
        phone: Исходный номер телефона.
    Returns:
        Форматированный номер или "Не указано", если номер некорректен.
    """
    if not phone or phone == "Не указано":
        return "Не указано"

    # Удаляем все нецифровые символы
    digits = re.sub(r"[^0-9]", "", phone)

    # Проверяем, начинается ли номер с +7 или 8
    if digits.startswith("8") or digits.startswith("+7"):
        # Берем последние 10 цифр и добавляем +7
        if len(digits) >= 11:
            return f"+7{digits[-10:]}"

    # Если номер не соответствует формату, возвращаем значение по умолчанию
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
    visit_date = data["visit_date"]
    visit_time = data.get("visit_time")
    duration = data.get("duration")
    amount = data["amount"]
    promocode_name = data.get("promocode_name", "-")
    discount = data.get("discount", 0)
    tariff_purpose = data.get("tariff_purpose", "")

    booking, admin_message, session = create_booking(
        telegram_id=message.from_user.id,
        tariff_id=tariff_id,
        visit_date=visit_date,
        visit_time=visit_time,
        duration=duration,
        amount=amount,
        paid=paid,
        confirmed=(
            False if tariff_purpose == "Переговорная" else True
        ),  # Всегда False, так как требует подтверждения
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
        tariffs = get_active_tariffs()
        tariff = next((t for t in tariffs if t.id == tariff_id), None)

        # Увеличиваем счетчик успешных бронирований для тарифов с назначением "Опенспейс"
        if tariff.purpose == "Опенспейс":
            user.successful_bookings += 1
            session.commit()
            logger.info(
                f"Увеличен счетчик successful_bookings для пользователя {user.telegram_id} до {user.successful_bookings}"
            )

        # Формируем дату и время для Rubitime
        if tariff.purpose == "Переговорная" and visit_time and duration:
            # Комбинируем дату и время для "Переговорной"
            rubitime_date = datetime.combine(visit_date, visit_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            rubitime_duration = duration * 60  # Преобразуем часы в минуты
        else:
            # Для остальных тарифов используем фиксированное время
            rubitime_date = visit_date.strftime("%Y-%m-%d") + " 09:00:00"
            rubitime_duration = None

        # Форматируем номер телефона для Rubitime
        formatted_phone = format_phone_for_rubitime(user.phone or "Не указано")
        # Формируем параметры для Rubitime
        rubitime_params = {
            "service_id": tariff.service_id,
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
                f"Запись в Rubitime создана: ID {rubitime_id}, date={rubitime_date}, duration={rubitime_duration}, price={amount}"
            )

        await bot.send_message(ADMIN_TELEGRAM_ID, admin_message)
        await message.answer(
            f"Бронь создана!\n"
            f"Тариф: {tariff.name}\n"
            f"Дата: {visit_date}\n"
            + (
                f"Время: {visit_time}\nПродолжительность: {duration} ч\nСумма: {amount:.2f} ₽\n"
                if duration
                else ""
            )
            + "Ожидайте подтверждения.",
            reply_markup=create_user_keyboard(),
        )
        logger.info(
            f"Бронь создана для пользователя {message.from_user.id}, ID брони {booking.id}, paid={paid}, amount={amount}"
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке брони: {str(e)}")
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
    visit_date = data["visit_date"]
    visit_time = data.get("visit_time")
    duration = data.get("duration")
    amount = data["amount"]
    promocode_name = data.get("promocode_name", "-")
    discount = data.get("discount", 0)

    max_attempts = 60  # 5 минут (60 * 5 сек)
    delay = 5  # Секунды между попытками

    for _ in range(max_attempts):
        status = await check_payment_status(payment_id)
        if status == "succeeded":
            booking, admin_message, session = create_booking(
                telegram_id=message.from_user.id,
                tariff_id=tariff_id,
                visit_date=visit_date,
                visit_time=visit_time,
                duration=duration,
                amount=amount,
                paid=True,
                confirmed=True if duration is None else False,
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
                tariffs = get_active_tariffs()
                tariff = next((t for t in tariffs if t.id == tariff_id), None)

                # Увеличиваем счетчик успешных бронирований для тарифов с назначением "Опенспейс"
                if tariff.purpose == "Опенспейс":
                    user.successful_bookings += 1
                    session.commit()
                    logger.info(
                        f"Увеличен счетчик successful_bookings для пользователя {user.telegram_id} до {user.successful_bookings}"
                    )

                # Формируем дату и время для Rubitime
                if tariff.purpose == "Переговорная" and visit_time and duration:
                    # Комбинируем дату и время для "Переговорной"
                    rubitime_date = datetime.combine(visit_date, visit_time).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    rubitime_duration = duration * 60  # Преобразуем часы в минуты
                else:
                    # Для остальных тарифов используем фиксированное время
                    rubitime_date = visit_date.strftime("%Y-%m-%d") + " 09:00:00"
                    rubitime_duration = None

                # Форматируем номер телефона для Rubitime
                formatted_phone = format_phone_for_rubitime(user.phone or "Не указано")
                # Формируем параметры для Rubitime
                rubitime_params = {
                    "service_id": tariff.service_id,
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
                        f"Запись в Rubitime создана: ID {rubitime_id}, date={rubitime_date}, duration={rubitime_duration}, price={amount}"
                    )

                await bot.send_message(ADMIN_TELEGRAM_ID, admin_message)
                await bot.edit_message_text(
                    text=f"Бронь создана!\n"
                    f"Тариф: {tariff.name}\n"
                    f"Дата: {visit_date}\n"
                    + (
                        f"Время: {visit_time}\nПродолжительность: {duration} ч\nСумма: {amount:.2f} ₽\n"
                        if duration
                        else ""
                    )
                    + (
                        f"Ожидайте подтверждения."
                        if tariff.purpose == "Переговорная"
                        else "Бронь подтверждена."
                    ),
                    chat_id=message.chat.id,
                    message_id=payment_message_id,
                    reply_markup=create_user_keyboard(),
                )
                logger.info(
                    f"Бронь создана после оплаты для пользователя {message.from_user.id}, ID брони {booking.id}, amount={amount}"
                )
            except Exception as e:
                logger.error(f"Ошибка после успешной оплаты: {str(e)}")
                await bot.edit_message_text(
                    text="Ошибка при создания брони. Попробуйте позже.",
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
            await bot.edit_message_text(
                text="Платёж отменён.",
                chat_id=message.chat.id,
                message_id=payment_message_id,
                reply_markup=create_user_keyboard(),
            )
            await state.clear()
            return
        await asyncio.sleep(delay)

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

    if payment_task and not payment_task.done():
        payment_task.cancel()
        logger.info(f"Задача проверки платежа {payment_id} отменена")

    if payment_id:
        try:
            status = await check_payment_status(payment_id)
            if status == "succeeded":
                # Платёж успешен, выполняем возврат
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
                # Платёж в ожидании, пытаемся отменить
                Payment.cancel(payment_id)
                logger.info(f"Платёж {payment_id} отменён в YooKassa")
            else:
                logger.info(
                    f"Платёж {payment_id} уже в статусе {status}, отмена не требуется"
                )
        except Exception as e:
            logger.warning(f"Не удалось обработать платёж {payment_id}: {str(e)}")
            logger.info(f"Завершаем отмену без дополнительного обращения к YooKassa")

    await callback_query.message.edit_text(
        text="Платёж отменён.",
        reply_markup=create_user_keyboard(),
    )
    await state.clear()
    logger.info(f"Платёж отменён для пользователя {callback_query.from_user.id}")
    await callback_query.answer()


def register_book_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
