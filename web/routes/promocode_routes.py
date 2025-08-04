from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import login_required
from datetime import datetime
from typing import Any

from models.models import Promocode
from web.routes.utils import get_unread_notifications_count, get_recent_notifications
from web.app import db

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)


def init_promocode_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с промокодами."""

    @app.route("/promocodes")
    @login_required
    def promocodes() -> Any:
        """
        Отображение списка промокодов, отсортированных по ID.

        Returns:
            Рендеринг шаблона promocodes.html с данными промокодов.
        """
        promocodes = db.session.query(Promocode).order_by(Promocode.id).all()
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        logger.info(f"Отображен список промокодов, всего: {len(promocodes)}")
        return render_template(
            "promocodes.html",
            promocodes=promocodes,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/promocode/<int:promocode_id>")
    @login_required
    def promocode_detail(promocode_id: int) -> Any:
        """
        Отображение детальной информации о промокоде.

        Args:
            promocode_id: ID промокода.

        Returns:
            Рендеринг шаблона promocode_detail.html или редирект.
        """
        promocode = db.session.get(Promocode, promocode_id)
        if not promocode:
            flash("Промокод не найден")
            logger.warning(f"Промокод с ID {promocode_id} не найден")
            return redirect(url_for("promocodes"))
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        logger.info(f"Отображена детальная информация о промокоде ID {promocode_id}")
        return render_template(
            "promocode_detail.html",
            promocode=promocode,
            edit=False,
            new=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/promocode/<int:promocode_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_promocode(promocode_id: int) -> Any:
        """
        Редактирование промокода.

        Args:
            promocode_id: ID промокода.

        Returns:
            Рендеринг шаблона promocode_detail.html или редирект.
        """
        promocode = db.session.get(Promocode, promocode_id)
        if not promocode:
            flash("Промокод не найден")
            logger.warning(f"Промокод с ID {promocode_id} не найден")
            return redirect(url_for("promocodes"))
        if request.method == "POST":
            try:
                promocode.name = request.form.get("name")
                promocode.discount = int(request.form.get("discount"))
                promocode.usage_quantity = int(request.form.get("usage_quantity"))
                expiration_date = request.form.get("expiration_date")
                promocode.expiration_date = (
                    datetime.strptime(expiration_date, "%Y-%m-%d %H:%M")
                    if expiration_date
                    else None
                )
                promocode.is_active = request.form.get("is_active") == "on"
                db.session.commit()
                flash("Данные промокода обновлены")
                logger.info(f"Промокод {promocode_id} обновлён")
                return redirect(url_for("promocode_detail", promocode_id=promocode_id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при обновлении данных")
                logger.error(f"Ошибка обновления промокода {promocode_id}: {str(e)}")
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "promocode_detail.html",
            promocode=promocode,
            edit=True,
            new=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/promocode/<int:promocode_id>/delete", methods=["POST"])
    @login_required
    def delete_promocode(promocode_id: int) -> Any:
        """
        Удаление промокода.

        Args:
            promocode_id: ID промокода.

        Returns:
            Редирект на список промокодов.
        """
        promocode = db.session.get(Promocode, promocode_id)
        if not promocode:
            flash("Промокод не найден")
            logger.warning(f"Промокод с ID {promocode_id} не найден")
            return redirect(url_for("promocodes"))
        try:
            db.session.delete(promocode)
            db.session.commit()
            flash("Промокод удалён")
            logger.info(f"Промокод {promocode_id} удалён")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении промокода")
            logger.error(f"Ошибка удаления промокода {promocode_id}: {str(e)}")
        return redirect(url_for("promocodes"))

    @app.route("/promocode/new", methods=["GET", "POST"])
    @login_required
    def new_promocode() -> Any:
        """
        Создание нового промокода.

        Returns:
            Рендеринг шаблона promocode_detail.html или редирект.
        """
        if request.method == "POST":
            try:
                promocode = Promocode(
                    name=request.form.get("name"),
                    discount=int(request.form.get("discount")),
                    usage_quantity=int(request.form.get("usage_quantity")),
                    expiration_date=(
                        datetime.strptime(
                            request.form.get("expiration_date"), "%Y-%m-%d %H:%M"
                        )
                        if request.form.get("expiration_date")
                        else None
                    ),
                    is_active=request.form.get("is_active") == "on",
                )
                db.session.add(promocode)
                db.session.commit()
                flash("Промокод создан")
                logger.info(f"Создан новый промокод: {promocode.name}")
                return redirect(url_for("promocode_detail", promocode_id=promocode.id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при создании промокода")
                logger.error(f"Ошибка создания промокода: {str(e)}")
        promocode = Promocode(name="", discount=0, usage_quantity=0, is_active=True)
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "promocode_detail.html",
            promocode=promocode,
            edit=True,
            new=True,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )
