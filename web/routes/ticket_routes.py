from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import login_required
from datetime import datetime
from typing import Any, Optional
import pytz

from models.models import Ticket, TicketStatus, User
from web.routes.utils import (
    get_unread_notifications_count,
    get_recent_notifications,
    send_telegram_message_sync,
)
from web.app import db
from utils.logger import get_logger

# Тихая настройка логгера для модуля
logger = get_logger(__name__)

# Московский часовой пояс
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


def format_ticket_status_notification(
    user: User, ticket: Ticket, status: str, comment: Optional[str] = None
) -> str:
    """
    Форматирует уведомление об изменении статуса заявки для отправки пользователю.

    Args:
        user: Объект пользователя.
        ticket: Объект заявки.
        status: Новый статус заявки (например, "Открыта", "В работе", "Закрыта").
        comment: Комментарий к изменению статуса (если указан, по умолчанию None).

    Returns:
        str: Отформатированное HTML-сообщение для отправки в Telegram.
    """
    status_emojis = {
        "Открыта": "🆕",
        "В работе": "⚙️",
        "Закрыта": "✅",
    }

    status_emoji = status_emojis.get(status, "📋")
    comment_info = f"\n└ <b>Комментарий:</b> {comment}" if comment else ""

    message = f"""{status_emoji} <b>Статус заявки #{ticket.id} изменён!</b>

📋 <b>Детали:</b>
├ <b>ID:</b> {ticket.id}
├ <b>Статус:</b> {status}{comment_info}
└ <b>Описание:</b> {ticket.description}

⏰ <i>Время изменения: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M:%S')}</i>"""

    logger.debug(
        f"Сформировано сообщение об изменении статуса заявки #{ticket.id}:\n{message}"
    )
    return message.strip()


def init_ticket_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с заявками."""

    @app.route("/tickets")
    @login_required
    def tickets() -> Any:
        """
        Отображение списка заявок с возможностью фильтрации по статусу.

        Returns:
            Рендеринг шаблона tickets.html с отфильтрованными данными заявок.
        """
        page = request.args.get("page", 1, type=int)
        status = request.args.get("status", "").strip()
        per_page = 10

        # Базовый запрос для получения заявок
        query = db.session.query(Ticket).order_by(Ticket.created_at.desc())

        # Фильтрация по статусу
        if status:
            try:
                status_enum = TicketStatus(status)
                query = query.filter(Ticket.status == status_enum)
                logger.debug(f"Применён фильтр по статусу: {status}")
            except ValueError:
                flash("Неверный статус", "error")
                logger.warning(f"Неверный статус в запросе: {status}")

        # Пагинация
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        tickets = pagination.items
        logger.info(
            f"Найдено {len(tickets)} заявок на странице {page} после фильтрации"
        )

        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "tickets.html",
            tickets=tickets,
            pagination=pagination,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/ticket/<int:ticket_id>")
    @login_required
    def ticket_detail(ticket_id: int) -> Any:
        """
        Отображение детальной информации о заявке.

        Args:
            ticket_id: ID заявки.

        Returns:
            Рендеринг шаблона ticket_detail.html или редирект.
        """
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            flash("Заявка не найдена", "error")
            return redirect(url_for("tickets"))

        # Преобразование времени в московский часовой пояс
        created_at_msk = (
            ticket.created_at.astimezone(MOSCOW_TZ) if ticket.created_at else None
        )
        updated_at_msk = (
            ticket.updated_at.astimezone(MOSCOW_TZ) if ticket.updated_at else None
        )

        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "ticket_detail.html",
            ticket=ticket,
            user=ticket.user,
            created_at_msk=created_at_msk,
            updated_at_msk=updated_at_msk,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/ticket/<int:ticket_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_ticket(ticket_id: int) -> Any:
        """
        Редактирование заявки.

        Args:
            ticket_id: ID заявки.

        Returns:
            Рендеринг шаблона ticket_detail.html или редирект.
        """
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            flash("Заявка не найдена", "error")
            return redirect(url_for("tickets"))

        if ticket.status == TicketStatus.CLOSED:
            flash("Заявка закрыта и не может быть изменена", "warning")
            return redirect(url_for("ticket_detail", ticket_id=ticket_id))

        if request.method == "POST":
            try:
                status = request.form.get("status")
                comment = request.form.get("comment")

                # Проверка недопустимого перехода назад на статус "Открыта"
                if ticket.status != TicketStatus.OPEN and status == "Открыта":
                    flash("Нельзя вернуть статус 'Открыта' после изменения", "error")
                    return render_template(
                        "ticket_detail.html",
                        ticket=ticket,
                        user=ticket.user,
                        created_at_msk=(
                            ticket.created_at.astimezone(MOSCOW_TZ)
                            if ticket.created_at
                            else None
                        ),
                        updated_at_msk=(
                            ticket.updated_at.astimezone(MOSCOW_TZ)
                            if ticket.updated_at
                            else None
                        ),
                        unread_notifications=get_unread_notifications_count(),
                        recent_notifications=get_recent_notifications(),
                    )

                # Проверка обязательного комментария для статуса "Закрыта"
                if status == "Закрыта" and not comment:
                    flash("Комментарий обязателен для закрытия заявки", "error")
                    return render_template(
                        "ticket_detail.html",
                        ticket=ticket,
                        user=ticket.user,
                        created_at_msk=(
                            ticket.created_at.astimezone(MOSCOW_TZ)
                            if ticket.created_at
                            else None
                        ),
                        updated_at_msk=(
                            ticket.updated_at.astimezone(MOSCOW_TZ)
                            if ticket.updated_at
                            else None
                        ),
                        unread_notifications=get_unread_notifications_count(),
                        recent_notifications=get_recent_notifications(),
                    )

                # Обновление полей
                ticket.status = TicketStatus(status)
                ticket.comment = comment
                ticket.updated_at = datetime.now(MOSCOW_TZ)
                db.session.commit()

                # Отправка уведомления пользователю
                user = db.session.get(User, ticket.user_id)
                message = format_ticket_status_notification(
                    user, ticket, status, comment
                )
                success = send_telegram_message_sync(user.telegram_id, message)
                if success:
                    logger.info(
                        f"Сообщение об изменении статуса заявки #{ticket.id} отправлено пользователю {user.telegram_id}"
                    )
                else:
                    logger.error(
                        f"Не удалось отправить сообщение пользователю {user.telegram_id} для заявки #{ticket.id}"
                    )
                    flash("Заявка обновлена, но уведомление не отправлено", "warning")
                flash("Данные заявки обновлены", "success")
                logger.info(
                    f"Заявка #{ticket.id} обновлена, updated_at: {ticket.updated_at}"
                )
                return redirect(url_for("ticket_detail", ticket_id=ticket_id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при обновлении данных", "error")
                logger.error(f"Ошибка обновления заявки #{ticket.id}: {str(e)}")
                return render_template(
                    "ticket_detail.html",
                    ticket=ticket,
                    user=ticket.user,
                    created_at_msk=(
                        ticket.created_at.astimezone(MOSCOW_TZ)
                        if ticket.created_at
                        else None
                    ),
                    updated_at_msk=(
                        ticket.updated_at.astimezone(MOSCOW_TZ)
                        if ticket.updated_at
                        else None
                    ),
                    unread_notifications=get_unread_notifications_count(),
                    recent_notifications=get_recent_notifications(),
                )

        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "ticket_detail.html",
            ticket=ticket,
            user=ticket.user,
            created_at_msk=(
                ticket.created_at.astimezone(MOSCOW_TZ) if ticket.created_at else None
            ),
            updated_at_msk=(
                ticket.updated_at.astimezone(MOSCOW_TZ) if ticket.updated_at else None
            ),
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/ticket/<int:ticket_id>/delete", methods=["POST"])
    @login_required
    def delete_ticket(ticket_id: int) -> Any:
        """
        Удаление заявки.

        Args:
            ticket_id: ID заявки.

        Returns:
            Редирект на список заявок.
        """
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            flash("Заявка не найдена", "error")
            return redirect(url_for("tickets"))
        try:
            db.session.delete(ticket)
            db.session.commit()
            flash("Заявка удалена", "success")
            logger.info(f"Заявка #{ticket.id} удалена")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении заявки", "error")
            logger.error(f"Ошибка удаления заявки #{ticket.id}: {str(e)}")
        return redirect(url_for("tickets"))
