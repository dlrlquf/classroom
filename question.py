import threading

from flask import request
from flask_socketio import join_room

from database import get_db
from extensions import socketio
import lobby

MAX_QUESTION_LENGTH = 500
MAX_SESSION_NAME_LENGTH = 60
HOST_ROOM = "question_hosts"

_lock = threading.RLock()


def _error(message):
    return {"ok": False, "message": message}


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


def _sessions_for_class(class_id):
    return [
        dict(row)
        for row in get_db().execute(
            "SELECT id, name, created_at, is_active FROM question_sessions "
            "WHERE class_id = ? ORDER BY id DESC",
            (class_id,),
        ).fetchall()
    ]


def _active_session(class_id):
    row = get_db().execute(
        "SELECT id, name FROM question_sessions "
        "WHERE class_id = ? AND is_active = 1",
        (class_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _saved_questions(session_id):
    return [
        {
            "id": row["id"],
            "name": row["participant_name"],
            "question": row["question"],
            "created_at": row["created_at"],
            "saved": True,
        }
        for row in get_db().execute(
            "SELECT id, participant_name, question, created_at "
            "FROM questions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    ]


def _class_state(class_info):
    active_session = _active_session(class_info["id"])
    return {
        "ok": True,
        "class": class_info,
        "sessions": _sessions_for_class(class_info["id"]),
        "active_session": active_session,
        "questions": (
            _saved_questions(active_session["id"]) if active_session else []
        ),
    }


def _participants_for_questions(questions):
    participants = {}
    for question in questions:
        participant = participants.setdefault(
            question["name"],
            {"name": question["name"], "questions": []},
        )
        participant["questions"].append(question)
    return list(participants.values())


def _public_question(question):
    return {
        "id": question["id"],
        "name": question["name"],
        "question": question["question"],
        "created_at": question["created_at"],
        "saved": True,
    }


def _broadcast_session_state(class_info):
    state = _class_state(class_info)
    socketio.emit("question_session_state", state, to=HOST_ROOM)
    socketio.emit(
        "question_active_session",
        {"active_session": state["active_session"]},
    )
    return state


@socketio.on("question_sync")
def on_question_sync():
    if not _is_host():
        return _error("호스트만 질문을 볼 수 있습니다.")
    selected_class = lobby.get_selected_class()
    if selected_class is None:
        return _error("홈에서 먼저 반을 선택해 주세요.")
    join_room(HOST_ROOM)
    return _class_state(selected_class)


@socketio.on("question_session_sync")
def on_question_session_sync():
    client_id, user = lobby.get_user_by_sid(request.sid)
    if client_id is None or user is None:
        return _error("먼저 수업에 참가해 주세요.")
    class_id = lobby.get_selected_class_id()
    if user.get("class_id") != class_id:
        return _error("현재 선택된 반 정보가 변경되었습니다. 다시 접속해 주세요.")
    return {"ok": True, "active_session": _active_session(class_id)}


@socketio.on("create_question_session")
def on_create_question_session(data=None):
    if not _is_host():
        return _error("호스트만 질문 세션을 만들 수 있습니다.")
    selected_class = lobby.get_selected_class()
    if selected_class is None:
        return _error("홈에서 먼저 반을 선택해 주세요.")
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return _error("세션 이름을 입력해 주세요.")
    name = data["name"].strip()
    if not name or len(name) > MAX_SESSION_NAME_LENGTH:
        return _error(f"세션 이름은 1~{MAX_SESSION_NAME_LENGTH}자로 입력해 주세요.")

    class_id = selected_class["id"]
    db = get_db()
    with _lock:
        duplicate = db.execute(
            "SELECT 1 FROM question_sessions "
            "WHERE class_id = ? AND name = ? COLLATE NOCASE",
            (class_id, name),
        ).fetchone()
        if duplicate:
            return _error("같은 이름의 세션이 이미 있습니다.")
        db.execute(
            "UPDATE question_sessions SET is_active = 0 WHERE class_id = ?",
            (class_id,),
        )
        db.execute(
            "INSERT INTO question_sessions (class_id, name, is_active) "
            "VALUES (?, ?, 1)",
            (class_id, name),
        )
        db.commit()
    return _broadcast_session_state(selected_class)


@socketio.on("select_question_session")
def on_select_question_session(data=None):
    if not _is_host():
        return _error("호스트만 질문 세션을 선택할 수 있습니다.")
    selected_class = lobby.get_selected_class()
    if selected_class is None:
        return _error("홈에서 먼저 반을 선택해 주세요.")
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if not isinstance(session_id, int) or isinstance(session_id, bool):
        return _error("세션 정보가 올바르지 않습니다.")

    class_id = selected_class["id"]
    db = get_db()
    with _lock:
        session = db.execute(
            "SELECT id FROM question_sessions WHERE id = ? AND class_id = ?",
            (session_id, class_id),
        ).fetchone()
        if session is None:
            return _error("선택한 세션을 찾을 수 없습니다.")
        db.execute(
            "UPDATE question_sessions SET is_active = 0 WHERE class_id = ?",
            (class_id,),
        )
        db.execute(
            "UPDATE question_sessions SET is_active = 1 WHERE id = ?",
            (session_id,),
        )
        db.commit()
    return _broadcast_session_state(selected_class)


@socketio.on("ask_question")
def on_ask_question(data=None):
    client_id, user = lobby.get_user_by_sid(request.sid)
    if client_id is None or user is None:
        return _error("먼저 수업에 참가해 주세요.")
    if not isinstance(data, dict):
        return _error("질문 정보가 올바르지 않습니다.")
    question = data.get("question")
    if not isinstance(question, str):
        return _error("질문을 입력해 주세요.")
    question = question.strip()
    if not question or len(question) > MAX_QUESTION_LENGTH:
        return _error(f"질문은 1~{MAX_QUESTION_LENGTH}자로 입력해 주세요.")

    class_id = user.get("class_id")
    selected_class_id = lobby.get_selected_class_id()
    if class_id is None or class_id != selected_class_id:
        return _error("현재 선택된 반 정보가 변경되었습니다. 다시 접속해 주세요.")

    db = get_db()
    with _lock:
        session = _active_session(class_id)
        if session is None:
            return _error("호스트가 질문 세션을 열지 않았습니다.")
        cursor = db.execute(
            "INSERT INTO questions "
            "(class_id, session_id, client_id, participant_name, question) "
            "VALUES (?, ?, ?, ?, ?)",
            (class_id, session["id"], client_id, user["name"], question),
        )
        created_at = db.execute(
            "SELECT created_at FROM questions WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()["created_at"]
        db.commit()

    item = {
        "id": cursor.lastrowid,
        "name": user["name"],
        "question": question,
        "created_at": created_at,
        "saved": True,
    }
    socketio.emit(
        "question_asked",
        {"session_id": session["id"], "question": _public_question(item)},
        to=HOST_ROOM,
    )
    return {"ok": True, "session": session}
