from flask import Flask, render_template
from flask_login import login_required
from typing import Any

from web.routes.utils import get_unread_notifications_count, get_recent_notifications

from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)


def init_dashboard_routes(app: Flask) -> None:
    """Инициализация маршрута для дашборда."""

    @app.route("/")
    @login_required
    def dashboard() -> Any:
        """
        Отображение дашборда.

        Returns:
            Рендеринг шаблона dashboard.html.
        """
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "dashboard.html",
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )
