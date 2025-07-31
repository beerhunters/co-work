import os
from typing import Any, Optional

from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    send_from_directory,
)
from flask_login import login_required

from models.models import User
from utils.logger import setup_logger
from web.app import db, AVATAR_FOLDER, MAX_AVATAR_SIZE
from web.routes.utils import (
    check_file_exists,
    allowed_avatar_file,
    custom_secure_filename,
    get_recent_notifications,
    get_unread_notifications_count,
)

logger = setup_logger(__name__)


def init_user_routes(app: Flask) -> None:
    """Инициализация маршрутов для работы с пользователями."""

    @app.template_filter("is_file")
    def is_file(filename: Optional[str]) -> bool:
        """Фильтр для проверки существования файла."""
        result = check_file_exists(filename)
        logger.info(f"is_file: Результат для {filename}: {result}")
        return result

    @app.route("/users")
    @login_required
    def users() -> Any:
        """
        Отображение списка пользователей с пагинацией.

        Returns:
            Рендеринг шаблона users.html с данными пользователей.
        """
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

    @app.route("/user/<int:user_id>")
    @login_required
    def user_detail(user_id: int) -> Any:
        """
        Отображение детальной информации о пользователе.

        Args:
            user_id: ID пользователя.

        Returns:
            Рендеринг шаблона user_detail.html или редирект.
        """
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            return redirect(url_for("users"))
        if user.avatar and not check_file_exists(user.avatar):
            logger.warning(
                f"Аватар пользователя {user_id} не найден или не читаем: {user.avatar}"
            )
            user.avatar = None
            db.session.commit()
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
    def edit_user(user_id: int) -> Any:
        """
        Редактирование пользователя, включая загрузку аватара.

        Args:
            user_id: ID пользователя.

        Returns:
            Рендеринг шаблона user_detail.html или редирект.
        """
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
                    f"Файл аватара в запросе для пользователя {user_id}: {avatar_file.filename if avatar_file else 'None'}"
                )
                if (
                    avatar_file
                    and avatar_file.filename
                    and allowed_avatar_file(avatar_file.filename)
                ):
                    if avatar_file.filename.strip() == "":
                        flash("Файл аватара имеет пустое имя", "error")
                        logger.warning(
                            f"Пустое имя файла аватара для пользователя {user_id}"
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
                            if user.avatar:
                                old_avatar_path = os.path.join(
                                    AVATAR_FOLDER,
                                    (
                                        user.avatar.replace("avatars/", "")
                                        if user.avatar.startswith("avatars/")
                                        else user.avatar
                                    ),
                                )
                                if os.path.exists(old_avatar_path):
                                    try:
                                        os.remove(old_avatar_path)
                                        logger.info(
                                            f"Старый аватар пользователя {user_id} удалён: {old_avatar_path}"
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"Не удалось удалить старый аватар {old_avatar_path}: {str(e)}"
                                        )
                            os.makedirs(AVATAR_FOLDER, exist_ok=True)
                            try:
                                os.chmod(AVATAR_FOLDER, 0o755)
                                logger.info(
                                    f"Установлены права 755 на папку {AVATAR_FOLDER}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Не удалось установить права на папку {AVATAR_FOLDER}: {str(e)}"
                                )
                            raw_filename = avatar_file.filename
                            filename = custom_secure_filename(
                                f"{user_id}_{raw_filename}"
                            )
                            file_path = os.path.join(AVATAR_FOLDER, filename)
                            avatar_file.save(file_path)
                            try:
                                os.chmod(file_path, 0o644)
                                logger.info(
                                    f"Аватар сохранён для пользователя {user_id}: {file_path}, права установлены на 644"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Не удалось установить права на файл {file_path}: {str(e)}"
                                )
                            user.avatar = f"avatars/{filename}"
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
    def delete_avatar(user_id: int) -> Any:
        """
        Удаление аватара пользователя.

        Args:
            user_id: ID пользователя.

        Returns:
            Редирект на страницу пользователя.
        """
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            logger.warning(f"Пользователь {user_id} не найден для удаления аватара")
            return redirect(url_for("users"))
        try:
            if user.avatar:
                avatar_filename = (
                    user.avatar.replace("avatars/", "")
                    if user.avatar.startswith("avatars/")
                    else user.avatar
                )
                avatar_path = os.path.join(AVATAR_FOLDER, avatar_filename)
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
    def serve_avatar(filename: str) -> Any:
        """
        Обслуживание файлов аватаров.

        Args:
            filename: Имя файла аватара.

        Returns:
            Файл или ошибка 404.
        """
        logger.info(f"Запрос к /static/avatars/{filename}")
        try:
            file_path = os.path.join(AVATAR_FOLDER, filename)
            if not os.path.exists(file_path):
                logger.warning(f"Файл {file_path} не существует")
                return "", 404
            return send_from_directory(AVATAR_FOLDER, filename)
        except Exception as e:
            logger.error(f"Ошибка при обслуживании файла {filename}: {str(e)}")
            return "", 404

    @app.route("/debug_static")
    def debug_static() -> Any:
        """
        Отладочный маршрут для проверки содержимого папки аватаров.

        Returns:
            Сообщение об успешной записи отладочной информации.
        """
        logger.info(f"debug_static: static_folder: {app.static_folder}")
        logger.info(f"debug_static: static_url_path: {app.static_url_path}")
        logger.info(f"debug_static: Текущая директория: {os.getcwd()}")
        try:
            files = os.listdir(AVATAR_FOLDER) if os.path.exists(AVATAR_FOLDER) else []
            logger.info(f"debug_static: Содержимое {AVATAR_FOLDER}: {files}")
            for file in files:
                file_path = os.path.join(AVATAR_FOLDER, file)
                logger.info(
                    f"debug_static: Файл {file_path}, существует: {os.path.exists(file_path)}, читаем: {os.access(file_path, os.R_OK)}"
                )
        except Exception as e:
            logger.error(
                f"debug_static: Ошибка при получении содержимого {AVATAR_FOLDER}: {str(e)}"
            )
        return "Debug info logged", 200

    @app.route("/user/<int:user_id>/delete", methods=["POST"])
    @login_required
    def delete_user(user_id: int) -> Any:
        """
        Удаление пользователя и связанных данных (уведомления, аватар).

        Args:
            user_id: ID пользователя.

        Returns:
            Редирект на список пользователей.
        """
        user = db.session.get(User, user_id)
        if not user:
            flash("Пользователь не найден")
            logger.warning(f"Пользователь {user_id} не найден для удаления")
            return redirect(url_for("users"))
        try:
            if user.avatar:
                avatar_filename = (
                    user.avatar.replace("avatars/", "")
                    if user.avatar.startswith("avatars/")
                    else user.avatar
                )
                avatar_path = os.path.join(AVATAR_FOLDER, avatar_filename)
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
                    logger.info(f"Аватар пользователя {user_id} удалён: {avatar_path}")
            db.session.delete(user)
            db.session.commit()
            flash("Пользователь и связанные данные удалены")
            logger.info(f"Пользователь {user_id} и связанные уведомления удалены")
        except Exception as e:
            db.session.rollback()
            flash("Ошибка при удалении пользователя")
            logger.error(f"Ошибка удаления пользователя {user_id}: {str(e)}")
        return redirect(url_for("users"))
