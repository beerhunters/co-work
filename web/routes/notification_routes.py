from flask import Flask, render_template, jsonify, flash, request
from flask_login import login_required
from datetime import datetime, timedelta
from typing import Any, Dict, List
from sqlite3 import OperationalError
import time
import uuid

from models.models import Notification, Session
from web.routes.utils import get_unread_notifications_count, get_recent_notifications
from web.app import db, MOSCOW_TZ

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)


def init_notification_routes(app: Flask) -> None:
    """
    Инициализация маршрутов для работы с уведомлениями.

    Args:
        app: Экземпляр Flask приложения.

    Notes:
        Асимптотическая сложность: O(1) для регистрации маршрутов.
    """

    @app.route("/notifications")
    @login_required
    def notifications() -> Any:
        """Отображение списка уведомлений."""
        try:
            notifications = (
                db.session.query(Notification)
                .order_by(Notification.created_at.desc())
                .all()
            )
            unread_notifications = get_unread_notifications_count()
            recent_notifications = get_recent_notifications()

            logger.info(
                f"Загрузка страницы уведомлений: {len(notifications)} уведомлений"
            )
            return render_template(
                "notifications.html",
                notifications=notifications,
                unread_notifications=unread_notifications,
                recent_notifications=recent_notifications,
            )
        except Exception as e:
            logger.error(f"Ошибка при загрузке страницы уведомлений: {str(e)}")
            flash("Ошибка при загрузке уведомлений", "error")
            return render_template(
                "notifications.html",
                notifications=[],
                unread_notifications=0,
                recent_notifications=[],
            )

    @app.route("/get_notifications", methods=["GET"])
    @login_required
    def get_notifications() -> Any:
        """
        Получение данных об уведомлениях для AJAX.

        Args:
            since_id (optional): ID последнего уведомления для получения только новых.

        Returns:
            JSON с количеством непрочитанных уведомлений и списком последних уведомлений.

        Notes:
            Асимптотическая сложность: O(n) для выборки уведомлений, где n — число уведомлений.
            Обрабатывает как объекты Notification, так и словари от get_recent_notifications.
        """
        try:
            request_id = str(uuid.uuid4())
            logger.debug(f"Запрос на получение уведомлений, ID: {request_id}")
            since_id = request.args.get("since_id", type=int)

            unread_count = get_unread_notifications_count()
            if since_id:
                recent_notifications = (
                    db.session.query(Notification)
                    .filter(Notification.id > since_id)
                    .order_by(Notification.created_at.desc())
                    .limit(10)
                    .all()
                )
            else:
                recent_notifications = get_recent_notifications()

            if not isinstance(recent_notifications, list):
                logger.warning(
                    f"recent_notifications не является списком: {type(recent_notifications)}"
                )
                recent_notifications = []

            formatted_notifications = []
            for notification in recent_notifications:
                try:
                    is_dict = isinstance(notification, dict)

                    if is_dict:
                        # Если это словарь (от get_recent_notifications), используем его поля
                        formatted_notification = {
                            "id": notification.get("id"),
                            "message": notification.get("message", ""),
                            "type": notification.get("type", "info"),
                            "is_read": notification.get("is_read", False),
                            "user_id": notification.get("user_id"),
                            "booking_id": notification.get("booking_id"),
                            "ticket_id": notification.get("ticket_id"),
                            "target_url": notification.get("target_url", "#"),
                            "created_at": notification.get("created_at", "Неизвестно"),
                        }
                    else:
                        # Если это объект Notification (от since_id)
                        target_url = "/notifications"
                        if notification.user_id:
                            target_url = f"/user/{notification.user_id}"
                        elif notification.booking_id:
                            target_url = f"/booking/{notification.booking_id}"
                        elif notification.ticket_id:
                            target_url = f"/ticket/{notification.ticket_id}"

                        formatted_notification = {
                            "id": getattr(notification, "id", None),
                            "message": getattr(notification, "message", ""),
                            "type": "info",  # Модель Notification не содержит поле type
                            "is_read": getattr(notification, "is_read", False),
                            "user_id": getattr(notification, "user_id", None),
                            "booking_id": getattr(notification, "booking_id", None),
                            "ticket_id": getattr(notification, "ticket_id", None),
                            "target_url": target_url,
                            "created_at": (
                                notification.created_at.strftime("%Y-%m-%d %H:%M")
                                if hasattr(notification, "created_at")
                                and notification.created_at
                                else "Неизвестно"
                            ),
                        }
                    formatted_notifications.append(formatted_notification)
                except Exception as e:
                    logger.warning(f"Ошибка форматирования уведомления: {str(e)}")
                    continue

            response_data = {
                "unread_count": int(unread_count) if unread_count is not None else 0,
                "recent_notifications": formatted_notifications,
                "status": "success",
            }

            logger.debug(
                f"Отправляем данные (ID: {request_id}): unread_count={response_data['unread_count']}, notifications_count={len(formatted_notifications)}"
            )
            return jsonify(response_data)

        except Exception as e:
            logger.error(f"Ошибка получения уведомлений (ID: {request_id}): {str(e)}")
            return (
                jsonify(
                    {
                        "error": "Ошибка сервера",
                        "unread_count": 0,
                        "recent_notifications": [],
                        "status": "error",
                        "message": str(e),
                    }
                ),
                500,
            )

    @app.route("/notifications/mark_read/<int:notification_id>", methods=["POST"])
    @login_required
    def mark_notification_read(notification_id: int) -> Any:
        """
        Пометить одно уведомление как прочитанное.

        Args:
            notification_id: ID уведомления.

        Returns:
            JSON с результатом операции.

        Notes:
            Асимптотическая сложность: O(1).
        """
        try:
            logger.debug(f"Помечаем уведомление {notification_id} как прочитанное")
            notification = db.session.get(Notification, notification_id)
            if not notification:
                logger.warning(f"Уведомление {notification_id} не найдено")
                return (
                    jsonify({"status": "error", "message": "Уведомление не найдено"}),
                    404,
                )

            if notification.is_read:
                logger.info(f"Уведомление {notification_id} уже прочитано")
                return jsonify(
                    {"status": "success", "message": "Уведомление уже было прочитано"}
                )

            notification.is_read = True
            db.session.commit()

            logger.info(f"Уведомление {notification_id} помечено как прочитанное")
            return jsonify(
                {"status": "success", "message": "Уведомление помечено как прочитанное"}
            )

        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при пометке уведомления {notification_id}: {str(e)}")
            return (
                jsonify({"status": "error", "message": f"Ошибка сервера: {str(e)}"}),
                500,
            )

    @app.route("/notifications/mark_all_read", methods=["POST"])
    @login_required
    def mark_all_notifications_read() -> Any:
        """
        Пометить все уведомления как прочитанные.

        Returns:
            JSON с результатом операции.

        Notes:
            Асимптотическая сложность: O(n), где n — число непрочитанных уведомлений.
        """
        try:
            logger.debug("Помечаем все уведомления как прочитанные")
            updated = (
                db.session.query(Notification)
                .filter_by(is_read=False)
                .update({"is_read": True})
            )
            db.session.commit()

            logger.info(f"Помечено как прочитано: {updated} уведомлений")
            message = (
                f"Помечено как прочитано: {updated} уведомлений"
                if updated > 0
                else "Нет непрочитанных уведомлений"
            )

            return jsonify(
                {"status": "success", "message": message, "updated_count": updated}
            )

        except Exception as e:
            db.session.rollback()
            logger.error(
                f"Ошибка при пометке всех уведомлений как прочитанных: {str(e)}"
            )
            flash("Ошибка при обновлении уведомлений", "error")
            return (
                jsonify({"status": "error", "message": f"Ошибка сервера: {str(e)}"}),
                500,
            )

    @app.route("/notifications/clean_old", methods=["POST"])
    @login_required
    def clean_old_notifications() -> Any:
        """
        Удаление прочитанных уведомлений старше 30 дней.

        Returns:
            JSON с результатом операции.

        Notes:
            Асимптотическая сложность: O(n), где n — число уведомлений.
        """
        try:
            threshold = datetime.now(MOSCOW_TZ) - timedelta(days=30)
            deleted = (
                db.session.query(Notification)
                .filter(
                    Notification.is_read == True, Notification.created_at < threshold
                )
                .delete()
            )
            db.session.commit()

            logger.info(f"Удалено {deleted} старых прочитанных уведомлений")
            flash(f"Удалено {deleted} старых прочитанных уведомлений", "success")

            return jsonify(
                {"status": "success", "message": f"Удалено {deleted} уведомлений"}
            )

        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при очистке уведомлений: {str(e)}")
            flash("Ошибка при очистке уведомлений", "error")
            return (
                jsonify({"status": "error", "message": f"Ошибка сервера: {str(e)}"}),
                500,
            )

    @app.route("/notifications/clear", methods=["POST"])
    @login_required
    def clear_notifications() -> Any:
        """
        Очищает все уведомления из базы данных.

        Returns:
            JSON с результатом операции.

        Notes:
            Асимптотическая сложность: O(n), где n — число уведомлений.
        """
        retries = 3
        for attempt in range(retries):
            session = Session()
            try:
                deleted = session.query(Notification).delete()
                session.commit()
                logger.info(f"Все уведомления очищены, удалено: {deleted} записей")
                return jsonify(
                    {"status": "success", "message": f"Удалено {deleted} уведомлений"}
                )
            except OperationalError as e:
                session.rollback()
                if "database is locked" in str(e) and attempt < retries - 1:
                    logger.warning(
                        f"База заблокирована, попытка {attempt + 1}/{retries}"
                    )
                    time.sleep(0.1 * (attempt + 1))
                    continue
                logger.error(f"Ошибка блокировки БД при очистке уведомлений: {str(e)}")
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "База данных временно недоступна",
                        }
                    ),
                    500,
                )
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка при очистке уведомлений: {str(e)}")
                return (
                    jsonify({"status": "error", "message": f"Ошибка: {str(e)}"}),
                    500,
                )
            finally:
                session.close()
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Не удалось выполнить операцию после нескольких попыток",
                }
            ),
            500,
        )

    @app.route("/notifications/check_new", methods=["GET"])
    @login_required
    def check_new_notifications() -> Dict[str, Any]:
        """
        Проверяет наличие новых уведомлений.

        Returns:
            JSON с количеством непрочитанных уведомлений и последними 5 уведомлениями,
            включая target_url для перехода.

        Example:
            >>> curl http://localhost:5000/notifications/check_new
            {
                "status": "success",
                "unread_count": 2,
                "has_new": true,
                "recent_notifications": [
                    {
                        "id": 1,
                        "message": "Новая заявка #456",
                        "created_at": "2025-08-04 12:34",
                        "is_read": false,
                        "type": "ticket",
                        "target_url": "/ticket/456"
                    },
                    ...
                ]
            }
        """
        try:
            unread_count = get_unread_notifications_count()
            logger.debug(f"Количество непрочитанных уведомлений: {unread_count}")
            recent_notifications = get_recent_notifications(limit=5)

            # Формируем target_url для каждого уведомления, если его нет
            for notification in recent_notifications:
                if "target_url" not in notification:
                    if notification.get("type") == "user" and notification.get(
                        "user_id"
                    ):
                        notification["target_url"] = f"/user/{notification['user_id']}"
                    elif notification.get("type") == "booking" and notification.get(
                        "booking_id"
                    ):
                        notification["target_url"] = (
                            f"/booking/{notification['booking_id']}"
                        )
                    elif notification.get("type") == "ticket" and notification.get(
                        "ticket_id"
                    ):
                        notification["target_url"] = (
                            f"/ticket/{notification['ticket_id']}"
                        )
                    else:
                        notification["target_url"] = "#"

            logger.debug(f"Последние уведомления: {recent_notifications}")
            response_data = {
                "status": "success",
                "unread_count": int(unread_count) if unread_count is not None else 0,
                "has_new": unread_count > 0,
                "recent_notifications": recent_notifications,
            }
            logger.debug(f"Ответ /check_new_notifications: {response_data}")
            return jsonify(response_data)
        except Exception as e:
            logger.error(f"Ошибка проверки уведомлений: {str(e)}")
            response_data = {"status": "error", "message": f"Ошибка сервера: {str(e)}"}
            return jsonify(response_data), 500
