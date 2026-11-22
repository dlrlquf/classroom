import base64
import ipaddress
import socket
import sqlite3
from io import BytesIO

import qrcode
from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)
from qrcode.image.svg import SvgPathImage

from database import get_db
from lobby import (
    APPS,
    ROOMS,
    get_code,
    is_class_started,
    set_active_app,
    stop_class,
)

bp = Blueprint("main", __name__)


def _is_admin_ip_allowed():
    if not request.remote_addr:
        return False
    try:
        client_ip = ipaddress.ip_address(request.remote_addr)
    except ValueError:
        return False
    return client_ip in current_app.config["ADMIN_ALLOWED_IPS"]


@bp.before_request
def redirect_remote_clients():
    # 로컬이 아닌 접속은 참가자 페이지 외에는 볼 수 없다.
    if _is_admin_ip_allowed() or request.endpoint in (
        "main.user",
        "main.user_app",
        "main.class_status",
        "static",
    ):
        return None
    return redirect(url_for("main.user", **request.args.to_dict()))


@bp.before_request
def require_started_class():
    if (
        _is_admin_ip_allowed()
        and request.endpoint in ("main.room", "main.app_page", "main.admin_redirect")
        and not is_class_started()
    ):
        return redirect(
            url_for(
                "main.home",
                notice="수업 시작 버튼을 먼저 눌러 주세요.",
            )
        )
    return None


def _make_join_info(code):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
            server_socket.connect(("8.8.8.8", 80))
            server_ip = server_socket.getsockname()[0]
        server_port = int(request.environ["SERVER_PORT"])
        join_url = f"{request.scheme}://{server_ip}"
        if not (
            request.scheme == "http" and server_port == 80
            or request.scheme == "https" and server_port == 443
        ):
            join_url += f":{server_port}"
        join_url += url_for("main.user", code=code)
        qr_image = qrcode.make(join_url, image_factory=SvgPathImage)
        qr_buffer = BytesIO()
        qr_image.save(qr_buffer)
        qr_code = base64.b64encode(qr_buffer.getvalue()).decode("ascii")
    except (OSError, KeyError, ValueError) as error:
        current_app.logger.warning("접속 QR 코드를 만들 수 없습니다: %s", error)
        return {"join_url": None, "qr_code": None}
    return {"join_url": join_url, "qr_code": qr_code}


@bp.app_context_processor
def inject_host_context():
    if _is_admin_ip_allowed() and request.endpoint != "main.user":
        return {
            "rooms": ROOMS,
            "join_code": get_code(),
            "class_started": is_class_started(),
            **_make_join_info(get_code()),
        }
    return {"rooms": ROOMS}


@bp.route("/")
def home():
    stop_class()
    set_active_app(None)
    from lobby import get_class_list, get_selected_class

    return render_template(
        "home.html",
        classes=get_class_list(),
        selected_class=get_selected_class(),
    )


@bp.route("/room/<room_id>")
def room(room_id):
    if room_id not in ROOMS:
        abort(404)
    set_active_app(None)
    return render_template("room.html", room_id=room_id, room=ROOMS[room_id])


@bp.route("/classes/<int:class_id>", methods=["PATCH"])
def update_class(class_id):
    if not _is_admin_ip_allowed():
        abort(403)
    data = request.get_json(silent=True)
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str):
        return {"ok": False, "message": "반 이름을 입력해 주세요."}, 400
    name = name.strip()
    if not name or len(name) > 40:
        return {
            "ok": False,
            "message": "반 이름은 1~40자로 입력해 주세요.",
        }, 400

    db = get_db()
    try:
        cursor = db.execute(
            "UPDATE seating_classes SET name = ? WHERE id = ?",
            (name, class_id),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return {"ok": False, "message": "같은 이름의 반이 이미 있습니다."}, 409
    if cursor.rowcount == 0:
        return {"ok": False, "message": "선택한 반을 찾을 수 없습니다."}, 404
    return {"ok": True, "class": {"id": class_id, "name": name}}


@bp.route("/classes", methods=["POST"])
def create_class():
    if not _is_admin_ip_allowed():
        abort(403)
    data = request.get_json(silent=True)
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str):
        return {"ok": False, "message": "반 이름을 입력해 주세요."}, 400
    name = name.strip()
    if not name or len(name) > 40:
        return {
            "ok": False,
            "message": "반 이름은 1~40자로 입력해 주세요.",
        }, 400

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO seating_classes (name) VALUES (?)", (name,)
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return {"ok": False, "message": "같은 이름의 반이 이미 있습니다."}, 409
    return {
        "ok": True,
        "class": {"id": cursor.lastrowid, "name": name},
    }, 201


@bp.route("/classes/<int:class_id>", methods=["DELETE"])
def delete_class(class_id):
    if not _is_admin_ip_allowed():
        abort(403)
    from lobby import clear_selected_class

    db = get_db()
    if db.execute(
        "SELECT id FROM seating_classes WHERE id = ?", (class_id,)
    ).fetchone() is None:
        return {"ok": False, "message": "선택한 반을 찾을 수 없습니다."}, 404
    try:
        db.execute("DELETE FROM questions WHERE class_id = ?", (class_id,))
        db.execute("DELETE FROM seating_seats WHERE class_id = ?", (class_id,))
        db.execute(
            "DELETE FROM seating_locked_seats WHERE class_id = ?", (class_id,)
        )
        db.execute("DELETE FROM seating_classes WHERE id = ?", (class_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    clear_selected_class(class_id)
    return {"ok": True}


@bp.route("/user")
def user():
    return render_template(
        "user.html",
        code=request.args.get("code", ""),
        class_started=is_class_started(),
    )


@bp.route("/class-status")
def class_status():
    return {"started": is_class_started()}


@bp.route("/user/app/<app_id>")
def user_app(app_id):
    app_info = APPS.get(app_id)
    if app_info is None or not app_info["ready"]:
        abort(404)
    return render_template(f"apps/{app_id}_user.html")


@bp.route("/admin")
def admin_redirect():
    return redirect(url_for("main.app_page", app_id="drawing"))


@bp.route("/app/<app_id>", methods=["GET", "POST"])
def app_page(app_id):
    app_info = APPS.get(app_id)
    if app_info is None or not app_info["ready"]:
        abort(404)
    # 특별한 서버 처리가 필요한 앱만 HOST_HANDLERS에 등록한다.
    handler = HOST_HANDLERS.get(app_id)
    if handler is not None:
        return handler(app_info)
    set_active_app(app_id)
    return render_template(
        f"apps/{app_id}_host.html",
        room_id=app_info["room_id"],
        app=app_info,
    )


def _drawing_host(app_info):
    set_active_app(app_info["id"])
    db = get_db()
    themes = db.execute("SELECT id, name FROM themes ORDER BY id").fetchall()
    if request.method == "POST":
        try:
            theme_id = int(request.form.get("theme_id", ""))
            duration = int(request.form.get("round_duration", ""))
        except ValueError:
            abort(400, "테마와 라운드 시간을 올바르게 입력해 주세요.")
        if not 15 <= duration <= 300:
            abort(400, "라운드 시간은 15초에서 300초 사이여야 합니다.")
        theme = db.execute("SELECT id FROM themes WHERE id = ?", (theme_id,)).fetchone()
        if theme is None:
            abort(400, "존재하지 않는 테마입니다.")
        db.execute(
            "INSERT INTO settings (key, value) VALUES ('theme_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(theme_id),),
        )
        db.execute(
            "INSERT INTO settings (key, value) VALUES ('round_duration', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(duration),),
        )
        db.commit()
        return redirect(url_for("main.app_page", app_id="drawing"))

    settings = dict(
        db.execute("SELECT key, value FROM settings").fetchall()
    )
    selected_theme_id = int(settings.get("theme_id", themes[0]["id"]))
    selected_theme_name = next(
        theme["name"] for theme in themes if theme["id"] == selected_theme_id
    )
    words = db.execute(
        "SELECT word FROM words WHERE theme_id = ? ORDER BY word",
        (selected_theme_id,),
    ).fetchall()
    return render_template(
        "apps/drawing_host.html",
        themes=themes,
        selected_theme_id=selected_theme_id,
        selected_theme_name=selected_theme_name,
        round_duration=int(settings.get("round_duration", "60")),
        words=words,
        room_id=app_info["room_id"],
    )


HOST_HANDLERS = {"drawing": _drawing_host}
