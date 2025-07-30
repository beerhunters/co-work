import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import pytz
from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.utils.media_group import MediaGroupBuilder
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from flask import send_from_directory, current_app
from flask_login import login_user, logout_user, login_required
from sqlalchemy import desc
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from models.models import (
    User,
    Admin,
    Notification,
    Tariff,
    Booking,
    Promocode,
    Newsletter,
)
from utils.bot_instance import get_bot
from utils.logger import setup_logger
from .app import db

logger = setup_logger(__name__)
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

UPLOAD_FOLDER = "uploads/newsletter"
AVATAR_FOLDER = "static/avatars"  # Папка для хранения аватаров
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "mp4", "mov"}
ALLOWED_AVATAR_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
}  # Только изображения для аватаров
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 МБ для аватаров

ALLOWED_HTML_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "a",
    "code",
    "pre",
    "tg-spoiler",
    "tg-emoji",
    "blockquote",
}


def clean_html(text: str) -> str:
    """Очищает HTML-текст от неподдерживаемых Telegram тегов, сохраняя разрешенные теги и переносы строк."""
    text = re.sub(r"<p\s*[^>]*>|</p>", "\n", text, flags=re.IGNORECASE)
    allowed_tags_pattern = "|".join(rf"(?:{tag})" for tag in ALLOWED_HTML_TAGS)
    cleaned_text = re.sub(
        rf"<(?!/?({allowed_tags_pattern})(?: [^>]*)?>).*?>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    lines = cleaned_text.split("\n")
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    return "\n".join(cleaned_lines)


def init_routes(app: Flask) -> None:
    """Инициализация маршрутов приложения."""

    def allowed_file(filename: str) -> bool:
        """Проверяет, допустимое ли расширение файла."""
        return (
            "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
        )

    def allowed_avatar_file(filename: str) -> bool:
        """Проверяет, допустимое ли расширение для аватара."""
        return (
            "." in filename
            and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS
        )

    def get_unread_notifications_count() -> int:
        """Получение количества непрочитанных уведомлений."""
        count = db.session.query(Notification).filter_by(is_read=0).count()
        logger.info(f"Количество непрочитанных уведомлений: {count}")
        return count

    def get_recent_notifications(limit: int = 5) -> List[Dict]:
        """Возвращает последние уведомления в формате, подходящем для шаблона и AJAX."""
        notifications = (
            db.session.query(Notification)
            .order_by(desc(Notification.created_at))
            .limit(limit)
            .all()
        )
        result = []
        for n in notifications:
            notification_type = "general"
            target_url = url_for("notifications")
            if "Новый пользователь:" in n.message:
                notification_type = "user"
                target_url = url_for("user_detail", user_id=n.user_id)
            elif "Новая бронь" in n.message and n.booking_id:
                notification_type = "booking"
                target_url = url_for("booking_detail", booking_id=n.booking_id)
            result.append(
                {
                    "id": n.id,
                    "message": n.message,
                    "created_at": (
                        n.created_at.strftime("%Y-%m-%d %H:%M")
                        if isinstance(n.created_at, datetime)
                        else n.created_at
                    ),
                    "is_read": bool(n.is_read),
                    "type": notification_type,
                    "target_url": target_url,
                }
            )
        return result

    @app.route("/login", methods=["GET", "POST"])
    def login():
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
    def logout():
        """Обработка выхода из системы."""
        logout_user()
        logger.info("Админ вышел из системы")
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        """Отображение дашборда."""
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "dashboard.html",
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/users")
    @login_required
    def users():
        """Отображение списка пользователей с пагинацией."""
        page = request.args.get("page", 1, type=int)
        per_page = 10
        users_pagination = (
            db.session.query(User)
            .order_by(User.reg_date.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "users.html",
            users=users_pagination.items,
            pagination=users_pagination,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    def custom_secure_filename(filename: str) -> str:
        """Очищает имя файла, сохраняя кириллические символы и заменяя недопустимые на подчеркивание."""
        filename = re.sub(r"[^\w\-\.\u0400-\u04FF]", "_", filename)
        filename = re.sub(r"_+", "_", filename)
        filename = filename.strip("_")
        return filename or "unnamed"

    def check_file_exists(filename: Optional[str]) -> bool:
        """Проверяет, существует ли файл по указанному пути."""
        if not filename:
            logger.info("check_file_exists: Пустое имя файла")
            return False
        file_name = filename.split("/")[-1]
        file_path = os.path.join(
            "/app/static", "avatars", file_name
        )  # Явно используем /app/static
        logger.info(f"check_file_exists: Текущая директория: {os.getcwd()}")
        logger.info(f"check_file_exists: Проверка пути {file_path}")
        logger.info(f"check_file_exists: static_folder: {current_app.static_folder}")
        logger.info(
            f"check_file_exists: Вызвано из шаблона: {current_app.jinja_env.filters.get('is_file') is not None}"
        )
        try:
            exists = os.path.exists(file_path)
            readable = os.access(file_path, os.R_OK)
            logger.info(
                f"check_file_exists: os.path.exists: {exists}, os.access: {readable}"
            )
            if exists:
                stat = os.stat(file_path)
                logger.info(
                    f"check_file_exists: os.stat: {stat.st_size} bytes, mode: {oct(stat.st_mode)}"
                )
            else:
                logger.warning(f"check_file_exists: Файл {file_path} не существует")
            if exists and not readable:
                logger.warning(
                    f"check_file_exists: Файл {file_path} существует, но не читаем"
                )
            return exists and readable
        except Exception as e:
            logger.error(
                f"check_file_exists: Ошибка при проверке файла {file_path}: {str(e)}"
            )
            return False

    @app.template_filter("is_file")
    def is_file(filename: Optional[str]) -> bool:
        """Фильтр для проверки существования файла."""
        result = check_file_exists(filename)
        logger.info(f"is_file: Результат для {filename}: {result}")
        return result

    @app.route("/user/<int:user_id>")
    @login_required
    def user_detail(user_id: int):
        """Отображение детальной информации о пользователе."""
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        # Проверяем существование файла аватара
        if user.avatar:
            if not check_file_exists(user.avatar):
                logger.warning(
                    f"Аватар пользователя {user_id} не найден или не читаем: {user.avatar}"
                )
                user.avatar = None
                db.session.commit()
            else:
                logger.info(f"Результат check_file_exists для {user.avatar}: True")
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "user_detail.html",
            user=user,
            edit=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/user/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_user(user_id: int):
        """Редактирование пользователя."""
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        if request.method == "POST":
            try:
                user.full_name = request.form.get("full_name")
                user.phone = request.form.get("phone")
                user.email = request.form.get("email")
                user.username = request.form.get("username")
                user.successful_bookings = int(
                    request.form.get("successful_bookings", 0)
                )
                user.language_code = request.form.get("language_code", "ru")
                avatar_file = request.files.get("avatar")
                logger.info(
                    f"Файл аватара в запросе для пользователя {user_id}: {request.files}"
                )
                if (
                    avatar_file
                    and avatar_file.filename
                    and allowed_avatar_file(avatar_file.filename)
                ):
                    if avatar_file.filename.strip() == "":
                        flash("Файл аватара имеет пустое имя", "error")
                        logger.warning(
                            f"Пустое имя файла аватара для пользователя {user_id}: {avatar_file.filename}"
                        )
                    else:
                        avatar_file.seek(0, os.SEEK_END)
                        file_size = avatar_file.tell()
                        avatar_file.seek(0)
                        if file_size > MAX_AVATAR_SIZE:
                            flash(
                                "Файл аватара превышает допустимый размер (5 МБ)",
                                "error",
                            )
                            logger.warning(
                                f"Файл аватара для пользователя {user_id} превышает 5 МБ"
                            )
                        else:
                            # Удаляем старый аватар, если он существует
                            if user.avatar:
                                old_avatar_path = os.path.join(
                                    "/app/static", "avatars", user.avatar.split("/")[-1]
                                )
                                if os.path.exists(old_avatar_path):
                                    os.remove(old_avatar_path)
                                    logger.info(
                                        f"Старый аватар пользователя {user_id} удалён: {old_avatar_path}"
                                    )
                            os.makedirs("/app/static/avatars", exist_ok=True)
                            raw_filename = avatar_file.filename
                            logger.info(
                                f"Исходное имя файла для пользователя {user_id}: {raw_filename}"
                            )
                            filename = custom_secure_filename(
                                f"{user_id}_{raw_filename}"
                            )
                            logger.info(
                                f"Обработанное имя файла для пользователя {user_id}: {filename}"
                            )
                            file_path = os.path.join("/app/static", "avatars", filename)
                            avatar_file.save(file_path)
                            os.chmod(file_path, 0o644)
                            logger.info(
                                f"Аватар сохранён для пользователя {user_id}: {file_path}"
                            )
                            user.avatar = f"static/avatars/{filename}"
                elif avatar_file and not avatar_file.filename:
                    flash("Файл аватара не выбран", "error")
                    logger.warning(f"Файл аватара не выбран для пользователя {user_id}")
                db.session.commit()
                flash("Данные пользователя обновлены")
                logger.info(f"Пользователь {user_id} обновлён")
                return redirect(url_for("user_detail", user_id=user_id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при обновлении данных")
                logger.error(f"Ошибка обновления пользователя {user_id}: {str(e)}")
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "user_detail.html",
            user=user,
            edit=True,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/user/<int:user_id>/delete_avatar", methods=["POST"])
    @login_required
    def delete_avatar(user_id: int):
        """Удаление аватара пользователя."""
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            logger.warning(f"Пользователь {user_id} не найден для удаления аватара")
            return redirect(url_for("users"))
        try:
            if user.avatar:
                avatar_path = os.path.join(
                    "/app/static", "avatars", user.avatar.split("/")[-1]
                )
                logger.info(
                    f"Попытка удаления аватара для пользователя {user_id}: {avatar_path}"
                )
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
                    logger.info(f"Аватар пользователя {user_id} удалён: {avatar_path}")
                user.avatar = None
                db.session.commit()
                flash("Аватар удалён")
                logger.info(f"Аватар пользователя {user_id} сброшен")
            else:
                flash("Аватар отсутствует")
                logger.info(f"У пользователя {user_id} нет аватара для удаления")
            return redirect(url_for("user_detail", user_id=user_id))
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении аватара")
            logger.error(f"Ошибка удаления аватара пользователя {user_id}: {str(e)}")
            return redirect(url_for("user_detail", user_id=user_id))

    @app.route("/static/avatars/<path:filename>")
    def serve_avatar(filename: str):
        """Обслуживание файлов аватаров."""
        logger.info(f"Запрос к /static/avatars/{filename}")
        try:
            file_path = os.path.join("/app/static/avatars", filename)
            logger.info(f"serve_avatar: Проверка пути {file_path}")
            if not os.path.exists(file_path):
                logger.warning(f"serve_avatar: Файл {file_path} не существует")
                return "", 404
            return send_from_directory("/app/static/avatars", filename)
        except Exception as e:
            logger.error(
                f"Ошибка при обслуживании файла /static/avatars/{filename}: {str(e)}"
            )
            return "", 404

    @app.route("/debug_static")
    def debug_static():
        """Отладочный маршрут для проверки static_folder."""
        logger.info(f"debug_static: static_folder: {current_app.static_folder}")
        logger.info(f"debug_static: static_url_path: {current_app.static_url_path}")
        logger.info(f"debug_static: Текущая директория: {os.getcwd()}")
        avatars_path = os.path.join("/app/static", "avatars")
        logger.info(
            f"debug_static: Содержимое /app/static/avatars: {os.listdir(avatars_path) if os.path.exists(avatars_path) else 'Папка не существует'}"
        )
        return "Debug info logged", 200

    @app.route("/user/<int:user_id>/delete", methods=["POST"])
    @login_required
    def delete_user(user_id: int):
        """Удаление пользователя."""
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        try:
            if user.avatar:
                avatar_path = os.path.join("web", "static", user.avatar)
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
                    logger.info(f"Аватар пользователя {user_id} удалён: {avatar_path}")
            db.session.delete(user)
            db.session.commit()
            flash("Пользователь удалён")
            logger.info(f"Пользователь {user_id} удалён")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении пользователя")
            logger.error(f"Ошибка удаления пользователя {user_id}: {str(e)}")
        return redirect(url_for("users"))

    @app.route("/tariffs")
    @login_required
    def tariffs():
        """Отображение списка тарифов, отсортированных по ID."""
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
    def tariff_detail(tariff_id: int):
        """Отображение детальной информации о тарифе."""
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
    def edit_tariff(tariff_id: int):
        """Редактирование тарифа."""
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
    def delete_tariff(tariff_id: int):
        """Удаление тарифа."""
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
    def new_tariff():
        """Создание нового тарифа."""
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

    @app.route("/bookings")
    @login_required
    def bookings():
        """Отображение списка бронирований."""
        bookings = db.session.query(Booking).order_by(Booking.visit_date.desc()).all()
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "bookings.html",
            bookings=bookings,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/booking/<int:booking_id>")
    @login_required
    def booking_detail(booking_id: int):
        """Отображение детальной информации о бронировании."""
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            return redirect(url_for("bookings"))
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "booking_detail.html",
            booking=booking,
            user=booking.user,
            tariff=booking.tariff,
            promocode=booking.promocode,
            edit=False,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/booking/<int:booking_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_booking(booking_id: int):
        """Редактирование бронирования."""
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            return redirect(url_for("bookings"))
        if request.method == "POST":
            try:
                visit_date = request.form.get("visit_date")
                booking.visit_date = datetime.strptime(visit_date, "%Y-%m-%d").date()
                if booking.tariff.purpose == "Переговорная":
                    visit_time = request.form.get("visit_time")
                    booking.visit_time = datetime.strptime(visit_time, "%H:%M").time()
                    booking.duration = int(request.form.get("duration"))
                booking.amount = float(request.form.get("amount"))
                booking.paid = request.form.get("paid") == "on"
                db.session.commit()
                flash("Данные бронирования обновлены")
                logger.info(f"Бронирование {booking_id} обновлено")
                return redirect(url_for("booking_detail", booking_id=booking_id))
            except Exception as e:
                db.session.rollback()
                flash("Ошибка при обновлении данных")
                logger.error(f"Ошибка обновления бронирования {booking_id}: {str(e)}")
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "booking_detail.html",
            booking=booking,
            user=booking.user,
            tariff=booking.tariff,
            edit=True,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    @app.route("/booking/<int:booking_id>/delete", methods=["POST"])
    @login_required
    def delete_booking(booking_id: int):
        """Удаление бронирования."""
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            return redirect(url_for("bookings"))
        try:
            db.session.delete(booking)
            db.session.commit()
            flash("Бронирование удалено")
            logger.info(f"Бронирование {booking_id} удалено")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении бронирования")
            logger.error(f"Ошибка удаления бронирования {booking_id}: {str(e)}")
        return redirect(url_for("bookings"))

    def send_telegram_message_sync(telegram_id: int, message: str) -> bool:
        """Отправляет сообщение пользователю через Telegram в синхронном контексте."""
        try:
            bot = get_bot()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(
                bot.send_message(chat_id=telegram_id, text=message)
            )
            loop.close()
            return bool(success)
        except Exception as e:
            logger.error(
                f"Не удалось отправить сообщение пользователю {telegram_id}: {str(e)}"
            )
            return False

    @app.route("/booking/<int:booking_id>/confirm", methods=["POST"])
    @login_required
    def confirm_booking(booking_id: int):
        """Подтверждение бронирования для 'Переговорной'."""
        booking = db.session.get(Booking, booking_id)
        if not booking:
            flash("Бронирование не найдено")
            return redirect(url_for("bookings"))
        if booking.confirmed:
            flash("Бронирование уже подтверждено")
            return redirect(url_for("booking_detail", booking_id=booking_id))
        try:
            booking.confirmed = True
            db.session.commit()
            user = db.session.get(User, booking.user_id)
            tariff = db.session.get(Tariff, booking.tariff_id)
            message = (
                f"Ваша бронь подтверждена!\n"
                f"Тариф: {tariff.name}\n"
                f"Дата: {booking.visit_date}\n"
                f"Время: {booking.visit_time}\n"
                f"Продолжительность: {booking.duration} ч"
            )
            success = send_telegram_message_sync(user.telegram_id, message)
            if success:
                logger.info(
                    f"Сообщение о подтверждении брони {booking_id} отправлено пользователю {user.telegram_id}"
                )
            else:
                logger.error(
                    f"Не удалось отправить сообщение пользователю {user.telegram_id}"
                )
            flash("Бронирование подтверждено")
            logger.info(f"Бронирование {booking_id} подтверждено")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при подтверждении бронирования")
            logger.error(f"Ошибка подтверждения бронирования {booking_id}: {str(e)}")
        return redirect(url_for("booking_detail", booking_id=booking_id))

    @app.route("/promocodes")
    @login_required
    def promocodes():
        """Отображение списка промокодов, отсортированных по ID."""
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
    def promocode_detail(promocode_id: int):
        """Отображение детальной информации о промокоде."""
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
    def edit_promocode(promocode_id: int):
        """Редактирование промокода."""
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
    def delete_promocode(promocode_id: int):
        """Удаление промокода."""
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
    def new_promocode():
        """Создание нового промокода."""
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

    @app.route("/notifications")
    @login_required
    def notifications():
        """Отображение списка уведомлений."""
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
    def mark_all_notifications_read():
        """Пометить все уведомления как прочитанные."""
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
    def mark_notification_read(notification_id: int):
        """Пометить одно уведомление как прочитанное."""
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
    def clean_old_notifications():
        """Удаление прочитанных уведомлений старше 30 дней."""
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
    def get_notifications():
        """Получение данных об уведомлениях для AJAX."""
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

    @app.route("/flash_message", methods=["POST"])
    @login_required
    def flash_message():
        """Отправляет flash-сообщение через AJAX."""
        try:
            message = request.form.get("message")
            category = request.form.get("category", "info")
            if not message:
                return (
                    jsonify({"status": "error", "message": "Сообщение не указано"}),
                    400,
                )
            flash(message, category)
            return jsonify(
                {"status": "success", "message": "Flash-сообщение добавлено"}
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке flash-сообщения: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/debug_db")
    @login_required
    def debug_db():
        """Отладочный маршрут для проверки таблиц users и notifications."""
        try:
            users = db.session.query(User).all()
            notifications = db.session.query(Notification).all()
            users_data = [
                {
                    "id": user.id,
                    "telegram_id": user.telegram_id,
                    "full_name": user.full_name,
                    "phone": user.phone,
                    "email": user.email,
                    "username": user.username,
                    "reg_date": (
                        user.reg_date.strftime("%Y-%m-%d %H:%M:%S %Z")
                        if user.reg_date
                        else None
                    ),
                    "avatar": user.avatar,
                }
                for user in users
            ]
            notifications_data = [
                {
                    "id": notification.id,
                    "user_id": notification.user_id,
                    "message": notification.message,
                    "created_at": notification.created_at.strftime(
                        "%Y-%m-%d %H:%M:%S %Z"
                    ),
                    "is_read": notification.is_read,
                }
                for notification in notifications
            ]
            return jsonify({"users": users_data, "notifications": notifications_data})
        except Exception as e:
            logger.error(f"Ошибка отладки БД: {str(e)}")
            return jsonify({"error": "Ошибка сервера"}), 500

    @app.route("/newsletter", methods=["GET", "POST"])
    @login_required
    def newsletter() -> Any:
        """Обрабатывает страницу рассылки и отправку сообщений."""
        try:
            if request.method == "GET":
                users = db.session.query(User).order_by(User.id).all()
                unread_notifications = get_unread_notifications_count()
                recent_notifications = get_recent_notifications()
                logger.info("Отображена страница рассылки")
                return render_template(
                    "newsletter.html",
                    users=users,
                    unread_notifications=unread_notifications,
                    recent_notifications=recent_notifications,
                )
            message = request.form.get("message")
            recipient_type = request.form.get("recipient_type")
            selected_users = request.form.getlist("selected_users")
            if not message:
                logger.warning("Попытка отправки рассылки с пустым сообщением")
                return (
                    jsonify(
                        {"status": "error", "message": "Сообщение не может быть пустым"}
                    ),
                    400,
                )
            cleaned_message = clean_html(message)
            if not cleaned_message:
                logger.warning("Очищенный текст сообщения пустой")
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Очищенный текст сообщения пустой",
                        }
                    ),
                    400,
                )
            users = []
            if recipient_type == "all":
                users = db.session.query(User).filter(User.telegram_id != None).all()
            else:
                if not selected_users:
                    logger.warning(
                        "Попытка отправки рассылки без выбранных пользователей"
                    )
                    return (
                        jsonify(
                            {"status": "error", "message": "Не выбраны пользователи"}
                        ),
                        400,
                    )
                users = (
                    db.session.query(User)
                    .filter(User.id.in_(selected_users), User.telegram_id != None)
                    .all()
                )
            if not users:
                logger.warning("Нет пользователей для рассылки")
                return (
                    jsonify(
                        {"status": "error", "message": "Нет пользователей для рассылки"}
                    ),
                    400,
                )
            media_files = request.files.getlist("media")
            saved_files = []
            if media_files and media_files[0].filename:
                if len(media_files) > 5:
                    logger.warning(
                        f"Попытка загрузки {len(media_files)} файлов, максимум 5"
                    )
                    return (
                        jsonify({"status": "error", "message": "Максимум 5 файлов"}),
                        400,
                    )
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                for file in media_files:
                    if file and allowed_file(file.filename):
                        file.seek(0, os.SEEK_END)
                        file_size = file.tell()
                        file.seek(0)
                        if file_size > MAX_FILE_SIZE:
                            logger.warning(
                                f"Файл {file.filename} превышает допустимый размер 50 МБ"
                            )
                            return (
                                jsonify(
                                    {
                                        "status": "error",
                                        "message": f"Файл {file.filename} превышает 50 МБ",
                                    }
                                ),
                                400,
                            )
                        filename = secure_filename(file.filename)
                        file_path = os.path.join(UPLOAD_FOLDER, filename)
                        file.save(file_path)
                        saved_files.append(file_path)
                    else:
                        logger.warning(f"Недопустимый файл: {file.filename}")
                        return (
                            jsonify(
                                {
                                    "status": "error",
                                    "message": f"Недопустимый файл: {file.filename}",
                                }
                            ),
                            400,
                        )

            async def send_newsletter():
                failed_users = []
                for user in users:
                    try:
                        if saved_files:
                            if len(saved_files) == 1 and saved_files[0].rsplit(".", 1)[
                                1
                            ].lower() in {"png", "jpg", "jpeg", "gif"}:
                                photo = FSInputFile(path=saved_files[0])
                                await bot.send_photo(
                                    chat_id=user.telegram_id,
                                    photo=photo,
                                    caption=cleaned_message,
                                    parse_mode="HTML",
                                )
                            elif len(saved_files) == 1 and saved_files[0].rsplit(
                                ".", 1
                            )[1].lower() in {"mp4", "mov"}:
                                video = FSInputFile(path=saved_files[0])
                                await bot.send_video(
                                    chat_id=user.telegram_id,
                                    video=video,
                                    caption=cleaned_message,
                                    parse_mode="HTML",
                                )
                            else:
                                media_group = MediaGroupBuilder()
                                for index, file_path in enumerate(saved_files):
                                    media_group.add_photo(
                                        media=FSInputFile(path=file_path),
                                        caption=(
                                            cleaned_message
                                            if index == 0 and cleaned_message
                                            else None
                                        ),
                                        parse_mode=(
                                            "HTML"
                                            if index == 0 and cleaned_message
                                            else None
                                        ),
                                    )
                                await bot.send_media_group(
                                    chat_id=user.telegram_id, media=media_group.build()
                                )
                        else:
                            await bot.send_message(
                                chat_id=user.telegram_id,
                                text=cleaned_message,
                                parse_mode="HTML",
                            )
                        logger.info(
                            f"Сообщение отправлено пользователю {user.telegram_id}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Ошибка отправки пользователю {user.telegram_id}: {str(e)}"
                        )
                        if "blocked by user" in str(e).lower():
                            logger.warning(
                                f"Пользователь {user.telegram_id} заблокировал бота"
                            )
                        failed_users.append(user.telegram_id)
                return failed_users

            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            failed_users = loop.run_until_complete(send_newsletter())
            try:
                newsletter = Newsletter(
                    message=cleaned_message, recipient_count=len(users)
                )
                db.session.add(newsletter)
                db.session.commit()
                logger.info("История рассылки сохранена в БД")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Ошибка сохранения истории рассылки: {str(e)}")
            for file_path in saved_files:
                try:
                    os.remove(file_path)
                    logger.info(f"Удалён временный файл: {file_path}")
                except Exception as e:
                    logger.error(f"Ошибка удаления файла {file_path}: {str(e)}")
            if failed_users:
                failed_count = len(failed_users)
                flash(
                    f"Не удалось отправить сообщение {failed_count} пользователям",
                    "warning",
                )
                logger.warning(
                    f"Не удалось отправить сообщение {failed_count} пользователям"
                )
                return jsonify(
                    {
                        "status": "warning",
                        "message": f"Рассылка отправлена, но не доставлена {failed_count} пользователям",
                    }
                )
            else:
                flash("Рассылка успешно отправлена всем пользователям", "success")
                logger.info(f"Рассылка успешно отправлена {len(users)} пользователям")
                return jsonify(
                    {"status": "success", "message": "Рассылка успешно отправлена"}
                )
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при обработке рассылки: {str(e)}")
            return jsonify({"status": "error", "message": f"Ошибка: {str(e)}"}), 500

    @app.route("/newsletters")
    @login_required
    def newsletters():
        newsletters = (
            db.session.query(Newsletter).order_by(desc(Newsletter.created_at)).all()
        )
        unread_notifications = get_unread_notifications_count()
        recent_notifications = get_recent_notifications()
        return render_template(
            "newsletters.html",
            newsletters=newsletters,
            unread_notifications=unread_notifications,
            recent_notifications=recent_notifications,
        )

    # Регистрация пользовательского фильтра для проверки существования файла
    @app.template_filter("is_file")
    def is_file(filename: str) -> bool:
        """Проверяет, существует ли файл по указанному пути."""
        if not filename:
            return False
        return os.path.exists(os.path.join("web", "static", filename))
