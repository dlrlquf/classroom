from collections import Counter
import random
import sqlite3

from database import get_db
from extensions import socketio
import events
import lobby

MAX_CLASS_NAME_LENGTH = 40
MAX_STUDENTS = 200
MIN_COLUMNS = 1
MAX_COLUMNS = 12
MIN_ROWS = 4
MAX_ROWS = 200


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


def _error(message):
    return {"ok": False, "message": message}


def _class_data(db, class_id):
    class_row = db.execute(
        "SELECT id, name, columns_count, rows_count "
        "FROM seating_classes WHERE id = ?",
        (class_id,),
    ).fetchone()
    if class_row is None:
        return None

    seats = db.execute(
        "SELECT id, seat_order, student_name FROM seating_seats "
        "WHERE class_id = ? ORDER BY seat_order",
        (class_id,),
    ).fetchall()
    locked_orders = {
        row["seat_order"]
        for row in db.execute(
            "SELECT seat_order FROM seating_locked_seats WHERE class_id = ?",
            (class_id,),
        )
    }
    seats_by_order = {seat["seat_order"]: seat for seat in seats}
    slot_count = class_row["columns_count"] * class_row["rows_count"]
    slots = []
    for order in range(slot_count):
        seat = seats_by_order.get(order)
        slots.append({
            "id": seat["id"] if seat else None,
            "order": order,
            "name": seat["student_name"] if seat else None,
            "locked": order in locked_orders,
        })
    return {
        "id": class_row["id"],
        "name": class_row["name"],
        "columns": class_row["columns_count"],
        "rows": class_row["rows_count"],
        "seats": slots,
        "online_names": list(lobby.online_users().values()),
    }


def _class_list(db):
    return [
        {"id": row["id"], "name": row["name"]}
        for row in db.execute(
            "SELECT id, name FROM seating_classes ORDER BY name COLLATE NOCASE"
        ).fetchall()
    ]


@socketio.on("seating_sync")
def on_seating_sync(data=None):
    if not _is_host():
        return _error("호스트만 자리 배치를 관리할 수 있습니다.")
    class_id = data.get("class_id") if isinstance(data, dict) else None
    db = get_db()
    classes = _class_list(db)
    if class_id is None:
        class_id = classes[0]["id"] if classes else None
    elif isinstance(class_id, bool) or not isinstance(class_id, int):
        return _error("반 정보가 올바르지 않습니다.")
    class_data = _class_data(db, class_id) if class_id is not None else None
    if class_id is not None and class_data is None:
        return _error("선택한 반을 찾을 수 없습니다.")
    return {"ok": True, "classes": classes, "class": class_data}


@socketio.on("seating_class_create")
def on_seating_class_create(data=None):
    if not _is_host():
        return _error("호스트만 반을 추가할 수 있습니다.")
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str):
        return _error("반 이름을 입력해 주세요.")
    name = name.strip()
    if not name or len(name) > MAX_CLASS_NAME_LENGTH:
        return _error(f"반 이름은 1~{MAX_CLASS_NAME_LENGTH}자로 입력해 주세요.")

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO seating_classes (name) VALUES (?)", (name,)
        )
        db.commit()
    except sqlite3.IntegrityError as error:
        db.rollback()
        if "UNIQUE constraint failed" in str(error):
            return _error("같은 이름의 반이 이미 있습니다.")
        raise
    return {
        "ok": True,
        "classes": _class_list(db),
        "class": _class_data(db, cursor.lastrowid),
    }


@socketio.on("seating_roster_save")
def on_seating_roster_save(data=None):
    if not _is_host():
        return _error("호스트만 명단을 저장할 수 있습니다.")
    if not isinstance(data, dict):
        return _error("명단 정보가 올바르지 않습니다.")
    class_id = data.get("class_id")
    roster = data.get("roster")
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        return _error("반 정보가 올바르지 않습니다.")
    if not isinstance(roster, str):
        return _error("명단을 입력해 주세요.")

    names = [name.strip() for name in roster.splitlines() if name.strip()]
    if len(names) > MAX_STUDENTS:
        return _error(f"명단은 최대 {MAX_STUDENTS}명까지 입력할 수 있습니다.")
    if any(not events.is_valid_nickname(name) for name in names):
        return _error("이름은 1~16자이며 한글, 영문, 숫자를 사용할 수 있습니다.")

    db = get_db()
    class_row = db.execute(
        "SELECT columns_count, rows_count FROM seating_classes WHERE id = ?",
        (class_id,),
    ).fetchone()
    if class_row is None:
        return _error("선택한 반을 찾을 수 없습니다.")
    try:
        db.execute("BEGIN")
        remaining = Counter(name.casefold() for name in names)
        display_names = {}
        for name in names:
            display_names.setdefault(name.casefold(), name)

        existing = db.execute(
            "SELECT id, seat_order, student_name FROM seating_seats "
            "WHERE class_id = ? ORDER BY seat_order",
            (class_id,),
        ).fetchall()
        append_start = max(
            (seat["seat_order"] for seat in existing),
            default=-1,
        ) + 1
        removed_ids = []
        for seat in existing:
            key = seat["student_name"].casefold()
            if remaining[key]:
                remaining[key] -= 1
                updated_name = display_names[key]
                if updated_name != seat["student_name"]:
                    db.execute(
                        "UPDATE seating_seats SET student_name = ? WHERE id = ?",
                        (updated_name, seat["id"]),
                    )
            else:
                removed_ids.append(seat["id"])

        if removed_ids:
            db.executemany(
                "DELETE FROM seating_seats WHERE id = ?",
                ((seat_id,) for seat_id in removed_ids),
            )

        added_names = []
        for name in names:
            key = name.casefold()
            if remaining[key]:
                added_names.append(name)
                remaining[key] -= 1

        locked_orders = {
            row["seat_order"]
            for row in db.execute(
                "SELECT seat_order FROM seating_locked_seats WHERE class_id = ?",
                (class_id,),
            )
        }
        slot_count = class_row["columns_count"] * class_row["rows_count"]
        empty_orders = [
            order
            for order in range(append_start, slot_count)
            if order not in locked_orders
        ]
        if len(empty_orders) < len(added_names):
            extra_rows = (
                len(added_names) - len(empty_orders) + class_row["columns_count"] - 1
            ) // class_row["columns_count"]
            rows_count = class_row["rows_count"] + extra_rows
            if rows_count > MAX_ROWS:
                db.rollback()
                return _error(f"행은 최대 {MAX_ROWS}개까지 사용할 수 있습니다.")
            db.execute(
                "UPDATE seating_classes SET rows_count = ? WHERE id = ?",
                (rows_count, class_id),
            )
            slot_count = class_row["columns_count"] * rows_count
            empty_orders.extend(
                order
                for order in range(
                    class_row["columns_count"] * class_row["rows_count"],
                    slot_count,
                )
                if order not in locked_orders
            )

        db.executemany(
            "INSERT INTO seating_seats (class_id, seat_order, student_name) "
            "VALUES (?, ?, ?)",
            (
                (class_id, seat_order, name)
                for name, seat_order in zip(
                    added_names, empty_orders
                )
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "class": _class_data(db, class_id)}


@socketio.on("seating_columns_update")
def on_seating_columns_update(data=None):
    if not _is_host():
        return _error("호스트만 열 수를 변경할 수 있습니다.")
    if not isinstance(data, dict):
        return _error("열 설정이 올바르지 않습니다.")

    class_id = data.get("class_id")
    columns = data.get("columns")
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        return _error("반 정보가 올바르지 않습니다.")
    if (
        isinstance(columns, bool)
        or not isinstance(columns, int)
        or not MIN_COLUMNS <= columns <= MAX_COLUMNS
    ):
        return _error(f"열 수는 {MIN_COLUMNS}~{MAX_COLUMNS} 사이여야 합니다.")

    db = get_db()
    class_row = db.execute(
        "SELECT rows_count FROM seating_classes WHERE id = ?", (class_id,)
    ).fetchone()
    if class_row is None:
        return _error("선택한 반을 찾을 수 없습니다.")
    student_count = db.execute(
        "SELECT COUNT(*) AS count FROM seating_seats WHERE class_id = ?",
        (class_id,),
    ).fetchone()["count"]
    max_locked_order = db.execute(
        "SELECT MAX(seat_order) AS seat_order FROM seating_locked_seats "
        "WHERE class_id = ?",
        (class_id,),
    ).fetchone()["seat_order"]
    required_rows = max(
        MIN_ROWS,
        (student_count + columns - 1) // columns,
        ((max_locked_order + 1 + columns - 1) // columns)
        if max_locked_order is not None
        else MIN_ROWS,
    )
    if required_rows > MAX_ROWS:
        return _error(f"현재 자리를 유지하려면 최대 행 수 {MAX_ROWS}개를 넘습니다.")
    db.execute(
        "UPDATE seating_classes SET columns_count = ?, rows_count = ? WHERE id = ?",
        (columns, max(class_row["rows_count"], required_rows), class_id),
    )
    db.commit()
    return {"ok": True, "class": _class_data(db, class_id)}


def _update_seat_positions(db, class_id, positions):
    rows = db.execute(
        "SELECT id, seat_order FROM seating_seats WHERE class_id = ?",
        (class_id,),
    ).fetchall()
    if not rows:
        return
    highest_target = max(positions.values(), default=-1)
    offset = max(
        max(row["seat_order"] for row in rows),
        highest_target,
    ) + len(rows) + 1
    db.execute(
        "UPDATE seating_seats SET seat_order = seat_order + ? WHERE class_id = ?",
        (offset, class_id),
    )
    for seat in rows:
        new_order = positions.get(seat["seat_order"], seat["seat_order"])
        db.execute(
            "UPDATE seating_seats SET seat_order = ? WHERE id = ?",
            (new_order, seat["id"]),
        )


@socketio.on("seating_swap")
def on_seating_swap(data=None):
    if not _is_host():
        return _error("호스트만 자리를 바꿀 수 있습니다.")
    if not isinstance(data, dict):
        return _error("자리 정보가 올바르지 않습니다.")

    class_id = data.get("class_id")
    source_order = data.get("source_order")
    target_order = data.get("target_order")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (class_id, source_order, target_order)
    ):
        return _error("자리 정보가 올바르지 않습니다.")
    if source_order == target_order:
        return _error("같은 자리입니다.")

    db = get_db()
    try:
        db.execute("BEGIN")
        class_row = db.execute(
            "SELECT columns_count, rows_count FROM seating_classes WHERE id = ?",
            (class_id,),
        ).fetchone()
        if class_row is None:
            db.rollback()
            return _error("선택한 반을 찾을 수 없습니다.")
        slot_count = class_row["columns_count"] * class_row["rows_count"]
        if not all(0 <= order < slot_count for order in (source_order, target_order)):
            db.rollback()
            return _error("선택한 자리를 찾을 수 없습니다.")
        locked = {
            row["seat_order"]
            for row in db.execute(
                "SELECT seat_order FROM seating_locked_seats WHERE class_id = ?",
                (class_id,),
            )
        }
        if source_order in locked or target_order in locked:
            db.rollback()
            return _error("잠긴 자리는 이동하거나 교체할 수 없습니다.")
        rows = db.execute(
            "SELECT id, seat_order FROM seating_seats WHERE class_id = ?",
            (class_id,),
        ).fetchall()
        positions = {row["seat_order"]: row["seat_order"] for row in rows}
        source_id = next(
            (row["id"] for row in rows if row["seat_order"] == source_order), None
        )
        target_id = next(
            (row["id"] for row in rows if row["seat_order"] == target_order), None
        )
        if source_id is not None:
            positions[source_order] = target_order
        if target_id is not None:
            positions[target_order] = source_order
        _update_seat_positions(db, class_id, positions)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "class": _class_data(db, class_id)}


@socketio.on("seating_seat_lock")
def on_seating_seat_lock(data=None):
    if not _is_host():
        return _error("호스트만 자리 잠금을 변경할 수 있습니다.")
    if not isinstance(data, dict):
        return _error("자리 정보가 올바르지 않습니다.")
    class_id = data.get("class_id")
    seat_order = data.get("seat_order")
    locked = data.get("locked")
    if (
        isinstance(class_id, bool)
        or not isinstance(class_id, int)
        or isinstance(seat_order, bool)
        or not isinstance(seat_order, int)
        or not isinstance(locked, bool)
    ):
        return _error("자리 정보가 올바르지 않습니다.")

    db = get_db()
    class_row = db.execute(
        "SELECT columns_count, rows_count FROM seating_classes WHERE id = ?",
        (class_id,),
    ).fetchone()
    if class_row is None:
        return _error("선택한 반을 찾을 수 없습니다.")
    if not 0 <= seat_order < class_row["columns_count"] * class_row["rows_count"]:
        return _error("선택한 자리를 찾을 수 없습니다.")
    if locked:
        db.execute(
            "INSERT OR IGNORE INTO seating_locked_seats (class_id, seat_order) "
            "VALUES (?, ?)",
            (class_id, seat_order),
        )
    else:
        db.execute(
            "DELETE FROM seating_locked_seats WHERE class_id = ? AND seat_order = ?",
            (class_id, seat_order),
        )
    db.commit()
    return {"ok": True, "class": _class_data(db, class_id)}


@socketio.on("seating_row_add")
def on_seating_row_add(data=None):
    if not _is_host():
        return _error("호스트만 행을 추가할 수 있습니다.")
    class_id = data.get("class_id") if isinstance(data, dict) else None
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        return _error("반 정보가 올바르지 않습니다.")
    db = get_db()
    cursor = db.execute(
        "UPDATE seating_classes SET rows_count = rows_count + 1 "
        "WHERE id = ? AND rows_count < ?",
        (class_id, MAX_ROWS),
    )
    if cursor.rowcount == 0:
        exists = db.execute(
            "SELECT 1 FROM seating_classes WHERE id = ?", (class_id,)
        ).fetchone()
        if exists is None:
            return _error("선택한 반을 찾을 수 없습니다.")
        return _error(f"행은 최대 {MAX_ROWS}개까지 추가할 수 있습니다.")
    db.commit()
    return {"ok": True, "class": _class_data(db, class_id)}


@socketio.on("seating_shuffle")
def on_seating_shuffle(data=None):
    if not _is_host():
        return _error("호스트만 자리를 섞을 수 있습니다.")
    class_id = data.get("class_id") if isinstance(data, dict) else None
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        return _error("반 정보가 올바르지 않습니다.")
    db = get_db()
    class_row = db.execute(
        "SELECT columns_count, rows_count FROM seating_classes WHERE id = ?",
        (class_id,),
    ).fetchone()
    if class_row is None:
        return _error("선택한 반을 찾을 수 없습니다.")
    locked = {
        row["seat_order"]
        for row in db.execute(
            "SELECT seat_order FROM seating_locked_seats WHERE class_id = ?",
            (class_id,),
        )
    }
    seats = db.execute(
        "SELECT id, seat_order FROM seating_seats WHERE class_id = ?",
        (class_id,),
    ).fetchall()
    occupied_orders = [
        seat["seat_order"]
        for seat in seats
        if seat["seat_order"] not in locked
    ]
    shuffled_orders = occupied_orders.copy()
    random.shuffle(shuffled_orders)
    positions = {
        source_order: target_order
        for source_order, target_order in zip(occupied_orders, shuffled_orders)
    }
    try:
        db.execute("BEGIN")
        _update_seat_positions(db, class_id, positions)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "class": _class_data(db, class_id)}
