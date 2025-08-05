import time
import uuid
from datetime import datetime, timedelta
from sqlite3 import OperationalError
from typing import Any, Dict

from flask import Flask, render_template, jsonify, flash, request
from flask_login import login_required

from models.models import Notification, Session
from utils.logger import get_logger
from web.app import db, MOSCOW_TZ
from web.routes.utils import get_unread_notifications_count, get_recent_notifications

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
        """
        Отображение списка уведомлений с пагинацией.

        Args:
            page (optional): Номер страницы (по умолчанию 1).

        Returns:
            Рендеринг шаблона notifications.html с пагинированным списком уведомлений.

        Notes:
            Асимптотическая сложность: O(n) для выборки уведомлений, где n — общее число уведомлений.
        """
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 15
            pagination = (
                db.session.query(Notification)
                .order_by(Notification.created_at.desc())
                .paginate(page=page, per_page=per_page, error_out=False)
            )
            notifications = pagination.items
            unread_notifications = get_unread_notifications_count()
            recent_notifications = [
                {
                    "id": n.id,
                    "message": n.message,
                    "is_read": n.is_read,
                    "user_id": n.user_id,
                    "booking_id": n.booking_id,
                    "ticket_id": n.ticket_id,
                    "type": (
                        "ticket"
                        if n.ticket_id
                        else (
                            "booking"
                            if n.booking_id
                            else "user" if n.user_id else "info"
                        )
                    ),
                    "target_url": (
                        f"/ticket/{n.ticket_id}"
                        if n.ticket_id
                        else (
                            f"/booking/{n.booking_id}"
                            if n.booking_id
                            else f"/user/{n.user_id}" if n.user_id else "#"
                        )
                    ),
                    "created_at": (
                        n.created_at.strftime("%Y-%m-%d %H:%M")
                        if n.created_at
                        else "Неизвестно"
                    ),
                }
                for n in notifications
            ]

            logger.info(
                f"Загрузка страницы уведомлений: {len(notifications)} уведомлений, страница {page}"
            )
            return render_template(
                "notifications.html",
                notifications=notifications,
                unread_notifications=unread_notifications,
                recent_notifications=recent_notifications,
                pagination=pagination,
            )
        except Exception as e:
            logger.error(f"Ошибка при загрузке страницы уведомлений: {str(e)}")
            flash("Ошибка при загрузке уведомлений", "error")
            return render_template(
                "notifications.html",
                notifications=[],
                unread_notifications=0,
                recent_notifications=[],
                pagination=None,
            )

    @app.route("/get_notifications", methods=["GET"])
    @login_required
    def get_notifications() -> Any:
        """
        Получение данных об уведомлениях для AJAX с пагинацией.

        Args:
            since_id (optional): ID последнего уведомления для получения только новых.
            page (optional): Номер страницы (по умолчанию 1).

        Returns:
            JSON с количеством непрочитанных уведомлений и списком последних уведомлений.

        Notes:
            Асимптотическая сложность: O(n) для выборки уведомлений, где n — число уведомлений на странице.
        """
        try:
            request_id = str(uuid.uuid4())
            logger.debug(f"Запрос на получение уведомлений, ID: {request_id}")
            since_id = request.args.get("since_id", type=int)
            page = request.args.get("page", 1, type=int)
            per_page = 15

            unread_count = get_unread_notifications_count()
            if since_id:
                recent_notifications = (
                    db.session.query(Notification)
                    .filter(Notification.id > since_id)
                    .order_by(Notification.created_at.desc())
                    .limit(per_page)
                    .all()
                )
            else:
                pagination = (
                    db.session.query(Notification)
                    .order_by(Notification.created_at.desc())
                    .paginate(page=page, per_page=per_page, error_out=False)
                )
                recent_notifications = pagination.items

            formatted_notifications = []
            for notification in recent_notifications:
                try:
                    formatted_notification = {
                        "id": notification.id,
                        "message": notification.message,
                        "is_read": notification.is_read,
                        "user_id": notification.user_id,
                        "booking_id": notification.booking_id,
                        "ticket_id": notification.ticket_id,
                        "type": (
                            "ticket"
                            if notification.ticket_id
                            else (
                                "booking"
                                if notification.booking_id
                                else "user" if notification.user_id else "info"
                            )
                        ),
                        "target_url": (
                            f"/ticket/{notification.ticket_id}"
                            if notification.ticket_id
                            else (
                                f"/booking/{notification.booking_id}"
                                if notification.booking_id
                                else (
                                    f"/user/{notification.user_id}"
                                    if notification.user_id
                                    else "#"
                                )
                            )
                        ),
                        "created_at": (
                            notification.created_at.strftime("%Y-%m-%d %H:%M")
                            if notification.created_at
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
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_pages": (
                        pagination.total // per_page
                        + (1 if pagination.total % per_page else 0)
                        if not since_id
                        else 1
                    ),
                    "total_items": (
                        pagination.total
                        if not since_id
                        else len(formatted_notifications)
                    ),
                },
            }

            logger.debug(
                f"Отправляем данные (ID: {request_id}): unread_count={response_data['unread_count']}, notifications_count={len(formatted_notifications)}, page={page}"
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
                        "pagination": {
                            "page": 1,
                            "per_page": 15,
                            "total_pages": 1,
                            "total_items": 0,
                        },
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

            for notification in recent_notifications:
                if "target_url" not in notification:
                    notification["type"] = (
                        "ticket"
                        if notification.get("ticket_id")
                        else (
                            "booking"
                            if notification.get("booking_id")
                            else "user" if notification.get("user_id") else "info"
                        )
                    )
                    notification["target_url"] = (
                        f"/ticket/{notification['ticket_id']}"
                        if notification.get("ticket_id")
                        else (
                            f"/booking/{notification['booking_id']}"
                            if notification.get("booking_id")
                            else (
                                f"/user/{notification['user_id']}"
                                if notification.get("user_id")
                                else "#"
                            )
                        )
                    )

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
