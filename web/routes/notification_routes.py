from flask import Flask, render_template, jsonify, flash
from flask_login import login_required
from datetime import datetime, timedelta
from typing import Any

from models.models import Notification
from web.routes.utils import get_unread_notifications_count, get_recent_notifications
from web.app import db, MOSCOW_TZ
from utils.logger import setup_logger

logger = setup_logger(__name__)


def init_notification_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с уведомлениями."""

    @app.route("/notifications")
    @login_required
    def notifications() -> Any:
        """
        Отображение списка уведомлений.

        Returns:
            Рендеринг шаблона notifications.html с данными уведомлений.
        """
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
    def mark_all_notifications_read() -> Any:
        """
        Пометить все уведомления как прочитанные.

        Returns:
            JSON-ответ с результатом операции.
        """
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
    def mark_notification_read(notification_id: int) -> Any:
        """
        Пометить одно уведомление как прочитанное.

        Args:
            notification_id: ID уведомления.

        Returns:
            JSON-ответ с результатом операции.
        """
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
    def clean_old_notifications() -> Any:
        """
        Удаление прочитанных уведомлений старше 30 дней.

        Returns:
            JSON-ответ с результатом операции.
        """
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
    def get_notifications() -> Any:
        """
        Получение данных об уведомлениях для AJAX.

        Returns:
            JSON-ответ с количеством непрочитанных и последними уведомлениями.
        """
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
