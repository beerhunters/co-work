import asyncio
import os
from datetime import datetime
from typing import Optional, Tuple

import aiohttp
import pytz
from dotenv import load_dotenv
from yookassa import Payment, Configuration

from utils.logger import setup_logger

logger = setup_logger(__name__)
load_dotenv()

# Конфигурация YooKassa
Configuration.account_id = os.getenv("YOKASSA_ACCOUNT_ID")
Configuration.secret_key = os.getenv("YOKASSA_SECRET_KEY")


# Конфигурация Rubitime
RUBITIME_API_KEY = os.getenv("RUBITIME_API_KEY")
RUBITIME_BASE_URL = "https://rubitime.ru/api2/"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


async def rubitime(method: str, extra_params: dict) -> Optional[str]:
    """
    Выполнение запроса к Rubitime API.

    Args:
        method: Метод API ('create_record', 'update_record', 'get_record', 'remove_record').
        extra_params: Дополнительные параметры для запроса.

    Returns:
        Optional[str]: ID записи (для create_record) или None.
    """
    if method == "create_record":
        url = f"{RUBITIME_BASE_URL}create-record"
        params = {
            "branch_id": 12595,
            "cooperator_id": 25786,
            "created_at": datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "status": 0,
            "source": "Telegram",
            **extra_params,
        }
    else:
        logger.error(f"Неизвестный метод Rubitime: {method}")
        return None

    params["rk"] = RUBITIME_API_KEY

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "ok":
                        if method == "create_record":
                            record_id = data.get("data", {}).get("id")
                            logger.debug(f"Создано в Rubitime: ID {record_id}")
                            return record_id
                        logger.debug(f"Запрос Rubitime успешен: {method}")
                        return None
                    else:
                        logger.warning(
                            f"Ошибка Rubitime: {data.get('message', 'Неизвестная ошибка')}"
                        )
                        return None
                else:
                    logger.error(
                        f"Ошибка HTTP {response.status}: {await response.text()}"
                    )
                    return None
        except Exception as e:
            logger.error(f"Исключение при запросе к Rubitime: {str(e)}")
            return None


async def create_payment(
    description: str, amount: float
) -> Tuple[Optional[str], Optional[str]]:
    """
    Создание платежа через YooKassa.

    Args:
        description: Описание платежа.
        amount: Сумма платежа.

    Returns:
        Tuple[Optional[str], Optional[str]]: ID платежа и URL для оплаты или (None, None) при ошибке.
    """
    try:
        payment = Payment.create(
            {
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "confirmation": {
                    "type": "redirect",
                    "return_url": os.getenv("BOT_LINK", "https://t.me/your_bot"),
                },
                "capture": True,
                "description": description,
            }
        )
        logger.debug(
            f"Платёж создан: id={payment.id}, url={payment.confirmation.confirmation_url}"
        )
        return payment.id, payment.confirmation.confirmation_url
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {str(e)}")
        return None, None


async def check_payment_status(payment_id: str) -> Optional[str]:
    """
    Проверка статуса платежа через YooKassa.

    Args:
        payment_id: ID платежа.

    Returns:
        Optional[str]: Статус платежа ('succeeded', 'canceled', etc.) или None при ошибке.
    """
    try:
        payment = await asyncio.get_event_loop().run_in_executor(
            None, Payment.find_one, payment_id
        )
        return payment.status
    except Exception as e:
        logger.error(f"Ошибка проверки статуса платежа {payment_id}: {str(e)}")
        return None
