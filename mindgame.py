import threading
import time

from flask import request
from flask_socketio import join_room

import lobby
from extensions import socketio

HOST_ROOM = "mindgame_hosts"
MIN_INTERVAL_MS = 100
MAX_INTERVAL_MS = 60_000

_lock = threading.RLock()
_phase = "waiting"
_interval_ms = 2_000
_last_click_at = None
_clicks = []
_clicked_clients = set()
_game_over = None


def _state_locked():
    return {
        "phase": _phase,
        "interval_ms": _interval_ms,
        "clicks": list(_clicks),
        "game_over": dict(_game_over) if _game_over else None,
    }


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


@socketio.on("mindgame_sync")
def on_mindgame_sync():
    if _is_host():
        join_room(HOST_ROOM)
        with _lock:
            return {"ok": True, **_state_locked()}

    client_id, _ = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    with _lock:
        return {
            "ok": True,
            "phase": _phase,
            "interval_ms": _interval_ms,
            "already_clicked": client_id in _clicked_clients,
            "game_over": dict(_game_over) if _game_over else None,
        }


@socketio.on("mindgame_start")
def on_mindgame_start(data=None):
    global _phase, _interval_ms, _last_click_at, _clicks
    global _clicked_clients, _game_over

    if not _is_host():
        return {"ok": False, "message": "호스트만 게임을 시작할 수 있습니다."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "게임 설정이 올바르지 않습니다."}

    interval_ms = data.get("interval_ms")
    if (
        isinstance(interval_ms, bool)
        or not isinstance(interval_ms, int)
        or not MIN_INTERVAL_MS <= interval_ms <= MAX_INTERVAL_MS
    ):
        return {
            "ok": False,
            "message": "판정 간격은 0.1초에서 60초 사이여야 합니다.",
        }

    with _lock:
        _phase = "playing"
        _interval_ms = interval_ms
        _last_click_at = None
        _clicks = []
        _clicked_clients = set()
        _game_over = None
        state = _state_locked()

    socketio.emit("mindgame_started", {"interval_ms": interval_ms})
    socketio.emit("mindgame_state", state, to=HOST_ROOM)
    return {"ok": True, **state}


@socketio.on("mindgame_stop")
def on_mindgame_stop():
    global _phase

    if not _is_host():
        return {"ok": False, "message": "호스트만 게임을 종료할 수 있습니다."}

    with _lock:
        if _phase != "playing":
            return {"ok": False, "message": "진행 중인 눈치게임이 없습니다."}
        _phase = "ended"
        state = _state_locked()

    socketio.emit("mindgame_ended")
    socketio.emit("mindgame_state", state, to=HOST_ROOM)
    return {"ok": True, **state}


@socketio.on("mindgame_click")
def on_mindgame_click():
    global _phase, _last_click_at, _game_over

    client_id, user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}

    now = time.monotonic()
    with _lock:
        if _phase != "playing":
            return {"ok": False, "message": "현재 진행 중인 눈치게임이 없습니다."}
        if client_id in _clicked_clients:
            return {"ok": False, "message": "이번 게임에서 이미 버튼을 눌렀습니다."}

        _clicked_clients.add(client_id)
        gap_ms = (
            None
            if _last_click_at is None
            else round((now - _last_click_at) * 1000)
        )
        if gap_ms is not None and gap_ms <= _interval_ms:
            _phase = "game_over"
            _game_over = {
                "name": user["name"],
                "gap_ms": gap_ms,
                "interval_ms": _interval_ms,
            }
            game_over = dict(_game_over)
            state = _state_locked()
        else:
            _clicks.append(
                {
                    "number": len(_clicks) + 1,
                    "name": user["name"],
                }
            )
            _last_click_at = now
            game_over = None
            state = _state_locked()

    if game_over is not None:
        socketio.emit("mindgame_over", game_over)
    socketio.emit("mindgame_state", state, to=HOST_ROOM)
    return {"ok": True, "game_over": game_over, "state": state}
