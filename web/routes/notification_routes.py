from flask import Flask, render_template, jsonify, flash
from flask_login import login_required
from datetime import datetime, timedelta
from typing import Any
from sqlite3 import OperationalError
import time

from models.models import Notification, Session
from web.routes.utils import get_unread_notifications_count, get_recent_notifications
from web.app import db, MOSCOW_TZ
from utils.logger import setup_logger

logger = setup_logger(__name__)


def init_notification_routes(app: Flask) -> None:
    """
    Инициализация маршрутов для работы с уведомлениями.

    Args:
        app: Экземпляр Flask-приложения.

    Notes:
        Регистрирует маршруты для просмотра, пометки как прочитанных, очистки старых уведомлений
        и полного удаления уведомлений.
    """

    @app.route("/notifications")
    @login_required
    def notifications() -> Any:
        """
        Отображение списка уведомлений.

        Returns:
            Рендеринг шаблона notifications.html с данными уведомлений.

        Notes:
            Асимптотическая сложность: O(n) для выборки всех уведомлений (n — количество уведомлений).
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

        Notes:
            Асимптотическая сложность: O(n) для обновления всех непрочитанных уведомлений.
        """
        try:
            updated = (
                db.session.query(Notification)
                .filter_by(is_read=False)
                .update({"is_read": True})
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

        Notes:
            Асимптотическая сложность: O(1) для обновления одной записи.
        """
        try:
            notification = db.session.get(Notification, notification_id)
            if not notification:
                logger.warning(f"Уведомление {notification_id} не найдено")
                return (
                    jsonify({"status": "error", "message": "Уведомление не найдено"}),
                    404,
                )
            notification.is_read = True
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

        Notes:
            Асимптотическая сложность: O(n) для удаления записей (n — количество уведомлений).
        """
        try:
            threshold = datetime.now(MOSCOW_TZ) - timedelta(days=30)
            deleted = (
                db.session.query(Notification)
                .filter(
                    Notification.is_read is True, Notification.created_at < threshold
                )
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

    @app.route("/notifications/clear", methods=["POST"])
    @login_required
    def clear_notifications() -> Any:
        """
        Очищает все уведомления из базы данных.

        Returns:
            JSON-ответ с результатом операции.

        Notes:
            Выполняет до 3 попыток в случае ошибки "database is locked".
            Асимптотическая сложность: O(n) для удаления всех записей (n — количество уведомлений).
            Память: O(1), так как записи удаляются без загрузки в память.
        """
        session = Session()
        retries = 3
        for attempt in range(retries):
            try:
                deleted = session.query(Notification).delete()
                session.commit()
                logger.info(f"Все уведомления очищены, удалено: {deleted} записей")
                return jsonify(
                    {"status": "success", "message": "Все уведомления удалены"}
                )
            except OperationalError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    session.rollback()
                    time.sleep(0.1)  # Ожидание 100 мс перед повторной попыткой
                    continue
                session.rollback()
                logger.error(f"Ошибка при очистке уведомлений: {str(e)}")
                return (
                    jsonify(
                        {"status": "error", "message": "Ошибка при очистке уведомлений"}
                    ),
                    500,
                )
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка при очистке уведомлений: {str(e)}")
                return jsonify({"status": "error", "message": f"Ошибка: {str(e)}"}), 500
            finally:
                session.close()

    @app.route("/get_notifications", methods=["GET"])
    @login_required
    def get_notifications() -> Any:
        """
        Получение данных об уведомлениях для AJAX.

        Returns:
            JSON-ответ с количеством непрочитанных и последними уведомлениями.

        Notes:
            Асимптотическая сложность: O(n) для выборки последних уведомлений.
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
