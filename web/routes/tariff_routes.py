from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import login_required
from typing import Any

from models.models import Tariff
from web.routes.utils import get_unread_notifications_count, get_recent_notifications
from web.app import db
from utils.logger import setup_logger

logger = setup_logger(__name__)


def init_tariff_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с тарифами."""

    @app.route("/tariffs")
    @login_required
    def tariffs() -> Any:
        """
        Отображение списка тарифов, отсортированных по ID.

        Returns:
            Рендеринг шаблона tariffs.html с данными тарифов.
        """
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
    def tariff_detail(tariff_id: int) -> Any:
        """
        Отображение детальной информации о тарифе.

        Args:
            tariff_id: ID тарифа.

        Returns:
            Рендеринг шаблона tariff_detail.html или редирект.
        """
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
    def edit_tariff(tariff_id: int) -> Any:
        """
        Редактирование тарифа.

        Args:
            tariff_id: ID тарифа.

        Returns:
            Рендеринг шаблона tariff_detail.html или редирект.
        """
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
    def delete_tariff(tariff_id: int) -> Any:
        """
        Удаление тарифа.

        Args:
            tariff_id: ID тарифа.

        Returns:
            Редирект на список тарифов.
        """
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
    def new_tariff() -> Any:
        """
        Создание нового тарифа.

        Returns:
            Рендеринг шаблона tariff_detail.html или редирект.
        """
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
