import threading

from flask import request
from flask_socketio import join_room

from database import get_db
from extensions import socketio
import lobby

MAX_QUESTION_LENGTH = 500
HOST_ROOM = "question_hosts"

_lock = threading.RLock()
_pending_questions = {}
_next_pending_id = 1


def _error(message):
    return {"ok": False, "message": message}


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


def _saved_questions(class_id):
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
            "FROM questions WHERE class_id = ? "
            "ORDER BY id",
            (class_id,),
        ).fetchall()
    ]


def _questions_for_class(class_id):
    with _lock:
        pending = [
            _public_question(question)
            for question in _pending_questions.get(class_id, [])
        ]
    return _saved_questions(class_id) + pending


def _participants_for_questions(questions):
    participants = {}
    for question in questions:
        participant = participants.setdefault(
            question["name"],
            {"name": question["name"], "questions": []},
        )
        participant["questions"].append(question)
    return list(participants.values())


def _class_state(class_info):
    questions = _questions_for_class(class_info["id"])
    return {
        "ok": True,
        "class": class_info,
        "questions": questions,
        "participants": _participants_for_questions(questions),
    }


def _public_question(question):
    return {
        "id": question["id"],
        "name": question["name"],
        "question": question["question"],
        "created_at": question["created_at"],
        "saved": question["saved"],
    }


@socketio.on("question_sync")
def on_question_sync():
    if not _is_host():
        return _error("호스트만 질문을 볼 수 있습니다.")
    selected_class = lobby.get_selected_class()
    if selected_class is None:
        return _error("홈에서 먼저 반을 선택해 주세요.")
    join_room(HOST_ROOM)
    return _class_state(selected_class)


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

    global _next_pending_id
    with _lock:
        pending = _pending_questions.setdefault(class_id, [])
        item = {
            "id": f"pending-{_next_pending_id}",
            "client_id": client_id,
            "name": user["name"],
            "question": question,
            "created_at": None,
            "saved": False,
        }
        _next_pending_id += 1
        pending.append(item)
    socketio.emit(
        "question_asked",
        {"question": _public_question(item)},
        to=HOST_ROOM,
    )
    return {"ok": True}


@socketio.on("save_questions")
def on_save_questions(data=None):
    if not _is_host():
        return _error("호스트만 질문을 저장할 수 있습니다.")
    selected_class = lobby.get_selected_class()
    if selected_class is None:
        return _error("홈에서 먼저 반을 선택해 주세요.")
    class_id = selected_class["id"]
    participant_name = data.get("name") if isinstance(data, dict) else None

    with _lock:
        queued = list(_pending_questions.get(class_id, []))
        pending = [
            item
            for item in queued
            if participant_name is None or item["name"] == participant_name
        ]
        if pending:
            pending_ids = {id(item) for item in pending}
            _pending_questions[class_id] = [
                item for item in queued if id(item) not in pending_ids
            ]
    if not pending:
        state = _class_state(selected_class)
        state["saved_count"] = 0
        return state

    db = get_db()
    try:
        db.executemany(
            "INSERT INTO questions "
            "(class_id, client_id, participant_name, question) "
            "VALUES (?, ?, ?, ?)",
            (
                (class_id, item["client_id"], item["name"], item["question"])
                for item in pending
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        with _lock:
            _pending_questions[class_id][:0] = pending
        raise
    state = _class_state(selected_class)
    state["saved_count"] = len(pending)
    return state
