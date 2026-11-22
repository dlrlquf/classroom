import re
import secrets
import threading

from flask import request

from database import get_db
import events
from extensions import socketio

# 방 -> 앱 목록. 새 앱은 여기에 추가한다. 아직 구현되지 않은 앱은 ready=False.
ROOMS = {
    "class": {
        "name": "수업방",
        "apps": [
            {
                "id": "truefalse",
                "name": "참 / 거짓",
                "description": "참가자가 참 또는 거짓을 고르고 호스트가 선택 결과를 봅니다.",
                "ready": True,
            },
            {
                "id": "responses",
                "name": "응답 수집",
                "description": "참 / 거짓, 1~5 선택, 짧은 답변을 배포하고 결과를 모읍니다.",
                "ready": True,
            },
            {
                "id": "seating",
                "name": "자리 배치",
                "description": "반별 명단을 관리하고 드래그 앤 드랍으로 자리를 배치합니다.",
                "ready": True,
            },
            {
                "id": "question",
                "name": "질문하기",
                "description": "참가자들이 수업 흐름에 따라 활동합니다.",
                "ready": True,
            },
            {
                "id": "oneofmany",
                "name": "하나를 고르기",
                "description": "참가자들이 여러 선택지 중 하나를 고릅니다.",
                "ready": False
            }
            ,
            {
                "id": "class_quiz",
                "name": "퀴즈",
                "description": "호스트가 문제를 내고 참가자가 답을 맞춥니다.",
                "ready": False
            },
            {
                "id": "wordart",
                "name": "워드 아트",
                "description": "참가자들이 단어를 가지고 그림을 만듭니다.",
                "ready": False
            }
        ],
    },
    "game": {
        "name": "게임방",
        "apps": [
            {
                "id": "drawing",
                "name": "그림 맞추기",
                "description": "한 명이 그림을 그리고 나머지가 정답을 맞힙니다.",
                "ready": True,
            },
            {
                "id": "mindgame",
                "name": "눈치게임",
                "description": "참가자가 차례로 버튼을 누르며, 너무 빠르게 이어 누르면 게임이 끝납니다.",
                "ready": True,
            },
            {
                "id": "landgrab",
                "name": "땅따먹기",
                "description": "자원을 모아 인접한 땅을 구매하고 영토를 넓힙니다.",
                "ready": True,
            },
            {
                "id": "crafting",
                "name": "자원으로 물건 만들기",
                "description": "자원을 모아 물건을 만드는 게임입니다.",
                "ready": True,
            },
            {
                "id": "liar",
                "name": "라이어 게임",
                "description": "참가자 중 한 명이 거짓말을 하고 나머지가 이를 맞춥니다.",
                "ready": False
            },
            {
                "id": "game_quiz",
                "name": "퀴즈",
                "description": "호스트가 문제를 내고 참가자가 답을 맞춥니다.",
                "ready": False
            },
            {
                "id": "trading",
                "name": "트레이딩 게임",
                "description": "참가자들이 거래를 통해 자원을 모읍니다.",
                "ready": False
            },
            {
                "id": "food_chain",
                "name": "먹이사슬",
                "description": "참가자들은 야생에서 승리를 위해 경쟁합니다.",
                "ready": False
            }
        ],
    },
    "share": {"name": "나눔방", "apps": []},
}
APPS = {}
for _room_id, _room in ROOMS.items():
    for _app in _room["apps"]:
        if _app["id"] in APPS:
            raise ValueError(f"앱 id가 중복되었습니다: {_app['id']}")
        APPS[_app["id"]] = {**_app, "room_id": _room_id}

CLIENT_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{16,64}")

_lock = threading.RLock()
# 서버 전체에서 접속 코드 하나, 참가자 풀 하나를 쓴다. 모든 앱이 현재 참가자를 그대로 사용한다.
_code = f"{secrets.randbelow(10**6):06d}"
_users = {}
_active_app = None
_selected_class_id = None
_class_started = False


def get_code():
    return _code


def get_class_list():
    return [
        {"id": row["id"], "name": row["name"]}
        for row in get_db().execute(
            "SELECT id, name FROM seating_classes ORDER BY name COLLATE NOCASE"
        ).fetchall()
    ]


def get_selected_class_id():
    global _selected_class_id
    if _selected_class_id is not None:
        return _selected_class_id

    setting = get_db().execute(
        "SELECT value FROM settings WHERE key = 'selected_class_id'"
    ).fetchone()
    if setting is None:
        return None
    try:
        class_id = int(setting["value"])
    except (TypeError, ValueError):
        return None
    row = get_db().execute(
        "SELECT id FROM seating_classes WHERE id = ?", (class_id,)
    ).fetchone()
    if row is None:
        return None
    _selected_class_id = class_id
    return class_id


def get_selected_class():
    class_id = get_selected_class_id()
    if class_id is None:
        return None
    row = get_db().execute(
        "SELECT id, name FROM seating_classes WHERE id = ?", (class_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"]}


def is_class_started():
    with _lock:
        return _class_started


def clear_selected_class(class_id):
    global _selected_class_id
    with _lock:
        if _selected_class_id == class_id:
            _selected_class_id = None
            get_db().execute(
                "DELETE FROM settings WHERE key = 'selected_class_id'"
            )
            get_db().commit()


def stop_class():
    global _class_started
    with _lock:
        _class_started = False
        online_sids = [
            user["sid"] for user in _users.values() if user["online"]
        ]
        for user in _users.values():
            if user["online"]:
                user["online"] = False
    socketio.emit("class_stopped")
    for sid in online_sids:
        socketio.server.disconnect(sid)
    _broadcast_participants()


def _set_selected_class_id(class_id):
    global _selected_class_id, _class_started
    row = get_db().execute(
        "SELECT id, name FROM seating_classes WHERE id = ?", (class_id,)
    ).fetchone()
    if row is None:
        return None
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES ('selected_class_id', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(class_id),),
    )
    db.commit()
    with _lock:
        _selected_class_id = class_id
        _class_started = True
        for user in _users.values():
            user["class_id"] = class_id
    return {"id": row["id"], "name": row["name"]}


def _participants_locked():
    return [
        {"name": user["name"]}
        for user in _users.values()
        if user["online"]
    ]


def _broadcast_participants():
    with _lock:
        data = _participants_locked()
    socketio.emit("participants", {"participants": data})


def set_active_app(app_id):
    """호스트가 앱을 열거나 닫을 때 호출한다. 접속 중인 참가자 화면도 함께 바뀐다."""
    global _active_app
    with _lock:
        if _active_app == app_id:
            return
        _active_app = app_id
    socketio.emit("app_changed", {"app": app_id})


def get_user_by_sid(sid):
    with _lock:
        for client_id, user in _users.items():
            if user["sid"] == sid and user["online"]:
                return client_id, dict(user)
    return None, None


def online_users():
    with _lock:
        return {
            client_id: user["name"]
            for client_id, user in _users.items()
            if user["online"]
        }


def online_user_sessions():
    with _lock:
        return [
            (client_id, user["name"], user["sid"])
            for client_id, user in _users.items()
            if user["online"]
        ]


def _error(message):
    return {"ok": False, "message": message}


def on_disconnect(sid):
    with _lock:
        changed = False
        for user in _users.values():
            if user["sid"] == sid and user["online"]:
                user["online"] = False
                changed = True
    if changed:
        _broadcast_participants()
        import truefalse
        import crafting

        truefalse.broadcast_state()
        crafting.broadcast_state()


@socketio.on("participants_sync")
def on_participants_sync():
    from routes import _is_admin_ip_allowed

    if not _is_admin_ip_allowed():
        return _error("호스트만 사용할 수 있습니다.")
    with _lock:
        return {"ok": True, "participants": _participants_locked()}


@socketio.on("user_join")
def on_user_join(data=None):
    if not isinstance(data, dict):
        return _error("접속 정보가 올바르지 않습니다.")
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    client_id = str(data.get("client_id", ""))
    if not CLIENT_ID_PATTERN.fullmatch(client_id):
        return _error("기기 식별값이 올바르지 않습니다.")
    if code != _code:
        return _error("접속 코드가 올바르지 않습니다.")
    if not events.is_valid_nickname(name):
        return _error("이름은 1~16자이며 한글, 영문, 숫자를 사용할 수 있습니다.")
    if not is_class_started():
        return _error("호스트가 수업을 아직 시작하지 않았습니다.")
    class_id = get_selected_class_id()
    if class_id is None:
        return _error("호스트가 수업 반을 아직 선택하지 않았습니다.")

    with _lock:
        if any(
            other_id != client_id
            and other["online"]
            and other["name"].casefold() == name.casefold()
            for other_id, other in _users.items()
        ):
            return _error("이미 사용 중인 이름입니다.")
        user = _users.get(client_id)
        old_sid = user["sid"] if user else None
        notice = None
        if old_sid is not None and events.has_player(old_sid):
            # 같은 기기의 재접속: 기존 게임 상태를 새 연결로 옮긴다.
            events.rekey_player(old_sid, request.sid)
            reconnected = True
        else:
            reconnected = False
            notice = events.join_game(request.sid, name)
        _users[client_id] = {
            "name": name,
            "sid": request.sid,
            "online": True,
            "class_id": class_id,
        }
        active_app = _active_app

    _broadcast_participants()
    import truefalse
    import crafting

    truefalse.broadcast_state()
    crafting.broadcast_state()
    return {
        "ok": True,
        "app": active_app,
        "name": name,
        "reconnected": reconnected,
        "notice": notice,
    }


@socketio.on("lobby_select_class")
def on_lobby_select_class(data=None):
    from routes import _is_admin_ip_allowed

    if not _is_admin_ip_allowed():
        return _error("호스트만 반을 선택할 수 있습니다.")
    class_id = data.get("class_id") if isinstance(data, dict) else None
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        return _error("반 정보를 올바르게 선택해 주세요.")
    selected_class = _set_selected_class_id(class_id)
    if selected_class is None:
        return _error("선택한 반을 찾을 수 없습니다.")
    return {"ok": True, "class": selected_class}
