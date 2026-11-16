import math
import random
import threading
import time

from flask import request
from flask_socketio import join_room

import lobby
from extensions import socketio

HOST_ROOM = "landgrab_hosts"
MIN_RESOURCE_INTERVAL = 10
MAX_RESOURCE_INTERVAL = 600
MIN_COST_INCREASE_RATE = 10
MAX_COST_INCREASE_RATE = 100
MAP_RADIUS = 4
RESOURCE_NAMES = {"wood": "목재", "stone": "석재", "food": "식량"}
TERRAINS = {
    "water": {
        "name": "물",
        "color": "#60a5fa",
        "weight": 14,
        "production": {},
        "cost": None,
        "startable": False,
    },
    "grass": {
        "name": "초원",
        "color": "#86efac",
        "weight": 30,
        "production": {"food": 2},
        "cost": {"wood": 2, "food": 2},
        "startable": True,
    },
    "desert": {
        "name": "사막",
        "color": "#fcd34d",
        "weight": 18,
        "production": {"food": 1},
        "cost": {"wood": 1, "food": 1},
        "startable": True,
    },
    "forest": {
        "name": "숲",
        "color": "#4ade80",
        "weight": 24,
        "production": {"wood": 2, "food": 1},
        "cost": {"wood": 3, "food": 1},
        "startable": True,
    },
    "mountain": {
        "name": "산",
        "color": "#a8a29e",
        "weight": 14,
        "production": {"stone": 2},
        "cost": {"wood": 2, "food": 2},
        "startable": False,
    },
}
NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1))
STARTING_RESOURCES = {"wood": 5, "stone": 5, "food": 5}
STARTING_TERRAINS = tuple(
    terrain for terrain, settings in TERRAINS.items() if settings["startable"]
)
USER_ROOM_PREFIX = "landgrab_user:"

_lock = threading.RLock()
_game_id = 0
_phase = "waiting"
_resource_interval = 60
_cost_increase_rate = MIN_COST_INCREASE_RATE
_next_resource_at = None
_tiles = {}
_players = {}


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


def _make_map():
    tiles = {}
    for q in range(-MAP_RADIUS, MAP_RADIUS + 1):
        for r in range(-MAP_RADIUS, MAP_RADIUS + 1):
            if max(abs(q), abs(r), abs(q + r)) > MAP_RADIUS:
                continue
            terrain = random.choices(
                tuple(TERRAINS),
                weights=tuple(item["weight"] for item in TERRAINS.values()),
                k=1,
            )[0]
            tiles[(q, r)] = {"q": q, "r": r, "terrain": terrain, "owner": None}
    return tiles


def _tile_payload(tile, client_id=None):
    settings = TERRAINS[tile["terrain"]]
    owner = _players.get(tile["owner"])
    cost = dict(settings["cost"]) if settings["cost"] else None
    distance = None
    if cost is not None and client_id in _players:
        start_q, start_r = _players[client_id]["start"]
        distance = max(
            abs(tile["q"] - start_q),
            abs(tile["r"] - start_r),
            abs((tile["q"] - start_q) + (tile["r"] - start_r)),
        )
        increase_percent = distance * _cost_increase_rate
        cost = {
            resource: amount * (100 + increase_percent) // 100
            for resource, amount in cost.items()
        }
    return {
        "q": tile["q"],
        "r": tile["r"],
        "terrain": tile["terrain"],
        "terrain_name": settings["name"],
        "color": settings["color"],
        "owner": owner["name"] if owner else None,
        "production": dict(settings["production"]),
        "cost": cost,
        "distance": distance,
    }


def _public_tiles_locked():
    return [_tile_payload(tile) for tile in _tiles.values()]


def _resource_seconds_remaining_locked():
    if _phase != "running" or _next_resource_at is None:
        return None
    return max(0, math.ceil(_next_resource_at - time.monotonic()))


def _start_positions(tiles, count):
    candidates = [
        key for key, tile in tiles.items()
        if tile["terrain"] in STARTING_TERRAINS
    ]
    for _ in range(100):
        random.shuffle(candidates)
        starts = candidates[:count]
        if len(starts) != count:
            return None
        starts_set = set(starts)
        if all(
            any(
                (q + dq, r + dr) in tiles
                and (q + dq, r + dr) not in starts_set
                and TERRAINS[tiles[(q + dq, r + dr)]["terrain"]]["cost"] is not None
                for dq, dr in NEIGHBORS
            )
            for q, r in starts
        ):
            return starts
    return None


def _has_neighbor_locked(client_id, q, r):
    return any(
        (q + dq, r + dr) in _tiles
        and _tiles[(q + dq, r + dr)]["owner"] == client_id
        for dq, dr in NEIGHBORS
    )


def _assign_player_locked(client_id, name):
    if client_id in _players:
        _players[client_id]["name"] = name
        return True
    available = []
    for key, tile in _tiles.items():
        if tile["terrain"] not in STARTING_TERRAINS or tile["owner"] is not None:
            continue
        q, r = key
        if any(
            (q + dq, r + dr) in _tiles
            and _tiles[(q + dq, r + dr)]["owner"] is None
            and TERRAINS[_tiles[(q + dq, r + dr)]["terrain"]]["cost"] is not None
            for dq, dr in NEIGHBORS
        ):
            available.append(key)
    if not available:
        return False
    start = random.choice(available)
    _tiles[start]["owner"] = client_id
    _players[client_id] = {
        "name": name,
        "resources": dict(STARTING_RESOURCES),
        "start": start,
    }
    return True


def _user_state_locked(client_id):
    player = _players.get(client_id)
    if player is None:
        return {
            "phase": _phase,
            "tiles": _public_tiles_locked(),
            "resources": {},
            "production": {},
            "buyable": [],
            "resource_interval": _resource_interval,
            "resource_seconds_remaining": _resource_seconds_remaining_locked(),
            "resource_names": RESOURCE_NAMES,
        }

    production = dict.fromkeys(RESOURCE_NAMES, 0)
    buyable = []
    if _phase == "running":
        for key, tile in _tiles.items():
            if (
                tile["owner"] is None
                and TERRAINS[tile["terrain"]]["cost"] is not None
                and _has_neighbor_locked(client_id, *key)
            ):
                buyable.append(_tile_payload(tile, client_id))
    owned = [
        {"q": tile["q"], "r": tile["r"], "terrain": tile["terrain"]}
        for tile in _tiles.values()
        if tile["owner"] == client_id
    ]
    for tile in _tiles.values():
        if tile["owner"] != client_id:
            continue
        for resource, amount in TERRAINS[tile["terrain"]]["production"].items():
            production[resource] += amount
    return {
        "phase": _phase,
        "tiles": _public_tiles_locked(),
        "resources": dict(player["resources"]),
        "production": production,
        "owned": owned,
        "buyable": buyable,
        "resource_interval": _resource_interval,
        "resource_seconds_remaining": _resource_seconds_remaining_locked(),
        "resource_names": RESOURCE_NAMES,
    }


def _host_state_locked():
    return {
        "phase": _phase,
        "resource_interval": _resource_interval,
        "cost_increase_rate": _cost_increase_rate,
        "tiles": _public_tiles_locked(),
        "players": [
            {
                "client_id": client_id,
                "name": player["name"],
                "resources": dict(player["resources"]),
                "territory_count": sum(
                    tile["owner"] == client_id for tile in _tiles.values()
                ),
            }
            for client_id, player in _players.items()
        ],
    }


def _broadcast_locked_state():
    with _lock:
        host_state = _host_state_locked()
        user_states = [
            (client_id, _user_state_locked(client_id))
            for client_id in _players
        ]
    socketio.emit("landgrab_host_state", host_state, to=HOST_ROOM)
    for client_id, state in user_states:
        socketio.emit(
            "landgrab_user_state",
            state,
            to=USER_ROOM_PREFIX + client_id,
        )


def _resource_loop(game_id, deadline):
    global _next_resource_at

    while True:
        socketio.sleep(min(1, max(0, deadline - time.monotonic())))
        now = time.monotonic()
        with _lock:
            if _game_id != game_id or _phase != "running":
                return
            cycles = int((now - deadline) // _resource_interval) + 1
            deadline += cycles * _resource_interval
            _next_resource_at = deadline
            for tile in _tiles.values():
                client_id = tile["owner"]
                if client_id is None:
                    continue
                player = _players.get(client_id)
                if player is None:
                    continue
                for resource, amount in TERRAINS[tile["terrain"]]["production"].items():
                    player["resources"][resource] += amount * cycles
        if cycles == 0:
            continue
        _broadcast_locked_state()


@socketio.on("landgrab_sync")
def on_landgrab_sync():
    if _is_host():
        join_room(HOST_ROOM)
        with _lock:
            return {"ok": True, **_host_state_locked()}

    client_id, user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    join_room(USER_ROOM_PREFIX + client_id)
    with _lock:
        if _phase == "running" and not _assign_player_locked(client_id, user["name"]):
            return {
                "ok": False,
                "message": "시작 가능한 땅이 부족합니다. 호스트에게 새 지도를 요청해 주세요.",
            }
        state = _user_state_locked(client_id)
    _broadcast_locked_state()
    return {"ok": True, **state}


@socketio.on("landgrab_start")
def on_landgrab_start(data=None):
    global _game_id, _phase, _resource_interval, _cost_increase_rate
    global _next_resource_at, _tiles, _players

    if not _is_host():
        return {"ok": False, "message": "호스트만 게임을 시작할 수 있습니다."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "게임 설정이 올바르지 않습니다."}
    interval = data.get("resource_interval")
    if (
        isinstance(interval, bool)
        or not isinstance(interval, int)
        or not MIN_RESOURCE_INTERVAL <= interval <= MAX_RESOURCE_INTERVAL
    ):
        return {
            "ok": False,
            "message": "자원 획득 주기는 10~600초 사이여야 합니다.",
        }
    cost_increase_rate = data.get("cost_increase_rate")
    if (
        isinstance(cost_increase_rate, bool)
        or not isinstance(cost_increase_rate, int)
        or not MIN_COST_INCREASE_RATE
        <= cost_increase_rate
        <= MAX_COST_INCREASE_RATE
    ):
        return {
            "ok": False,
            "message": "거리당 구매 비용 증가율은 10~100% 사이여야 합니다.",
        }

    online = lobby.online_users()
    tiles = _make_map()
    starts = _start_positions(tiles, len(online))
    attempts = 0
    while starts is None and attempts < 100:
        tiles = _make_map()
        starts = _start_positions(tiles, len(online))
        attempts += 1
    if starts is None:
        return {"ok": False, "message": "시작 땅과 인접한 구매 가능 땅을 배정하지 못했습니다."}

    with _lock:
        _game_id += 1
        game_id = _game_id
        _resource_interval = interval
        _cost_increase_rate = cost_increase_rate
        _next_resource_at = time.monotonic() + interval
        _tiles = tiles
        _players = {}
        _phase = "running"
        for ((q, r), (client_id, name)) in zip(starts, online.items()):
            _tiles[(q, r)]["owner"] = client_id
            _players[client_id] = {
                "name": name,
                "resources": dict(STARTING_RESOURCES),
                "start": (q, r),
            }
        state = _host_state_locked()

    socketio.start_background_task(
        _resource_loop, game_id, _next_resource_at
    )
    _broadcast_locked_state()
    return {"ok": True, **state}


@socketio.on("landgrab_stop")
def on_landgrab_stop():
    global _game_id, _phase, _next_resource_at

    if not _is_host():
        return {"ok": False, "message": "호스트만 게임을 종료할 수 있습니다."}
    with _lock:
        if _phase != "running":
            return {"ok": False, "message": "진행 중인 땅따먹기 게임이 없습니다."}
        _phase = "ended"
        _next_resource_at = None
        _game_id += 1
        state = _host_state_locked()
    _broadcast_locked_state()
    return {"ok": True, **state}


@socketio.on("landgrab_buy")
def on_landgrab_buy(data=None):
    client_id, _user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "구매 정보가 올바르지 않습니다."}
    q, r = data.get("q"), data.get("r")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (q, r)):
        return {"ok": False, "message": "좌표가 올바르지 않습니다."}

    with _lock:
        if _phase != "running":
            return {"ok": False, "message": "현재 진행 중인 게임이 없습니다."}
        player = _players.get(client_id)
        tile = _tiles.get((q, r))
        if player is None or tile is None:
            return {"ok": False, "message": "해당 땅을 구매할 수 없습니다."}
        if tile["owner"] is not None or TERRAINS[tile["terrain"]]["cost"] is None:
            return {"ok": False, "message": "해당 땅을 구매할 수 없습니다."}
        if not _has_neighbor_locked(client_id, q, r):
            return {"ok": False, "message": "인접한 땅만 구매할 수 있습니다."}
        cost = _tile_payload(tile, client_id)["cost"]
        if any(player["resources"][resource] < amount for resource, amount in cost.items()):
            return {"ok": False, "message": "자원이 부족합니다."}
        for resource, amount in cost.items():
            player["resources"][resource] -= amount
        tile["owner"] = client_id
        state = _user_state_locked(client_id)

    _broadcast_locked_state()
    return {"ok": True, **state}
