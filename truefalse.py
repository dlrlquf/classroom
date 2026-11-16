import threading

from flask import request

import lobby
from extensions import socketio

CHOICES = ("참", "거짓")

_lock = threading.RLock()
_votes = {}


def _state_locked():
    users = lobby.online_users()
    state = {choice: [] for choice in CHOICES}
    state["none"] = []
    for client_id, name in users.items():
        choice = _votes.get(client_id)
        state[choice if choice in CHOICES else "none"].append(name)
    for names in state.values():
        names.sort(key=str.casefold)
    return state


def broadcast_state():
    with _lock:
        state = _state_locked()
    socketio.emit("tf_state", state)


@socketio.on("tf_vote")
def on_tf_vote(data=None):
    choice = data.get("choice") if isinstance(data, dict) else None
    if choice not in CHOICES:
        return {"ok": False, "message": "선택이 올바르지 않습니다."}
    client_id, _ = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    with _lock:
        _votes[client_id] = choice
    broadcast_state()
    return {"ok": True, "choice": choice}


@socketio.on("tf_my_choice")
def on_tf_my_choice():
    client_id, _ = lobby.get_user_by_sid(request.sid)
    with _lock:
        return {"ok": True, "choice": _votes.get(client_id)}


@socketio.on("tf_sync")
def on_tf_sync():
    from routes import _is_admin_ip_allowed

    if not _is_admin_ip_allowed():
        return {"ok": False}
    with _lock:
        return {"ok": True, "state": _state_locked()}


@socketio.on("tf_reset")
def on_tf_reset():
    from routes import _is_admin_ip_allowed

    if not _is_admin_ip_allowed():
        return {"ok": False}
    with _lock:
        _votes.clear()
    socketio.emit("tf_cleared")
    broadcast_state()
    return {"ok": True}
