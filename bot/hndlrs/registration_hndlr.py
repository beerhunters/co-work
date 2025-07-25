import os
import re
from datetime import datetime

import pytz
from aiogram import Router, Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from models.models import add_user, check_and_add_user
from utils.logger import setup_logger

logger = setup_logger(__name__)

load_dotenv()

router = Router()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")


def create_register_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для начала регистрации.
    """
    logger.debug("Создание инлайн-клавиатуры для регистрации")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Начать регистрацию", callback_data="start_registration"
                )
            ]
        ]
    )
    return keyboard


def create_agreement_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для подтверждения согласия с правилами.
    """
    logger.debug("Создание инлайн-клавиатуры для согласия с правилами")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Согласен", callback_data="agree_to_terms")]
        ]
    )
    return keyboard


def create_user_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для начала регистрации.
    """
    logger.debug("Создание инлайн-клавиатуры для пользователя")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Информация", callback_data="info")]
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
            [InlineKeyboardButton(text="Главное меню", callback_data="main_menu")]
        ]
    )
    return keyboard


class Registration(StatesGroup):
    """Состояния для процесса регистрации."""

    agreement = State()
    full_name = State()
    phone = State()
    email = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    Обработчик команды /start.

    Проверяет регистрацию пользователя и предлагает начать регистрацию, если она не завершена.
    """
    logger.info(f"Получена команда /start от пользователя {message.from_user.id}")
    await state.clear()
    if not message.from_user:
        logger.warning("Не удалось определить пользователя для команды /start")
        await message.answer("Не удалось определить пользователя.")
        return

    result = check_and_add_user(
        telegram_id=message.from_user.id, username=message.from_user.username
    )

    if not result:
        logger.error(f"Ошибка при регистрации пользователя {message.from_user.id}")
        await message.answer("Произошла ошибка при регистрации. Попробуйте позже.")
        return

    user, is_complete = result

    if is_complete:
        full_name = user.full_name or "Пользователь"
        logger.debug(
            f"Пользователь {message.from_user.id} уже полностью зарегистрирован: {full_name}"
        )
        await message.answer(
            f"Добро пожаловать, {full_name}!",
            reply_markup=create_user_keyboard(),
            parse_mode="HTML",
        )
    else:
        logger.debug(f"Пользователь {message.from_user.id} не завершил регистрацию")
        await message.answer(
            "Добро пожаловать!\n\n"
            "Бот предназначен для взаимодействия с коворкингом.\n\n"
            "Для продолжения регистрации, нажмите кнопку ниже.",
            reply_markup=create_register_keyboard(),
        )


@router.callback_query(F.data == "start_registration")
async def start_registration(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик нажатия кнопки "Начать регистрацию".

    Запрашивает подтверждение согласия с обработкой данных и правилами коворкинга.
    """
    logger.info(f"Начало регистрации для пользователя {callback_query.from_user.id}")
    await callback_query.message.answer(
        'Продолжая регистрацию, вы соглашаетесь с обработкой персональных данных и <a href="https://parta-works.ru/main_rules">правилами коворкинга</a>.',
        reply_markup=create_agreement_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()
    await state.set_state(Registration.agreement)


@router.callback_query(F.data == "agree_to_terms")
async def agree_to_terms(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик нажатия кнопки "Согласен".

    Обновляет сообщение, добавляя зелёную галочку, и запрашивает ФИО.
    """
    logger.info(f"Пользователь {callback_query.from_user.id} согласился с правилами")
    try:
        add_user(telegram_id=callback_query.from_user.id, agreed_to_terms=True)
    except Exception as e:
        logger.error(
            f"Ошибка при обновлении agreed_to_terms для пользователя {callback_query.from_user.id}: {e}"
        )
        await callback_query.message.answer("Произошла ошибка. Попробуйте снова.")
        return
    await callback_query.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Согласен 🟢", callback_data="agree_to_terms"
                    )
                ]
            ]
        )
    )
    await callback_query.message.answer("Введите ваше ФИО для завершения регистрации:")
    await state.set_state(Registration.full_name)


@router.message(Registration.agreement)
async def handle_invalid_agreement(message: Message, state: FSMContext) -> None:
    """
    Обработчик некорректного ввода на этапе согласия.

    Повторно запрашивает согласие.
    """
    logger.warning(
        f"Некорректный ввод на этапе согласия от пользователя {message.from_user.id}"
    )
    await message.answer(
        'Пожалуйста, нажмите кнопку "Согласен" для продолжения регистрации. <a href="https://parta-works.ru/main_rules">Правила коворкинга</a>.',
        reply_markup=create_agreement_keyboard(),
        parse_mode="HTML",
    )


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
        # GROUP_ID = -1002444417785
        # invite_link = await message.bot.create_chat_invite_link(
        #     chat_id=GROUP_ID,
        #     name="Вступить в группу",
        #     member_limit=1,
        # )
        registration_success = "===✨Вы успешно прошли регистрацию!✨===\n\n"
        registration_info = (
            "💼 <b>PARTA</b> для вашего удобства!<u>\n\n"
            "🛜 Сеть WiFi: <b>Parta</b> Пароль:</u> <code>Parta2024</code>\n\n"
            # f"🔔 <b>Вступайте в нашу группу</b>: <a href='{invite_link}'>PARTA COMMUNITY</a>"
            "🔔 <b>А также подпишитесь на наш новостной канал</b>, чтобы всегда быть в курсе последних обновлений и акций: https://t.me/partacowo"
        )
        success_msg = registration_success + registration_info
        await message.answer(
            success_msg, reply_markup=create_user_keyboard(), parse_mode="HTML"
        )
        logger.info(f"Пользователь {message.from_user.id} успешно зарегистрирован")
        # Отправка уведомления администратору
        if ADMIN_TELEGRAM_ID:
            try:
                notification = (
                    "<b>===👤 Новый резидент ✅ ===</b>\n\n"
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


@router.callback_query(F.data == "info")
async def info(callback_query: CallbackQuery, state: FSMContext) -> None:
    info_message = (
        "💼 <b>PARTA</b> для вашего удобства!<u>\n\n"
        "🛜 Сеть WiFi: <b>Parta</b> Пароль:</u> <code>Parta2024</code>)\n\n"
        # "- 🛠 <b>HelpDesk - оставьте заявку</b> на устранение любой проблемы или просьбы.\n"
        # "- 🖥 <b>Бронирование рабочего места</b> в опенспейсе на выбранную дату с <b>оплатой прямо в боте</b>.\n"
        # "- 📅 <b>Запрос на бронь переговорной</b> для встреч и переговоров.\n"
        # "- 👥 <b>Заявка на приглашение гостя</b> или клиента в ваш офис.\n\n"
        "🔔 <b>Подпишитесь на наш новостной канал</b>, чтобы всегда быть в курсе последних обновлений и акций: <a href='https://t.me/partacowo'>Наш канал</a>"
    )
    await callback_query.message.answer(
        info_message, reply_markup=create_back_keyboard(), parse_mode="HTML"
    )
    await callback_query.answer()


@router.callback_query(F.data == "main_menu")
async def info(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback_query.message.answer(
        f"Выберите действие:",
        reply_markup=create_user_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()


def register_reg_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
