import math
import random
import re
import threading
import time

from flask import current_app, request

from database import get_db
from extensions import socketio

DRAWING_WIDTH = 800
DRAWING_HEIGHT = 500
MAX_DRAWING_WIDTH = 40
MAX_STROKES_PER_MESSAGE = 50
MAX_POINTS_PER_STROKE = 500
DRAWING_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")
MAX_STORED_STROKES = 200
MAX_STORED_POINTS = 20000
MAX_CHAT_LENGTH = 200
NICKNAME_PATTERN = re.compile(r"[\w가-힣 -]{1,16}", re.UNICODE)

_lock = threading.RLock()
_players = {}
_host_sids = set()
_phase = "lobby"
_theme_name = None
_round_duration = 60
_word_list = []
_used_words = set()
_order = []
_round_index = 0
_round_number = 0
_round = None
_round_results = []
_participants = {}
_scores = {}
_answer_times = {}
_strokes = []


def _player_list_locked():
    return [
        {
            "nickname": player["nickname"],
            "score": _scores.get(sid, 0),
            "solved": bool(_round and sid in _round["solved"]),
        }
        for sid, player in _players.items()
    ]


def _public_round_locked():
    if _round is None:
        return None
    return {
        "number": _round["number"],
        "drawer_sid": _round["drawer_sid"],
        "drawer_name": _participants[_round["drawer_sid"]],
        "ends_at": _round["ends_at"],
        "duration": _round_duration,
        "solved_count": len(_round["solved"]),
        "eligible_count": sum(
            sid != _round["drawer_sid"] for sid in _players
        ),
    }


def _game_state_locked():
    return {
        "phase": _phase,
        "theme": _theme_name,
        "round": _public_round_locked(),
        "players": _player_list_locked(),
    }


def _emit_room_update():
    with _lock:
        data = _game_state_locked()
        socketio.emit("game_state", data)


def _make_round_locked():
    global _round, _round_number, _strokes, _phase
    while _round_index < len(_order) and _order[_round_index] not in _players:
        _round_index_increment()
    if _round_index >= len(_order):
        _round = None
        _phase = "finished"
        return None

    drawer_sid = _order[_round_index]
    available_words = [word for word in _word_list if word not in _used_words]
    if not available_words:
        _used_words.clear()
        available_words = list(_word_list)
    word = random.choice(available_words)
    _used_words.add(word)
    _round_number += 1
    started_at = time.time()
    _round = {
        "id": _round_number,
        "number": _round_index + 1,
        "drawer_sid": drawer_sid,
        "word": word,
        "started_at": started_at,
        "started_monotonic": time.monotonic(),
        "ends_at": started_at + _round_duration,
        "solved": set(),
    }
    _strokes = []
    _phase = "playing"
    return {
        "id": _round["id"],
        "number": _round["number"],
        "total": len(_order),
        "drawer_sid": drawer_sid,
        "drawer_name": _participants[drawer_sid],
        "theme": _theme_name,
        "ends_at": _round["ends_at"],
        "duration": _round_duration,
        "word": word,
    }


def _round_index_increment():
    global _round_index
    _round_index += 1


def _statistics_locked():
    results = []
    for sid, nickname in _participants.items():
        times = _answer_times.get(sid, [])
        results.append(
            {
                "nickname": nickname,
                "correct_count": _scores.get(sid, 0),
                "average_seconds": (
                    round(sum(times) / len(times), 1) if times else None
                ),
                "answer_times": [round(seconds, 1) for seconds in times],
            }
        )
    results.sort(
        key=lambda item: (
            -item["correct_count"],
            item["average_seconds"]
            if item["average_seconds"] is not None
            else float("inf"),
        )
    )
    return {"players": results, "rounds": list(_round_results)}


def _should_finish_round_locked():
    if _round is None:
        return False
    eligible = [
        sid for sid in _players if sid != _round["drawer_sid"]
    ]
    return all(sid in _round["solved"] for sid in eligible)


def _finish_round(round_id=None):
    global _round, _phase, _round_index
    with _lock:
        if (
            _phase != "playing"
            or _round is None
            or (round_id is not None and _round["id"] != round_id)
        ):
            return False
        finished = _round
        elapsed = min(
            time.monotonic() - finished["started_monotonic"],
            _round_duration,
        )
        _round_results.append(
            {
                "number": finished["number"],
                "drawer": _participants[finished["drawer_sid"]],
                "word": finished["word"],
                "correct_count": len(finished["solved"]),
                "seconds": round(elapsed, 1),
            }
        )
        solved_names = [
            _participants[sid]
            for sid in finished["solved"]
            if sid in _participants
        ]
        _round = None
        _round_index += 1
        next_round = _make_round_locked()
        complete = next_round is None
        statistics = _statistics_locked() if complete else None
        state = _game_state_locked()
        socketio.emit(
            "round_finished",
            {
                "number": finished["number"],
                "word": finished["word"],
                "drawer_name": _participants[finished["drawer_sid"]],
                "solved": solved_names,
                "seconds": round(elapsed, 1),
            },
        )
        if complete:
            socketio.emit(
                "game_finished",
                {"statistics": statistics, "state": state},
            )
        else:
            _broadcast_round(next_round)
    return True


def _broadcast_round(round_data):
    with _lock:
        if _round is None or _round["id"] != round_data["id"]:
            return
        public_round = {
            key: value for key, value in round_data.items() if key != "word"
        }
        state = _game_state_locked()
        socketio.emit("drawing_cleared")
        socketio.emit("round_started", public_round)
        socketio.emit("game_state", state)
        socketio.emit(
            "drawer_word",
            {"word": round_data["word"]},
            to=round_data["drawer_sid"],
        )
        socketio.start_background_task(
            _round_timer, round_data["id"], round_data["duration"]
        )


def _round_timer(round_id, duration):
    socketio.sleep(duration)
    _finish_round(round_id)


def _emit_error(message):
    socketio.emit("game_error", {"message": message}, to=request.sid)
    return {"ok": False, "message": message}


@socketio.on("host_join")
def on_host_join():
    from routes import _is_admin_ip_allowed

    if not _is_admin_ip_allowed():
        return _emit_error("관리자 페이지에서만 게임을 진행할 수 있습니다.")
    with _lock:
        _host_sids.add(request.sid)
        data = _game_state_locked()
    socketio.emit("game_state", data, to=request.sid)
    return {"ok": True}


def is_valid_nickname(nickname):
    return bool(
        NICKNAME_PATTERN.fullmatch(nickname)
        and any(
            character.isalnum() or "\uac00" <= character <= "\ud7a3"
            for character in nickname
        )
    )


def join_game(sid, nickname):
    """로비 계층에서 호출한다. 성공하면 None, 실패하면 오류 메시지를 반환한다."""
    with _lock:
        if _phase == "playing":
            return "게임이 이미 시작되어 입장할 수 없습니다."
        if any(
            other != sid and player["nickname"].casefold() == nickname.casefold()
            for other, player in _players.items()
        ):
            return "이미 사용 중인 닉네임입니다."
        _players[sid] = {"nickname": nickname}
        _participants[sid] = nickname
        _scores[sid] = 0
        _answer_times[sid] = []
        socketio.emit("game_state", _game_state_locked())
    return None


def has_player(sid):
    with _lock:
        return sid in _players


def rekey_player(old_sid, new_sid):
    """재접속한 사용자의 게임 상태를 새 소켓 ID로 옮긴다."""
    global _order
    if old_sid == new_sid:
        return
    with _lock:
        for table in (_players, _participants, _scores, _answer_times):
            if old_sid in table:
                table[new_sid] = table.pop(old_sid)
        _order = [new_sid if sid == old_sid else sid for sid in _order]
        if _round is not None:
            if _round["drawer_sid"] == old_sid:
                _round["drawer_sid"] = new_sid
            if old_sid in _round["solved"]:
                _round["solved"].discard(old_sid)
                _round["solved"].add(new_sid)
        socketio.emit("game_state", _game_state_locked())


def resend_game_view(sid):
    """재접속한 사용자에게 진행 중인 라운드와 그림을 다시 보낸다."""
    with _lock:
        if _round is None:
            return
        public_round = _public_round_locked()
        strokes = list(_strokes)
        word = _round["word"] if _round["drawer_sid"] == sid else None
    socketio.emit("round_started", {**public_round, "total": len(_order)}, to=sid)
    socketio.emit("drawing_state", {"strokes": strokes}, to=sid)
    if word is not None:
        socketio.emit("drawer_word", {"word": word}, to=sid)


@socketio.on("game_start")
def on_game_start():
    if request.sid not in _host_sids:
        return _emit_error("게임 시작 권한이 없습니다.")

    settings = dict(get_db().execute("SELECT key, value FROM settings").fetchall())
    try:
        theme_id = int(settings["theme_id"])
        duration = int(settings["round_duration"])
    except (KeyError, ValueError) as error:
        current_app.logger.error("게임 설정이 올바르지 않습니다: %s", error)
        return _emit_error("게임 설정을 읽지 못했습니다.")

    theme = get_db().execute(
        "SELECT name FROM themes WHERE id = ?", (theme_id,)
    ).fetchone()
    words = get_db().execute(
        "SELECT word FROM words WHERE theme_id = ? ORDER BY word",
        (theme_id,),
    ).fetchall()
    if theme is None or not words:
        return _emit_error("선택한 테마에 사용할 단어가 없습니다.")

    global _phase, _theme_name, _round_duration, _word_list
    global _used_words, _order, _round_index, _round
    global _round_results, _participants, _scores, _answer_times
    with _lock:
        if _phase == "playing":
            return _emit_error("진행 중인 게임이 있습니다.")
        if len(_players) < 2:
            return _emit_error("게임을 시작하려면 참가자가 2명 이상 필요합니다.")
        _phase = "lobby"
        _theme_name = theme["name"]
        _round_duration = duration
        _word_list = [row["word"] for row in words]
        _used_words = set()
        _order = list(_players)
        random.shuffle(_order)
        _round_index = 0
        _round = None
        _round_results = []
        _participants = {
            sid: player["nickname"] for sid, player in _players.items()
        }
        _scores = {sid: 0 for sid in _players}
        _answer_times = {sid: [] for sid in _players}
        first_round = _make_round_locked()
        socketio.emit("game_started", {"theme": _theme_name})
        _broadcast_round(first_round)
    return {"ok": True}


@socketio.on("game_chat_message")
def on_game_chat_message(data=None):
    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        return _emit_error("채팅 내용을 입력해 주세요.")
    message = data["message"].strip()
    if not message or len(message) > MAX_CHAT_LENGTH:
        return _emit_error("채팅은 1~200자로 입력해 주세요.")

    with _lock:
        player = _players.get(request.sid)
        if player is None:
            return _emit_error("먼저 닉네임을 정하고 게임에 입장해 주세요.")
        channel = (
            "solved"
            if _round is not None and request.sid in _round["solved"]
            else "normal"
        )
        if (
            _round is not None
            and request.sid != _round["drawer_sid"]
            and request.sid not in _round["solved"]
        ):
            normalized = re.sub(r"\s+", "", message).casefold()
            answer = re.sub(r"\s+", "", _round["word"]).casefold()
            if normalized == answer:
                _round["solved"].add(request.sid)
                _scores[request.sid] = _scores.get(request.sid, 0) + 1
                elapsed = max(
                    0, time.monotonic() - _round["started_monotonic"]
                )
                _answer_times.setdefault(request.sid, []).append(elapsed)
                channel = "solved"
                is_correct = True
            else:
                is_correct = False
        else:
            is_correct = False
        payload = {
            "nickname": player["nickname"],
            "message": message,
            "channel": channel,
            "correct": is_correct,
        }
        finish_early = is_correct and _should_finish_round_locked()
        state = _game_state_locked()
        socketio.emit("game_chat", payload)
        if is_correct:
            socketio.emit("game_state", state)
    if finish_early:
        _finish_round()
    return {"ok": True, "correct": is_correct}


def _is_coordinate(value, limit):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= limit
    )


def _sanitize_strokes(data):
    if not isinstance(data, dict) or not isinstance(data.get("strokes"), list):
        return None
    strokes = data["strokes"]
    if len(strokes) > MAX_STROKES_PER_MESSAGE:
        return None
    clean = []
    for stroke in strokes:
        if not isinstance(stroke, dict):
            return None
        color = stroke.get("color")
        points = stroke.get("points")
        width = stroke.get("width")
        if (
            not _is_coordinate(width, MAX_DRAWING_WIDTH)
            or width < 1
            or not isinstance(color, str)
            or not DRAWING_COLOR_PATTERN.fullmatch(color)
            or not isinstance(points, list)
            or not 1 <= len(points) <= MAX_POINTS_PER_STROKE
        ):
            return None
        clean_points = []
        for point in points:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or not _is_coordinate(point[0], DRAWING_WIDTH)
                or not _is_coordinate(point[1], DRAWING_HEIGHT)
            ):
                return None
            clean_points.append([point[0], point[1]])
        clean.append(
            {
                "color": color,
                "width": width,
                "begin": stroke.get("begin") is True,
                "points": clean_points,
            }
        )
    return clean


@socketio.on("drawing_strokes")
def on_drawing_strokes(data=None):
    strokes = _sanitize_strokes(data)
    if not strokes:
        return {"ok": False, "message": "그림 데이터가 올바르지 않습니다."}
    with _lock:
        if (
            _phase != "playing"
            or _round is None
            or request.sid != _round["drawer_sid"]
        ):
            return {"ok": False, "message": "현재 그림을 그릴 차례가 아닙니다."}
        for stroke in strokes:
            if stroke["begin"] or not _strokes:
                _strokes.append(
                    {
                        "color": stroke["color"],
                        "width": stroke["width"],
                        "begin": True,
                        "points": list(stroke["points"]),
                    }
                )
            else:
                _strokes[-1]["points"].extend(stroke["points"])
        total_points = sum(len(stroke["points"]) for stroke in _strokes)
        while len(_strokes) > 1 and (
            len(_strokes) > MAX_STORED_STROKES
            or total_points > MAX_STORED_POINTS
        ):
            total_points -= len(_strokes.pop(0)["points"])
        if total_points > MAX_STORED_POINTS:
            del _strokes[-1]["points"][MAX_STORED_POINTS:]
        socketio.emit(
            "drawing_strokes",
            {"id": request.sid, "strokes": strokes},
            skip_sid=request.sid,
        )
    return {"ok": True}


@socketio.on("drawing_sync")
def on_drawing_sync():
    with _lock:
        return {"strokes": list(_strokes)}


@socketio.on("game_sync")
def on_game_sync():
    with _lock:
        state = _game_state_locked()
    socketio.emit("game_state", state, to=request.sid)
    resend_game_view(request.sid)


@socketio.on("drawing_undo")
def on_drawing_undo():
    with _lock:
        if (
            _round is None
            or request.sid != _round["drawer_sid"]
            or not _strokes
        ):
            return {"ok": False}
        _strokes.pop()
        remaining = list(_strokes)
        socketio.emit("drawing_state", {"strokes": remaining})
    return {"ok": True}

@socketio.on("classflow_ask_question")
def on_classflow_ask_question():
    print("Classflow question asked")
    socketio.emit("classflow_question_asked") 
    return {"ok": True}




DISCONNECT_GRACE_SECONDS = 30
def _remove_player(sid):
    with _lock:
        _players.pop(sid, None)
        drawer_disconnected = (
            _round is not None and _round["drawer_sid"] == sid
        )
        finish_early = _should_finish_round_locked()
    if drawer_disconnected or finish_early:
        _finish_round()
    _emit_room_update()


def _remove_player_after_grace(sid):
    socketio.sleep(DISCONNECT_GRACE_SECONDS)
    # 유예 시간 안에 재접속하면 rekey_player가 이미 항목을 옮겼으므로 건드리지 않는다.
    if has_player(sid):
        _remove_player(sid)

@socketio.on("disconnect")
def on_disconnect():
    import lobby

    lobby.on_disconnect(request.sid)
    with _lock:
        _host_sids.discard(request.sid)
        keep_for_reconnect = request.sid in _players and _phase == "playing"
    if keep_for_reconnect:
        socketio.start_background_task(_remove_player_after_grace, request.sid)
    else:
        _remove_player(request.sid)
