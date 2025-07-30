import os
import asyncio
from flask import Flask, request, render_template, jsonify, flash
from flask_login import login_required
from werkzeug.utils import secure_filename
from aiogram.types import FSInputFile
from aiogram.utils.media_group import MediaGroupBuilder
from typing import Any, List
from sqlalchemy import desc

from models.models import User, Newsletter
from web.routes.utils import (
    clean_html,
    allowed_file,
    send_telegram_message_sync,
    get_recent_notifications,
    get_unread_notifications_count,
)
from web.app import db, UPLOAD_FOLDER, MAX_FILE_SIZE
from utils.bot_instance import get_bot
from utils.logger import setup_logger

logger = setup_logger(__name__)


def init_newsletter_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с рассылками."""

    @app.route("/newsletter", methods=["GET", "POST"])
    @login_required
    def newsletter() -> Any:
        """
        Обрабатывает страницу рассылки и отправку сообщений.

        Returns:
            Рендеринг шаблона newsletter.html или JSON-ответ.
        """
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

            async def send_newsletter() -> List[int]:
                """
                Отправляет рассылку пользователям.

                Returns:
                    Список ID пользователей, которым не удалось отправить сообщение.
                """
                failed_users = []
                bot = get_bot()
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
    def newsletters() -> Any:
        """
        Отображение списка рассылок.

        Returns:
            Рендеринг шаблона newsletters.html с данными рассылок.
        """
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
