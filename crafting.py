import threading

from flask import request
from flask_socketio import join_room

import lobby
from extensions import socketio
from teams import TeamManager


HOST_ROOM = "crafting_hosts"
_lock = threading.RLock()
_teams = TeamManager(mode="random", team_count=2)


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


def _refresh_participants_locked():
    participants = {
        client_id: name
        for client_id, name, sid in lobby.online_user_sessions()
    }
    _teams.set_participants(participants)


def broadcast_state():
    with _lock:
        _refresh_participants_locked()
        host_state = _teams.host_state()
        sessions = lobby.online_user_sessions()
    socketio.emit("crafting_team_state", host_state, to=HOST_ROOM)
    for client_id, name, sid in sessions:
        socketio.emit(
            "crafting_team_state",
            _teams.participant_state(client_id),
            to=sid,
        )


@socketio.on("crafting_team_sync")
def on_crafting_team_sync():
    if _is_host():
        join_room(HOST_ROOM)
        with _lock:
            _refresh_participants_locked()
            state = _teams.host_state()
        return {"ok": True, "host": True, **state}

    client_id, user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    with _lock:
        _refresh_participants_locked()
        state = _teams.participant_state(client_id)
    return {"ok": True, "host": False, **state}


@socketio.on("crafting_team_configure")
def on_crafting_team_configure(data=None):
    if not _is_host():
        return {"ok": False, "message": "호스트만 팀을 설정할 수 있습니다."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "팀 설정이 올바르지 않습니다."}

    ok, message = _teams.configure(
        data.get("mode"),
        data.get("team_count"),
        data.get("team_names"),
    )
    if not ok:
        return {"ok": False, "message": message}
    broadcast_state()
    with _lock:
        state = _teams.host_state()
    return {"ok": True, **state}


@socketio.on("crafting_team_assign")
def on_crafting_team_assign(data=None):
    if not _is_host():
        return {"ok": False, "message": "호스트만 팀 배정을 변경할 수 있습니다."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "팀 배정 정보가 올바르지 않습니다."}

    client_id = data.get("client_id")
    team_id = data.get("team_id")
    ok, message = _teams.assign(client_id, team_id)
    if not ok:
        return {"ok": False, "message": message}
    broadcast_state()
    return {"ok": True}


@socketio.on("crafting_team_choose")
def on_crafting_team_choose(data=None):
    client_id, _ = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "팀 선택 정보가 올바르지 않습니다."}

    ok, message = _teams.choose_team(client_id, data.get("team_id"))
    if not ok:
        return {"ok": False, "message": message}
    broadcast_state()
    return {"ok": True}


@socketio.on("crafting_team_randomize")
def on_crafting_team_randomize():
    if not _is_host():
        return {"ok": False, "message": "호스트만 팀을 섞을 수 있습니다."}
    with _lock:
        _refresh_participants_locked()
        _teams.randomize()
    broadcast_state()
    return {"ok": True}
