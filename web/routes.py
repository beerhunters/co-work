from datetime import datetime, timedelta
from typing import List, Dict

import pytz
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required
from sqlalchemy import desc
from werkzeug.security import check_password_hash
from aiogram import Bot
import os
import asyncio

from models.models import User, Admin, Notification, Tariff, Booking
from utils.bot_instance import get_bot
from utils.logger import setup_logger
from .app import db

logger = setup_logger(__name__)

MOSCOW_TZ = pytz.timezone("Europe/Moscow")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Инициализация бота для отправки сообщений
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None


def init_routes(app: Flask) -> None:
    """Инициализация маршрутов приложения."""

    def get_unread_notifications_count() -> int:
        """Получение количества непрочитанных уведомлений."""
        count = db.session.query(Notification).filter_by(is_read=0).count()
        logger.info(f"Количество непрочитанных уведомлений: {count}")
        return count

    def get_recent_notifications(limit: int = 5) -> List[Dict]:
        """Возвращает последние уведомления в формате, подходящем для шаблона и AJAX."""
        notifications = (
            db.session.query(Notification)
            .order_by(desc(Notification.created_at))
            .limit(limit)
            .all()
        )

        result = []
        for n in notifications:
            # Определяем тип уведомления и URL для перехода
            notification_type = "general"
            target_url = url_for("notifications")

            if "Новый пользователь:" in n.message:
                notification_type = "user"
                # Извлекаем user_id из notification.user_id
                target_url = url_for("user_detail", user_id=n.user_id)
            elif "Новая бронь" in n.message and n.booking_id:
                notification_type = "booking"
                target_url = url_for("booking_detail", booking_id=n.booking_id)

            result.append(
                {
                    "id": n.id,
                    "message": n.message,
                    "created_at": (
                        n.created_at.strftime("%Y-%m-%d %H:%M")
                        if isinstance(n.created_at, datetime)
                        else n.created_at
                    ),
                    "is_read": bool(n.is_read),
                    "type": notification_type,
                    "target_url": target_url,
                }
            )

        return result

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            login_name = request.form.get("login", "").strip()
            password = request.form.get("password", "")
            user = db.session.query(Admin).filter_by(login=login_name).first()
            if user and check_password_hash(user.password, password):
                login_user(user)
                next_page = request.args.get("next")
                logger.info(f"Успешный вход администратора: {login_name}")
                return redirect(next_page or url_for("dashboard"))
            else:
                logger.error(f"Неудачная попытка входа: логин={login_name}")
                flash("Неверный логин или пароль", "error")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        """Обработка выхода из системы."""
        logout_user()
        logger.info("Админ вышел из системы")
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        """Отображение дашборда."""
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "dashboard.html",
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/users")
    @login_required
    def users():
        """Отображение списка пользователей с пагинацией."""
        page = request.args.get("page", 1, type=int)
        per_page = 10  # Количество записей на странице
        users_pagination = (
            db.session.query(User)
            .order_by(User.reg_date.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "users.html",
            users=users_pagination.items,
            pagination=users_pagination,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/user/<int:user_id>")
    @login_required
    def user_detail(user_id: int):
        """Отображение детальной информации о пользователе."""
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "user_detail.html",
            user=user,
            edit=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/user/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_user(user_id: int):
        """Редактирование пользователя."""
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        if request.method == "POST":
            user.full_name = request.form.get("full_name")
            user.phone = request.form.get("phone")
            user.email = request.form.get("email")
            user.username = request.form.get("username")
            user.successful_bookings = request.form.get("successful_bookings")
            user.language_code = request.form.get("language_code", "ru")
            try:
                db.session.commit()
                flash("Данные пользователя обновлены")
                logger.info(f"Пользователь {user_id} обновлён")
                return redirect(url_for("user_detail", user_id=user_id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при обновлении данных")
                logger.error(f"Ошибка обновления пользователя {user_id}: {str(e)}")
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "user_detail.html",
            user=user,
            edit=True,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/user/<int:user_id>/delete", methods=["POST"])
    @login_required
    def delete_user(user_id: int):
        """Удаление пользователя."""
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        try:
            db.session.delete(user)
            db.session.commit()
            flash("Пользователь удалён")
            logger.info(f"Пользователь {user_id} удалён")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении пользователя")
            logger.error(f"Ошибка удаления пользователя {user_id}: {str(e)}")
        return redirect(url_for("users"))

    @app.route("/tariffs")
    @login_required
    def tariffs():
        """Отображение списка тарифов, отсортированных по ID."""
        tariffs = db.session.query(Tariff).order_by(Tariff.id).all()
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "tariffs.html",
            tariffs=tariffs,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/tariff/<int:tariff_id>")
    @login_required
    def tariff_detail(tariff_id: int):
        """Отображение детальной информации о тарифе."""
        tariff = db.session.get(Tariff, tariff_id)
        if not tariff:
            flash("Тариф не найден")
            return redirect(url_for("tariffs"))
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "tariff_detail.html",
            tariff=tariff,
            edit=False,
            new=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/tariff/<int:tariff_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_tariff(tariff_id: int):
        """Редактирование тарифа."""
        tariff = db.session.get(Tariff, tariff_id)
        if not tariff:
            flash("Тариф не найден")
            return redirect(url_for("tariffs"))
        if request.method == "POST":
            tariff.name = request.form.get("name")
            tariff.description = request.form.get("description")
            tariff.price = float(request.form.get("price"))
            tariff.purpose = request.form.get("purpose") or None
            tariff.service_id = request.form.get("service_id") or None
            tariff.is_active = request.form.get("is_active") == "on"
            try:
                db.session.commit()
                flash("Данные тарифа обновлены")
                logger.info(f"Тариф {tariff_id} обновлён")
                return redirect(url_for("tariff_detail", tariff_id=tariff_id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при обновлении данных")
                logger.error(f"Ошибка обновления тарифа {tariff_id}: {str(e)}")
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "tariff_detail.html",
            tariff=tariff,
            edit=True,
            new=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/tariff/<int:tariff_id>/delete", methods=["POST"])
    @login_required
    def delete_tariff(tariff_id: int):
        """Удаление тарифа."""
        tariff = db.session.get(Tariff, tariff_id)
        if not tariff:
            flash("Тариф не найден")
            return redirect(url_for("tariffs"))
        try:
            db.session.delete(tariff)
            db.session.commit()
            flash("Тариф удалён")
            logger.info(f"Тариф {tariff_id} удалён")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении тарифа")
            logger.error(f"Ошибка удаления тарифа {tariff_id}: {str(e)}")
        return redirect(url_for("tariffs"))

    @app.route("/tariff/new", methods=["GET", "POST"])
    @login_required
    def new_tariff():
        """Создание нового тарифа."""
        if request.method == "POST":
            tariff = Tariff(
                name=request.form.get("name"),
                description=request.form.get("description"),
                price=float(request.form.get("price")),
                purpose=request.form.get("purpose") or None,
                service_id=request.form.get("service_id") or None,
                is_active=request.form.get("is_active") == "on",
            )
            try:
                db.session.add(tariff)
                db.session.commit()
                flash("Тариф создан")
                logger.info(f"Создан новый тариф: {tariff.name}")
                return redirect(url_for("tariff_detail", tariff_id=tariff.id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при создании тарифа")
                logger.error(f"Ошибка создания тарифа: {str(e)}")
        tariff = Tariff(
            name="", description="Описание тарифа", price=0.0, is_active=True
        )
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "tariff_detail.html",
            tariff=tariff,
            edit=True,
            new=True,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/bookings")
    @login_required
    def bookings():
        """Отображение списка бронирований."""
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
    def booking_detail(booking_id: int):
        """Отображение детальной информации о бронировании."""
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
            edit=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/booking/<int:booking_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_booking(booking_id: int):
        """Редактирование бронирования."""
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
    def delete_booking(booking_id: int):
        """Удаление бронирования."""
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

    def send_telegram_message_sync(telegram_id: int, message: str) -> bool:
        """
        Отправляет сообщение пользователю через Telegram в синхронном контексте.

        Args:
            telegram_id: ID пользователя в Telegram.
            message: Текст сообщения.

        Returns:
            bool: True, если сообщение отправлено успешно, иначе False.
        """
        try:
            bot = get_bot()  # Получаем экземпляр бота
            # Используем run_in_executor для выполнения асинхронной функции в синхронном контексте
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(
                bot.send_message(chat_id=telegram_id, text=message)
            )
            loop.close()
            return bool(success)
        except Exception as e:
            logger.error(
                f"Не удалось отправить сообщение пользователю {telegram_id}: {str(e)}"
            )
            return False

    @app.route("/booking/<int:booking_id>/confirm", methods=["POST"])
    @login_required
    def confirm_booking(booking_id: int):
        """Подтверждение бронирования для 'Переговорной'."""
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

            # Отправка сообщения пользователю через Telegram
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

    @app.route("/notifications")
    @login_required
    def notifications():
        """Отображение списка уведомлений."""
        notifications = (
            db.session.query(Notification)
            .order_by(Notification.created_at.desc())
            .all()
        )
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "notifications.html",
            notifications=notifications,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/notifications/mark_all_read", methods=["POST"])
    @login_required
    def mark_all_notifications_read():
        """Пометить все уведомления как прочитанные."""
        try:
            updated = (
                db.session.query(Notification)
                .filter_by(is_read=0)
                .update({"is_read": 1})
            )
            db.session.commit()
            flash(f"Помечено как прочитано: {updated} уведомлений")
            logger.info(f"Помечено как прочитано: {updated} уведомлений")
            return jsonify(
                {
                    "status": "success",
                    "message": "Все уведомления помечены как прочитанные",
                }
            )
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при обновлении уведомлений")
            logger.error(f"Ошибка при пометке уведомлений как прочитанных: {str(e)}")
            return jsonify({"status": "error", "message": "Ошибка сервера"}), 500

    @app.route("/notifications/mark_read/<int:notification_id>", methods=["POST"])
    @login_required
    def mark_notification_read(notification_id: int):
        """Пометить одно уведомление как прочитанное."""
        try:
            notification = db.session.get(Notification, notification_id)
            if not notification:
                logger.warning(f"Уведомление {notification_id} не найдено")
                return (
                    jsonify({"status": "error", "message": "Уведомление не найдено"}),
                    404,
                )
            notification.is_read = 1
            db.session.commit()
            logger.info(f"Уведомление {notification_id} помечено как прочитанное")
            return jsonify(
                {"status": "success", "message": "Уведомление помечено как прочитанное"}
            )
        except Exception as e:
            db.session.rollback()
            logger.error(
                f"Ошибка при пометке уведомления {notification_id} как прочитанного: {str(e)}"
            )
            return jsonify({"status": "error", "message": "Ошибка сервера"}), 500

    @app.route("/notifications/clean_old", methods=["POST"])
    @login_required
    def clean_old_notifications():
        """Удаление прочитанных уведомлений старше 30 дней."""
        try:
            threshold = datetime.now(MOSCOW_TZ) - timedelta(days=30)
            deleted = (
                db.session.query(Notification)
                .filter(Notification.is_read == 1, Notification.created_at < threshold)
                .delete()
            )
            db.session.commit()
            flash(f"Удалено {deleted} старых прочитанных уведомлений")
            logger.info(f"Удалено {deleted} старых прочитанных уведомлений")
            return jsonify(
                {"status": "success", "message": f"Удалено {deleted} уведомлений"}
            )
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при очистке уведомлений")
            logger.error(f"Ошибка при очистке уведомлений: {str(e)}")
            return jsonify({"status": "error", "message": "Ошибка сервера"}), 500

    @app.route("/get_notifications", methods=["GET"])
    @login_required
    def get_notifications():
        """Получение данных об уведомлениях для AJAX."""
        try:
            unread_count = get_unread_notifications_count()
            recent_notifications = get_recent_notifications()
            return jsonify(
                {
                    "unread_count": unread_count,
                    "recent_notifications": recent_notifications,
                }
            )
        except Exception as e:
            logger.error(f"Ошибка получения уведомлений: {str(e)}")
            return jsonify({"error": "Ошибка сервера"}), 500

    @app.route("/flash_message", methods=["POST"])
    @login_required
    def flash_message():
        """Отправляет flash-сообщение через AJAX."""
        try:
            message = request.form.get("message")
            category = request.form.get("category", "info")
            if not message:
                return (
                    jsonify({"status": "error", "message": "Сообщение не указано"}),
                    400,
                )
            flash(message, category)
            return jsonify(
                {"status": "success", "message": "Flash-сообщение добавлено"}
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке flash-сообщения: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/debug_db")
    @login_required
    def debug_db():
        """Отладочный маршрут для проверки таблиц users и notifications."""
        try:
            users = db.session.query(User).all()
            notifications = db.session.query(Notification).all()
            users_data = [
                {
                    "id": user.id,
                    "telegram_id": user.telegram_id,
                    "full_name": user.full_name,
                    "phone": user.phone,
                    "email": user.email,
                    "username": user.username,
                    "reg_date": (
                        user.reg_date.strftime("%Y-%m-%d %H:%M:%S %Z")
                        if user.reg_date
                        else None
                    ),
                }
                for user in users
            ]
            notifications_data = [
                {
                    "id": notification.id,
                    "user_id": notification.user_id,
                    "message": notification.message,
                    "created_at": notification.created_at.strftime(
                        "%Y-%m-%d %H:%M:%S %Z"
                    ),
                    "is_read": notification.is_read,
                }
                for notification in notifications
            ]
            return jsonify({"users": users_data, "notifications": notifications_data})
        except Exception as e:
            logger.error(f"Ошибка отладки БД: {str(e)}")
            return jsonify({"error": "Ошибка сервера"}), 500
