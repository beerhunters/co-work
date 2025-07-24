from datetime import datetime, timedelta
from typing import List, Dict

import pytz
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required
from sqlalchemy import desc
from werkzeug.security import check_password_hash

from models.models import User, Admin, Notification
from utils.logger import setup_logger
from .app import db

logger = setup_logger(__name__)

# logger = logging.getLogger(__name__)
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


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
        return [
            {
                "id": n.id,
                "message": n.message,
                "created_at": (
                    n.created_at.strftime("%Y-%m-%d %H:%M")
                    if isinstance(n.created_at, datetime)
                    else n.created_at
                ),
                "is_read": bool(n.is_read),
            }
            for n in notifications
        ]

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
        """Отображение списка пользователей, отсортированных по дате регистрации."""
        users = db.session.query(User).order_by(User.reg_date.desc()).all()
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "users.html",
            users=users,
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
