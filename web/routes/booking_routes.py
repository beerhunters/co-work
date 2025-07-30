from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import login_required
from datetime import datetime
from typing import Any

from models.models import Booking, User, Tariff
from web.routes.utils import (
    get_unread_notifications_count,
    get_recent_notifications,
    send_telegram_message_sync,
)
from web.app import db
from utils.logger import setup_logger

logger = setup_logger(__name__)


def init_booking_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с бронированиями."""

    @app.route("/bookings")
    @login_required
    def bookings() -> Any:
        """
        Отображение списка бронирований.

        Returns:
            Рендеринг шаблона bookings.html с данными бронирований.
        """
        bookings = db.session.query(Booking).order_by(Booking.visit_date.desc()).all()
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
            return redirect(url_for("bookings"))
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
            return redirect(url_for("bookings"))
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
            return redirect(url_for("bookings"))
        if booking.confirmed:
            flash("Бронирование уже подтверждено")
            return redirect(url_for("booking_detail", booking_id=booking_id))
        try:
            booking.confirmed = True
            db.session.commit()
            user = db.session.get(User, booking.user_id)
            tariff = db.session.get(Tariff, booking.tariff_id)
            message = (
                f"Ваша бронь подтверждена!\n"
                f"Тариф: {tariff.name}\n"
                f"Дата: {booking.visit_date}\n"
                f"Время: {booking.visit_time}\n"
                f"Продолжительность: {booking.duration} ч"
            )
            success = send_telegram_message_sync(user.telegram_id, message)
            if success:
                logger.info(
                    f"Сообщение о подтверждении брони {booking_id} отправлено пользователю {user.telegram_id}"
                )
            else:
                logger.error(
                    f"Не удалось отправить сообщение пользователю {user.telegram_id}"
                )
            flash("Бронирование подтверждено")
            logger.info(f"Бронирование {booking_id} подтверждено")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при подтверждении бронирования")
            logger.error(f"Ошибка подтверждения бронирования {booking_id}: {str(e)}")
        return redirect(url_for("booking_detail", booking_id=booking_id))
