from typing import Optional, List
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import login_required, login_user, logout_user, current_user
from models.models import User, Admin
from werkzeug.security import check_password_hash
import logging

logger = logging.getLogger(__name__)


def init_routes(app: Flask) -> None:
    """Инициализация маршрутов Flask."""

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Обработчик страницы логина."""
        if current_user.is_authenticated:
            return redirect(url_for("users"))

        if request.method == "POST":
            login = request.form.get("login")
            password = request.form.get("password")
            user = (
                app.extensions["sqlalchemy"]
                .db.session.query(Admin)
                .filter_by(login=login)
                .first()
            )

            if user and check_password_hash(user.password, password):
                login_user(user)
                logger.info(f"Админ {login} вошел в систему")
                return redirect(url_for("users"))
            flash("Неверный логин или пароль")

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        """Обработчик выхода из системы."""
        logger.info(f"Админ {current_user.login} вышел из системы")
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def users():
        """Список всех пользователей."""
        users = app.extensions["sqlalchemy"].db.session.query(User).all()
        return render_template("users.html", users=users)

    @app.route("/user/<int:user_id>")
    @login_required
    def user_detail(user_id: int):
        """Детальная информация о пользователе."""
        user = app.extensions["sqlalchemy"].db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        return render_template("user_detail.html", user=user)

    @app.route("/user/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_user(user_id: int):
        """Редактирование данных пользователя."""
        user = app.extensions["sqlalchemy"].db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))

        if request.method == "POST":
            try:
                user.full_name = request.form.get("full_name")
                user.phone = request.form.get("phone")
                user.email = request.form.get("email")
                app.extensions["sqlalchemy"].db.session.commit()
                flash("Данные пользователя обновлены")
                logger.info(f"Данные пользователя {user_id} обновлены")
                return redirect(url_for("users"))
            except Exception as e:
                flash("Ошибка при обновлении данных")
                logger.error(f"Ошибка при обновлении пользователя {user_id}: {str(e)}")

        return render_template("user_detail.html", user=user, edit=True)

    @app.route("/user/<int:user_id>/delete", methods=["POST"])
    @login_required
    def delete_user(user_id: int):
        """Удаление пользователя."""
        user = app.extensions["sqlalchemy"].db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))

        try:
            app.extensions["sqlalchemy"].db.session.delete(user)
            app.extensions["sqlalchemy"].db.session.commit()
            flash("Пользователь удален")
            logger.info(f"Пользователь {user_id} удален")
        except Exception as e:
            flash("Ошибка при удалении пользователя")
            logger.error(f"Ошибка при удалении пользователя {user_id}: {str(e)}")
        return redirect(url_for("users"))
