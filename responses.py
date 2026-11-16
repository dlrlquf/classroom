from flask import request
from flask_socketio import join_room

from database import get_db
from extensions import socketio
import lobby

HOST_ROOM = "response_hosts"
MODULES = {
    "truefalse": {"name": "참 / 거짓", "options": ("참", "거짓")},
    "scale": {"name": "1~5 선택", "options": ("1", "2", "3", "4", "5")},
    "short_text": {"name": "짧은 답변", "options": None},
}
MAX_PROMPT_LENGTH = 120
MAX_ANSWER_LENGTH = 40


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


def _run_payload(db, run):
    if run is None:
        return None

    answers = db.execute(
        "SELECT participant_name, answer, submitted_at "
        "FROM response_answers WHERE run_id = ? "
        "ORDER BY submitted_at, participant_name",
        (run["id"],),
    ).fetchall()
    options = MODULES[run["module_type"]]["options"]
    if options is None:
        counts = {}
        for answer in answers:
            counts[answer["answer"]] = counts.get(answer["answer"], 0) + 1
    else:
        counts = {option: 0 for option in options}
        for answer in answers:
            counts[answer["answer"]] += 1

    return {
        "id": run["id"],
        "type": run["module_type"],
        "type_name": MODULES[run["module_type"]]["name"],
        "prompt": run["prompt"],
        "status": run["status"],
        "created_at": run["created_at"],
        "ended_at": run["ended_at"],
        "counts": counts,
        "responses": [
            {
                "name": answer["participant_name"],
                "answer": answer["answer"],
                "submitted_at": answer["submitted_at"],
            }
            for answer in answers
        ],
    }


def _host_state(db):
    active = db.execute(
        "SELECT * FROM response_runs WHERE status = 'active'"
    ).fetchone()
    history = db.execute(
        "SELECT * FROM response_runs WHERE status = 'closed' "
        "ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return {
        "run": _run_payload(db, active),
        "history": [_run_payload(db, run) for run in history],
    }


def _public_run(run):
    if run is None:
        return None
    return {
        "id": run["id"],
        "type": run["module_type"],
        "type_name": MODULES[run["module_type"]]["name"],
        "prompt": run["prompt"],
        "status": run["status"],
        "created_at": run["created_at"],
    }


def _emit_host_state(db):
    socketio.emit("responses_state", _host_state(db), to=HOST_ROOM)


@socketio.on("responses_sync")
def on_responses_sync():
    if not _is_host():
        return {"ok": False, "message": "호스트만 사용할 수 있습니다."}
    join_room(HOST_ROOM)
    return {"ok": True, **_host_state(get_db())}


@socketio.on("response_sync")
def on_response_sync():
    client_id, _ = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}

    db = get_db()
    run = db.execute(
        "SELECT * FROM response_runs WHERE status = 'active'"
    ).fetchone()
    payload = _public_run(run)
    answer = None
    if run is not None:
        row = db.execute(
            "SELECT answer FROM response_answers "
            "WHERE run_id = ? AND client_id = ?",
            (run["id"], client_id),
        ).fetchone()
        answer = row["answer"] if row is not None else None
    return {"ok": True, "run": payload, "answer": answer}


@socketio.on("response_start")
def on_response_start(data=None):
    if not _is_host():
        return {"ok": False, "message": "호스트만 사용할 수 있습니다."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "실행 정보가 올바르지 않습니다."}

    module_type = data.get("type")
    prompt = data.get("prompt")
    if not isinstance(module_type, str) or module_type not in MODULES:
        return {"ok": False, "message": "응답 유형이 올바르지 않습니다."}
    if not isinstance(prompt, str):
        return {"ok": False, "message": "질문을 입력해 주세요."}
    prompt = prompt.strip()
    if not prompt or len(prompt) > MAX_PROMPT_LENGTH:
        return {
            "ok": False,
            "message": f"질문은 1~{MAX_PROMPT_LENGTH}자로 입력해 주세요.",
        }

    join_room(HOST_ROOM)
    db = get_db()
    db.execute(
        "UPDATE response_runs SET status = 'closed', ended_at = CURRENT_TIMESTAMP "
        "WHERE status = 'active'"
    )
    cursor = db.execute(
        "INSERT INTO response_runs (module_type, prompt, status) "
        "VALUES (?, ?, 'active')",
        (module_type, prompt),
    )
    db.commit()
    run = db.execute(
        "SELECT * FROM response_runs WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    payload = _run_payload(db, run)
    socketio.emit("response_started", payload)
    _emit_host_state(db)
    return {"ok": True, "run": payload}


@socketio.on("response_submit")
def on_response_submit(data=None):
    client_id, user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "응답 정보가 올바르지 않습니다."}

    run_id = data.get("run_id")
    answer = data.get("answer")
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        return {"ok": False, "message": "실행 정보가 올바르지 않습니다."}
    if not isinstance(answer, str):
        return {"ok": False, "message": "답변 형식이 올바르지 않습니다."}

    db = get_db()
    run = db.execute(
        "SELECT * FROM response_runs WHERE id = ? AND status = 'active'",
        (run_id,),
    ).fetchone()
    if run is None:
        return {"ok": False, "message": "응답을 받는 활동이 아닙니다."}

    answer = answer.strip()
    module = MODULES[run["module_type"]]
    if module["options"] is not None and answer not in module["options"]:
        return {"ok": False, "message": "선택한 답변이 올바르지 않습니다."}
    if module["options"] is None and (
        not answer or len(answer) > MAX_ANSWER_LENGTH
    ):
        return {
            "ok": False,
            "message": f"답변은 1~{MAX_ANSWER_LENGTH}자로 입력해 주세요.",
        }

    db.execute(
        "INSERT INTO response_answers "
        "(run_id, client_id, participant_name, answer) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(run_id, client_id) DO UPDATE SET "
        "participant_name = excluded.participant_name, "
        "answer = excluded.answer, submitted_at = CURRENT_TIMESTAMP",
        (run_id, client_id, user["name"], answer),
    )
    db.commit()
    _emit_host_state(db)
    return {"ok": True, "answer": answer}


@socketio.on("response_stop")
def on_response_stop():
    if not _is_host():
        return {"ok": False, "message": "호스트만 사용할 수 있습니다."}
    db = get_db()
    active = db.execute(
        "SELECT id FROM response_runs WHERE status = 'active'"
    ).fetchone()
    db.execute(
        "UPDATE response_runs SET status = 'closed', ended_at = CURRENT_TIMESTAMP "
        "WHERE status = 'active'"
    )
    db.commit()
    if active is not None:
        socketio.emit("response_ended", {"run_id": active["id"]})
    _emit_host_state(db)
    return {"ok": True}
