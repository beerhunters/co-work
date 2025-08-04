from typing import Any

from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash

from models.models import Admin

from web.app import db

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)


def init_auth_routes(app: Flask) -> None:
    """Инициализация маршрутов для аутентификации."""

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        """
        Обработка входа администратора.

        Returns:
            Рендеринг страницы логина или редирект на дашборд.
        """
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
    def logout() -> Any:
        """
        Обработка выхода из системы.

        Returns:
            Редирект на страницу логина.
        """
        logout_user()
        logger.info("Админ вышел из системы")
        return redirect(url_for("login"))
