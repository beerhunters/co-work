import os
import re
from datetime import datetime

import pytz
from aiogram import Router, Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv

from bot.config import create_user_keyboard, create_back_keyboard, RULES
from models.models import add_user, check_and_add_user, get_user_by_telegram_id

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)


def format_registration_notification(user, referrer_info=None):
    """Форматирует красивое уведомление о новой регистрации для админа"""

    # Информация о реферере
    referrer_text = ""
    if referrer_info:
        referrer_text = f"""
🔗 <b>Пригласил:</b>
└ {referrer_info.get('username', 'Неизвестно')} (ID: <code>{referrer_info.get('telegram_id', 'Неизвестно')}</code>)"""

    message = f"""🎉 <b>НОВЫЙ ПОЛЬЗОВАТЕЛЬ!</b>

👤 <b>Данные пользователя:</b>
├ <b>Имя:</b> {user.full_name or 'Не указано'}
├ <b>Телефон:</b> <code>{user.phone or 'Не указано'}</code>
├ <b>Email:</b> <code>{user.email or 'Не указано'}</code>
└ <b>Telegram:</b> @{user.username or 'не указан'} (ID: <code>{user.telegram_id}</code>){referrer_text}

⏰ <i>Время регистрации: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}</i>"""

    return message.strip()


load_dotenv()

router = Router()
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
BOT_LINK = os.getenv("BOT_LINK")
INVITE_LINK = os.getenv("INVITE_LINK")
GROUP_ID = os.getenv("GROUP_ID")


def create_register_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для начала регистрации.
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой "Начать регистрацию".
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
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой "Согласен".
    """
    logger.debug("Создание инлайн-клавиатуры для согласия с правилами")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Согласен", callback_data="agree_to_terms")]
        ]
    )
    return keyboard


def create_invite_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для отправки реферальной ссылки с кнопкой шаринга.
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой для шаринга и возврата в меню.
    """
    logger.debug("Создание инлайн-клавиатуры для реферальной ссылки")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Поделиться с другом", callback_data="share_invite"
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )
    return keyboard


class Registration(StatesGroup):
    """Состояния для процесса регистрации."""

    agreement = State()
    full_name = State()
    phone = State()
    email = State()


welcome_message = (
    "🌟 <b>Добро пожаловать в PARTA!</b> 🌟\n\n"
    "Мы рады видеть вас в нашем уютном коворкинге! Этот бот создан, чтобы сделать ваше пребывание комфортным и удобным. Что я умею:\n\n"
    "📍 <i>Бронировать место</i> — выберите тариф и дату для работы в опенспейсе или переговорной, оплатите прямо здесь!\n\n"
    "🛠 <i>Helpdesk</i> — оставьте заявку, если что-то сломалось или нужна помощь.\n\n"
    "❔ <i>Информация</i> — узнайте о Wi-Fi, правилах коворкинга и актуальных новостях.\n\n"
    "🔔 <b>А также подпишитесь на наш новостной канал</b>, чтобы всегда быть в курсе последних обновлений и акций: https://t.me/partacowo"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    Обработчик команды /start с реферальным параметром или без него.

    Args:
        message: Входящее сообщение.
        state: Контекст состояния FSM.
    """
    user_id = message.from_user.id
    text_parts = message.text.split(maxsplit=1)
    logger.info(f"/start от {user_id}, текст: {message.text}")

    await state.clear()

    if not message.from_user:
        logger.warning("Не удалось определить пользователя для команды /start")
        await message.answer("Не удалось определить пользователя.")
        return

    # Извлекаем реферальный ID из команды, если он есть
    ref_id = None
    if len(text_parts) > 1:
        try:
            ref_id = int(text_parts[1])
        except ValueError:
            logger.warning(f"Некорректный реферальный ID в команде: {message.text}")

    result = check_and_add_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        referrer_id=ref_id,
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
        welcome_text = welcome_message
        if ref_id:
            referrer = get_user_by_telegram_id(ref_id)
            referrer_username = (
                f"@{referrer.username}"
                if referrer and referrer.username
                else f"ID {ref_id}"
            )
            welcome_text += f"\n\nВы были приглашены пользователем {referrer_username}!"
        await message.answer(
            welcome_text,
            reply_markup=create_register_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "invite_friend")
async def invite_friend(
    callback_query: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    """
    Обработчик нажатия кнопки 'Поделиться с другом'. Отправляет реферальную ссылку через шаринг.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
    """
    user_id = callback_query.from_user.id
    deeplink = f"{INVITE_LINK}?start={user_id}"
    share_text = (
        f"Присоединяйтесь к PARTA! Уютный коворкинг с удобным бронированием мест. "
        f"Перейдите по ссылке для регистрации: {deeplink}"
    )
    logger.info(
        f"Пользователь {user_id} инициировал шаринг реферальной ссылки: {deeplink}"
    )

    # await callback_query.message.delete()
    await callback_query.message.edit_text(
        # await callback_query.message.answer(
        text="Выберите, с кем поделиться ссылкой:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Поделиться", switch_inline_query=share_text
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
            ]
        ),
        parse_mode="HTML",
    )
    await callback_query.answer()


@router.callback_query(F.data == "start_registration")
async def start_registration(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик нажатия кнопки "Начать регистрацию".
    """
    logger.info(f"Начало регистрации для пользователя {callback_query.from_user.id}")
    await callback_query.message.answer(
        f'Продолжая регистрацию, вы соглашаетесь с обработкой персональных данных и <a href="{RULES}">правилами коворкинга</a>.',
        reply_markup=create_agreement_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()
    await state.set_state(Registration.agreement)


@router.callback_query(F.data == "agree_to_terms")
async def agree_to_terms(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик нажатия кнопки "Согласен".
    """
    logger.info(f"Пользователь {callback_query.from_user.id} согласился с правилами")
    try:
        add_user(telegram_id=callback_query.from_user.id, agreed_to_terms=True)
        await callback_query.answer()
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
    """
    logger.warning(
        f"Некорректный ввод на этапе согласия от пользователя {message.from_user.id}"
    )
    await message.answer(
        f'Пожалуйста, нажмите кнопку "Согласен" для продолжения регистрации. <a href="{RULES}">Правила коворкинга</a>.',
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
    """
    Обработка ввода email и завершение регистрации.

    Args:
        message: Входящее сообщение с email.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
    """
    email = message.text.strip()
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        await message.answer("Неверный формат email. Попробуйте снова:")
        return

    data = await state.get_data()
    full_name = data["full_name"]
    phone = data["phone"]

    try:
        user = get_user_by_telegram_id(message.from_user.id)
        referrer_username = None
        referrer_id = user.referrer_id if user else None
        if user and user.referrer_id:
            referrer = get_user_by_telegram_id(user.referrer_id)
            referrer_username = (
                f"@{referrer.username}"
                if referrer and referrer.username
                else f"ID {user.referrer_id}"
            )

        add_user(
            telegram_id=message.from_user.id,
            full_name=full_name,
            phone=phone,
            email=email,
            username=message.from_user.username,
            reg_date=datetime.now(MOSCOW_TZ),
            referrer_id=referrer_id,  # Передаем referrer_id явно
        )
        # Запрашиваем обновлённого пользователя из базы данных
        user = get_user_by_telegram_id(message.from_user.id)
        if not user:
            logger.error(
                f"Пользователь {message.from_user.id} не найден после обновления"
            )
            await message.answer("Ошибка при регистрации. Попробуйте позже.")
            await state.clear()
            return
        invite_url = "https://t.me/partacowo"  # Fallback-ссылка на случай ошибки
        try:
            invite_link = await bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                name="Вступить в группу",
                member_limit=1,
            )
            invite_url = invite_link.invite_link
            logger.info(f"Создана инвайт-ссылка для группы {GROUP_ID}: {invite_url}")
        except Exception as e:
            logger.error(f"Ошибка создания инвайт-ссылки: {str(e)}")
            # Используем fallback-ссылку на новостной канал
        registration_success = "===✨<i>Регистрация успешна!</i>✨===\n\n"
        registration_info = (
            "💼 <b>PARTA бот</b> для вашего удобства!\n\n"
            "🛜 WiFi: <b>Parta</b>\n"
            "Пароль: <code>Parta2024</code>\n\n"
            f"🔔 <b>Вступайте в нашу группу</b>: <a href='{invite_url}'>PARTA COMMUNITY</a>"
        )
        success_msg = registration_success + registration_info
        await message.answer(
            success_msg, reply_markup=create_user_keyboard(), parse_mode="HTML"
        )
        logger.info(f"Пользователь {message.from_user.id} успешно зарегистрирован")
        # Отправка уведомления администратору
        if ADMIN_TELEGRAM_ID:
            try:
                referrer_info = None
                if referrer_username:
                    referrer_info = {
                        "username": referrer_username,
                        "telegram_id": user.referrer_id,
                    }
                notification = format_registration_notification(
                    user=user, referrer_info=referrer_info
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
    # await callback_query.message.delete()
    info_message = (
        "💼 <b>PARTA бот</b> для вашего удобства!<u>\n\n"
        "🛜 WiFi: <b>Parta</b> Пароль:</u> <code>Parta2024</code>\n\n"
        "- 🛠 <b>HelpDesk - оставьте заявку</b> на устранение любой проблемы или просьбы.\n"
        "- 🖥 <b>Бронирование рабочего места</b> на выбранную дату с <b>оплатой прямо в боте</b>.\n\n"
        "🔔 <b>Подпишитесь на наш новостной канал</b>, чтобы всегда быть в курсе последних обновлений и акций: <a href='https://t.me/partacowo'>Наш канал</a>"
    )
    await callback_query.message.edit_text(
        # await callback_query.message.answer(
        info_message,
        reply_markup=create_back_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()


@router.callback_query(F.data == "main_menu")
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    # await callback_query.message.delete()
    await callback_query.message.edit_text(
        # await callback_query.message.answer(
        f"Выберите действие:",
        reply_markup=create_user_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()


def register_reg_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков."""
    dp.include_router(router)
