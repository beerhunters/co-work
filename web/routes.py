from typing import Optional
from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from models.models import User, Admin, Notification
from web.app import db
import logging

logger = logging.getLogger(__name__)


def init_routes(app: Flask) -> None:
    """Инициализация маршрутов приложения."""

    def get_unread_notifications_count() -> int:
        """Получение количества непрочитанных уведомлений."""
        return db.session.query(Notification).filter_by(is_read=0).count()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Обработка входа в систему."""
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            login = request.form.get("login")
            password = request.form.get("password")
            user = db.session.query(Admin).filter_by(login=login).first()
            if user and check_password_hash(user.password, password):
                login_user(user)
                logger.info(f"Админ {login} вошёл в систему")
                return redirect(url_for("dashboard"))
            flash("Неверный логин или пароль")
            logger.warning(f"Неудачная попытка входа для логина {login}")
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
        return render_template(
            "dashboard.html", unread_notifications=unread_notifications
        )

    @app.route("/users")
    @login_required
    def users():
        """Отображение списка пользователей, отсортированных по дате регистрации."""
        users = db.session.query(User).order_by(User.reg_date.desc()).all()
        unread_notifications = get_unread_notifications_count()
        return render_template(
            "users.html", users=users, unread_notifications=unread_notifications
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
        return render_template(
            "user_detail.html",
            user=user,
            edit=False,
            unread_notifications=unread_notifications,
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
        return render_template(
            "user_detail.html",
            user=user,
            edit=True,
            unread_notifications=unread_notifications,
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
        return render_template(
            "notifications.html",
            notifications=notifications,
            unread_notifications=unread_notifications,
        )

    @app.route("/notifications/mark_all_read", methods=["POST"])
    @login_required
    def mark_all_notifications_read():
        """Пометить все уведомления как прочитанные."""
        try:
            db.session.query(Notification).filter_by(is_read=0).update({"is_read": 1})
            db.session.commit()
            flash("Все уведомления помечены как прочитанные")
            logger.info("Все уведомления помечены как прочитанные")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при обновлении уведомлений")
            logger.error(f"Ошибка при пометке уведомлений как прочитанных: {str(e)}")
        return redirect(url_for("notifications"))
