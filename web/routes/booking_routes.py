from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import login_required
from datetime import datetime, date
from typing import Any, Optional

from models.models import Booking, User, Tariff, Promocode
from web.routes.utils import (
    get_unread_notifications_count,
    get_recent_notifications,
    send_telegram_message_sync,
)
from web.app import db
import pytz

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)

MOSCOW_TZ = pytz.timezone("Europe/Moscow")


def format_booking_confirmation_notification(
    user: User, booking: Booking, tariff: Tariff, promocode: Optional[Promocode] = None
) -> str:
    """
    Форматирует уведомление о подтверждении бронирования для отправки пользователю.

    Args:
        user: Объект пользователя.
        booking: Объект бронирования.
        tariff: Объект тарифа.
        promocode: Объект промокода (если применён, по умолчанию None).

    Returns:
        str: Отформатированное HTML-сообщение для отправки в Telegram.
    """
    tariff_emojis = {
        "meeting": "🤝",
        "workspace": "💼",
        "event": "🎉",
        "office": "🏢",
        "coworking": "💻",
    }

    purpose = tariff.purpose.lower()
    tariff_emoji = tariff_emojis.get(purpose, "📋")
    visit_date = booking.visit_date
    visit_time = booking.visit_time

    if visit_time:
        datetime_str = (
            f"{visit_date.strftime('%d.%m.%Y')} в {visit_time.strftime('%H:%M')}"
        )
    else:
        datetime_str = f"{visit_date.strftime('%d.%m.%Y')} (весь день)"

    discount_info = ""
    if promocode and booking.promocode_id:
        discount_info = f"\n💰 <b>Скидка:</b> {promocode.discount}% (промокод: <code>{promocode.name}</code>)"

    duration_info = ""
    if booking.duration:
        duration_info = f"\n⏱ <b>Длительность:</b> {booking.duration} час(ов)"

    message = f"""✅ <b>Ваша бронь подтверждена!</b> {tariff_emoji}

📋 <b>Детали брони:</b>
├ <b>Тариф:</b> {tariff.name}
├ <b>Дата и время:</b> {datetime_str}{duration_info}
└ <b>Сумма:</b> {booking.amount:.2f} ₽{discount_info}

⏰ <i>Время подтверждения: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}</i>"""

    logger.debug(
        f"Сформировано сообщение о подтверждении брони {booking.id}:\n{message}"
    )
    return message.strip()


def init_booking_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с бронированиями."""

    @app.route("/bookings")
    @login_required
    def bookings() -> Any:
        """
        Отображение списка бронирований с возможностью поиска по имени пользователя и дате визита.

        Returns:
            Рендеринг шаблона bookings.html с отфильтрованными данными бронирований.
        """
        user_query = request.args.get("user_query", "").strip()
        date_query = request.args.get("date_query", "").strip()

        # Базовый запрос для получения бронирований
        query = (
            db.session.query(Booking)
            .join(User)
            .join(Tariff)
            .order_by(Booking.visit_date.desc())
        )

        # Фильтрация по имени пользователя (регистронезависимый частичный поиск)
        if user_query:
            query = query.filter(User.full_name.ilike(f"%{user_query}%"))
            logger.debug(f"Применён фильтр по имени пользователя: {user_query}")

        # Фильтрация по дате визита (точное совпадение)
        if date_query:
            try:
                query_date = datetime.strptime(date_query, "%Y-%m-%d").date()
                query = query.filter(Booking.visit_date == query_date)
                logger.debug(f"Применён фильтр по дате визита: {date_query}")
            except ValueError:
                flash("Неверный формат даты. Используйте YYYY-MM-DD")
                logger.warning(f"Неверный формат даты в запросе: {date_query}")

        bookings = query.all()
        logger.info(f"Найдено {len(bookings)} бронирований после фильтрации")

        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "bookings.html",
            bookings=bookings,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/booking/<int:booking_id>")
    @login_required
    def booking_detail(booking_id: int) -> Any:
        """
        Отображение детальной информации о бронировании.

        Args:
            booking_id: ID бронирования.

        Returns:
            Рендеринг шаблона booking_detail.html или редирект.
        """
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            logger.warning(f"Бронирование {booking_id} не найдено")
            return redirect(url_for("bookings"))

        logger.debug(f"Promocode for booking {booking_id}: {booking.promocode}")
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "booking_detail.html",
            booking=booking,
            user=booking.user,
            tariff=booking.tariff,
            promocode=booking.promocode,
            edit=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/booking/<int:booking_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_booking(booking_id: int) -> Any:
        """
        Редактирование бронирования.

        Args:
            booking_id: ID бронирования.

        Returns:
            Рендеринг шаблона booking_detail.html или редирект.
        """
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            logger.warning(f"Бронирование {booking_id} не найдено")
            return redirect(url_for("bookings"))

        logger.debug(f"Promocode for booking {booking_id}: {booking.promocode}")

        if request.method == "POST":
            try:
                visit_date = request.form.get("visit_date")
                booking.visit_date = datetime.strptime(visit_date, "%Y-%m-%d").date()
                if booking.tariff.purpose == "Переговорная":
                    visit_time = request.form.get("visit_time")
                    booking.visit_time = datetime.strptime(visit_time, "%H:%M").time()
                    booking.duration = int(request.form.get("duration"))
                booking.amount = float(request.form.get("amount"))
                booking.paid = request.form.get("paid") == "on"
                db.session.commit()
                flash("Данные бронирования обновлены")
                logger.info(f"Бронирование {booking_id} обновлено")
                return redirect(url_for("booking_detail", booking_id=booking_id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при обновлении данных")
                logger.error(f"Ошибка обновления бронирования {booking_id}: {str(e)}")

        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "booking_detail.html",
            booking=booking,
            user=booking.user,
            tariff=booking.tariff,
            promocode=booking.promocode,
            edit=True,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/booking/<int:booking_id>/delete", methods=["POST"])
    @login_required
    def delete_booking(booking_id: int) -> Any:
        """
        Удаление бронирования.

        Args:
            booking_id: ID бронирования.

        Returns:
            Редирект на список бронирований.
        """
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            logger.warning(f"Бронирование {booking_id} не найдено")
            return redirect(url_for("bookings"))
        try:
            db.session.delete(booking)
            db.session.commit()
            flash("Бронирование удалено")
            logger.info(f"Бронирование {booking_id} удалено")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении бронирования")
            logger.error(f"Ошибка удаления бронирования {booking_id}: {str(e)}")
        return redirect(url_for("bookings"))

    @app.route("/booking/<int:booking_id>/confirm", methods=["POST"])
    @login_required
    def confirm_booking(booking_id: int) -> Any:
        """
        Подтверждение бронирования для 'Переговорной'.

        Args:
            booking_id: ID бронирования.

        Returns:
            Редирект на страницу бронирования.
        """
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            logger.warning(f"Бронирование {booking_id} не найдено")
            return redirect(url_for("bookings"))

        if booking.confirmed:
            flash("Бронирование уже подтверждено")
            logger.info(f"Бронирование {booking_id} уже подтверждено")
            return redirect(url_for("booking_detail", booking_id=booking_id))

        try:
            booking.confirmed = True
            user = db.session.get(User, booking.user_id)
            tariff = db.session.get(Tariff, booking.tariff_id)
            promocode = (
                db.session.get(Promocode, booking.promocode_id)
                if booking.promocode_id
                else None
            )

            if not user or not tariff:
                flash("Ошибка: пользователь или тариф не найдены")
                logger.error(
                    f"Пользователь {booking.user_id} или тариф {booking.tariff_id} не найдены для брони {booking_id}"
                )
                return redirect(url_for("booking_detail", booking_id=booking_id))

            message = format_booking_confirmation_notification(
                user, booking, tariff, promocode
            )
            success = send_telegram_message_sync(user.telegram_id, message)
            if success:
                logger.info(
                    f"Сообщение о подтверждении брони {booking_id} отправлено пользователю {user.telegram_id}"
                )
            else:
                logger.error(
                    f"Не удалось отправить сообщение пользователю {user.telegram_id} для брони {booking_id}"
                )

            db.session.commit()
            flash("Бронирование подтверждено")
            logger.info(f"Бронирование {booking_id} подтверждено")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при подтверждении бронирования")
            logger.error(f"Ошибка подтверждения бронирования {booking_id}: {str(e)}")
        return redirect(url_for("booking_detail", booking_id=booking_id))
