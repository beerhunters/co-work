import os
from typing import Optional

from aiogram import Router, Bot, F, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from bot.config import create_user_keyboard, create_back_keyboard
from models.models import (
    create_ticket,
)
from utils.logger import setup_logger

logger = setup_logger(__name__)
router = Router()
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")


class TicketForm(StatesGroup):
    """Состояния для процесса создания заявки."""

    DESCRIPTION = State()
    ASK_PHOTO = State()
    PHOTO = State()


def create_helpdesk_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для Helpdesk.

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой Helpdesk и отмены.
    """
    try:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Создать заявку", callback_data="create_ticket"
                    )
                ],
                [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
            ]
        )
        logger.debug("Создана клавиатура для Helpdesk")
        return keyboard
    except Exception as e:
        logger.error(f"Ошибка при создании клавиатуры Helpdesk: {str(e)}")
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
            ]
        )


def create_photo_choice_keyboard() -> InlineKeyboardMarkup:
    """
    Создаёт клавиатуру для выбора добавления фото.

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками 'Да', 'Нет' и 'Отмена'.
    """
    logger.debug("Создание клавиатуры для выбора добавления фото")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="add_photo"),
                InlineKeyboardButton(text="Нет", callback_data="no_photo"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
        ]
    )
    return keyboard


@router.callback_query(F.data == "helpdesk")
async def start_helpdesk(
    callback_query: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    """
    Обработчик нажатия кнопки 'Helpdesk'. Запрашивает описание проблемы.

    Args:
        callback_query: Callback-запрос от кнопки.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
    """
    await state.set_state(TicketForm.DESCRIPTION)
    await callback_query.message.answer(
        "Опишите вашу проблему или пожелание:",
        reply_markup=create_back_keyboard(),
    )
    logger.info(f"Пользователь {callback_query.from_user.id} начал создание заявки")
    try:
        await callback_query.message.delete()
    except TelegramBadRequest as e:
        logger.warning(
            f"Не удалось удалить сообщение для пользователя {callback_query.from_user.id}: {str(e)}"
        )
    await callback_query.answer()


@router.callback_query(TicketForm.DESCRIPTION, F.data == "cancel")
@router.callback_query(TicketForm.ASK_PHOTO, F.data == "cancel")
@router.callback_query(TicketForm.PHOTO, F.data == "cancel")
async def cancel_ticket_creation(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка отмены создания заявки.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
    """
    await state.clear()
    await callback_query.message.edit_text(
        text="Создание заявки отменено.",
        reply_markup=create_user_keyboard(),
    )
    logger.info(f"Пользователь {callback_query.from_user.id} отменил создание заявки")
    await callback_query.answer()


@router.callback_query(
    F.data == "main_menu",
    TicketForm.DESCRIPTION or TicketForm.ASK_PHOTO or TicketForm.PHOTO,
)
async def cancel_to_main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка возврата в главное меню.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
    """
    await state.clear()
    await callback_query.message.edit_text(
        text="Создание заявки отменено.",
        reply_markup=create_user_keyboard(),
    )
    logger.info(f"Пользователь {callback_query.from_user.id} вернулся в главное меню")
    await callback_query.answer()


@router.message(TicketForm.DESCRIPTION)
async def process_description(message: Message, state: FSMContext) -> None:
    """
    Обработка описания проблемы. Запрашивает добавление фото.

    Args:
        message: Входящее сообщение с описанием.
        state: Контекст состояния FSM.
    """
    description = message.text.strip()
    if not description:
        await message.answer(
            "Описание не может быть пустым. Пожалуйста, введите описание:",
            reply_markup=create_back_keyboard(),
        )
        logger.warning(f"Пользователь {message.from_user.id} ввёл пустое описание")
        return

    await state.update_data(description=description)
    await state.set_state(TicketForm.ASK_PHOTO)
    await message.answer(
        "Хотите прикрепить фото к заявке?",
        reply_markup=create_photo_choice_keyboard(),
    )
    logger.info(f"Пользователь {message.from_user.id} ввёл описание: {description}")


@router.callback_query(TicketForm.ASK_PHOTO, F.data == "add_photo")
async def process_add_photo(callback_query: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка выбора добавления фото.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
    """
    await state.set_state(TicketForm.PHOTO)
    await callback_query.message.edit_text(
        text="Пожалуйста, отправьте фото.",
        reply_markup=create_back_keyboard(),
    )
    logger.info(f"Пользователь {callback_query.from_user.id} выбрал добавление фото")
    await callback_query.answer()


@router.callback_query(TicketForm.ASK_PHOTO, F.data == "no_photo")
async def process_no_photo(
    callback_query: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    """
    Обработка отказа от добавления фото. Создаёт заявку.

    Args:
        callback_query: Callback-запрос.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
    """
    await save_ticket(callback_query.message, state, bot, photo_id=None)
    await callback_query.answer()


@router.message(TicketForm.PHOTO, F.content_type == "photo")
async def process_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    """
    Обработка отправленного фото. Создаёт заявку с фото.

    Args:
        message: Входящее сообщение с фото.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
    """
    photo_id = message.photo[-1].file_id
    await save_ticket(message, state, bot, photo_id)


async def save_ticket(
    message: Message, state: FSMContext, bot: Bot, photo_id: Optional[str]
) -> None:
    """
    Сохраняет заявку в БД и отправляет уведомления.

    Args:
        message: Входящее сообщение.
        state: Контекст состояния FSM.
        bot: Экземпляр бота.
        photo_id: ID фото в Telegram (если есть).
    """
    data = await state.get_data()
    description = data.get("description")
    try:
        ticket, admin_message, session = create_ticket(
            telegram_id=message.from_user.id,
            description=description,
            photo_id=photo_id,
        )
        if not ticket:
            await message.answer(
                admin_message or "Ошибка при создании заявки.",
                reply_markup=create_user_keyboard(),
            )
            logger.warning(
                f"Не удалось создать заявку для пользователя {message.from_user.id}"
            )
            await state.clear()
            return

        try:
            if photo_id:
                await bot.send_photo(
                    chat_id=ADMIN_TELEGRAM_ID,
                    photo=photo_id,
                    caption=admin_message,
                )
            else:
                await bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID,
                    text=admin_message,
                )

            await message.answer(
                f"Заявка #{ticket.id} создана!",
                reply_markup=create_user_keyboard(),
            )
            logger.info(
                f"Заявка #{ticket.id} создана для пользователя {message.from_user.id}, "
                f"photo_id={photo_id or 'без фото'}"
            )
        except Exception as e:
            logger.error(
                f"Ошибка при отправке уведомления для заявки #{ticket.id}: {str(e)}"
            )
            session.rollback()
            await message.answer(
                "Заявка создана, но возникла ошибка при отправке уведомления.",
                reply_markup=create_user_keyboard(),
            )
        finally:
            if session:
                session.close()
    except Exception as e:
        logger.error(
            f"Ошибка при создании заявки для пользователя {message.from_user.id}: {str(e)}"
        )
        await message.answer(
            "Ошибка при создании заявки. Попробуйте позже.",
            reply_markup=create_user_keyboard(),
        )
    finally:
        await state.clear()


def register_ticket_handlers(dp: Dispatcher) -> None:
    """Регистрация обработчиков для тикетов."""
    dp.include_router(router)
