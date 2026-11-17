import json
import logging
import math
import random
import threading
import time
from collections import deque
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, jsonify, request
from flask_socketio import join_room

import lobby
from extensions import socketio

from .buildings import BUILDINGS, Building, City, Farm, LoggingSite, Mine, Port
from .resources import (
    RESOURCE_ICONS, RESOURCE_NAMES, RESOURCES, STARTING_RESOURCES,
    Food, Iron, Luxury, Resource, Stone, Wood,
)
from .terrains import (
    STARTING_TERRAINS, TERRAINS, Coast, Cliff, Desert, Forest, Grass, Hill, Jungle,
    Lake, Mountain, Plains, River, Rocks, Shrub, Snow, Terrain, Water, Wetland,
)

bp = Blueprint(
    "landgrab", __name__, template_folder="templates",
    static_folder="static", url_prefix="/landgrab",
)

HOST_ROOM = "landgrab_hosts"
MIN_RESOURCE_INTERVAL = 10
MAX_RESOURCE_INTERVAL = 600
MIN_COST_INCREASE_RATE = 10
MAX_COST_INCREASE_RATE = 100
DEFAULT_MAP_WIDTH = 9
DEFAULT_MAP_HEIGHT = 9
MIN_MAP_DIMENSION = 3
MAX_MAP_DIMENSION = 300
MAX_AI_PLAYERS = 10
AI_ACTION_INTERVAL = 10
PLAYER_COLORS = (
    "#e11d48", "#2563eb", "#9333ea", "#ea580c",
    "#0d9488", "#db2777", "#4f46e5", "#ca8a04",
    "#0891b2", "#a21caf", "#65a30d", "#dc2626",
    "#7c3aed", "#0284c7", "#c2410c", "#059669",
)

NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1))
USER_ROOM_PREFIX = "landgrab_user:"
NOISE_TERRAINS = tuple(TERRAINS)
REAL_MAP_FILES = {
    "world": "world.txt",
    "korea": "korea.txt",
}
MAP_TERRAINS = {terrain.code: terrain_id for terrain_id, terrain in TERRAINS.items()}
DATA_DIRECTORY = Path(__file__).parent / "data"
logger = logging.getLogger(__name__)


_lock = threading.RLock()
_game_id = 0
_phase = "waiting"
_resource_interval = 60
_cost_increase_rate = MIN_COST_INCREASE_RATE
_map_width = DEFAULT_MAP_WIDTH
_map_height = DEFAULT_MAP_HEIGHT
_map_generation = "random"
_map_size = None
_map_country = None
_map_wrap = False
_next_resource_at = None
_tiles = {}
_players = {}
_port_links = set()


def _is_host():
    from routes import _is_admin_ip_allowed

    return _is_admin_ip_allowed()


@lru_cache(maxsize=1)
def _countries():
    return json.loads((DATA_DIRECTORY / "countries.json").read_text(encoding="utf-8"))


@bp.get("/countries")
def country_list():
    return jsonify(_countries())


def _preset_dimensions(width, source_width, source_height):
    width = max(MIN_MAP_DIMENSION, min(
        width, MAX_MAP_DIMENSION * source_width // source_height,
    ))
    height = max(MIN_MAP_DIMENSION, min(
        MAX_MAP_DIMENSION, round(width * source_height / source_width),
    ))
    return width, height


def _noise_value(x, y, values):
    x0, y0 = math.floor(x), math.floor(y)
    dx, dy = x - x0, y - y0
    dx = dx * dx * (3 - 2 * dx)
    dy = dy * dy * (3 - 2 * dy)
    corners = []
    for point in ((x0, y0), (x0 + 1, y0), (x0, y0 + 1), (x0 + 1, y0 + 1)):
        if point not in values:
            values[point] = random.random()
        corners.append(values[point])
    top = corners[0] + (corners[1] - corners[0]) * dx
    bottom = corners[2] + (corners[3] - corners[2]) * dx
    return top + (bottom - top) * dy


def _make_map(width, height, generation="random", country_id=None):
    source = None
    if generation in REAL_MAP_FILES or generation == "country":
        path = (
            DATA_DIRECTORY / "country_maps" / (country_id + ".txt")
            if generation == "country"
            else DATA_DIRECTORY / REAL_MAP_FILES[generation]
        )
        source = path.read_text(encoding="ascii").splitlines()
        if (
            not source
            or not source[0]
            or any(len(row) != len(source[0]) or set(row) - MAP_TERRAINS.keys() for row in source)
        ):
            raise ValueError(f"Invalid landgrab map data: {path}")
    tiles = {}
    for row in range(height):
        r = row - height // 2
        for column in range(width):
            q = column - width // 2 - r // 2
            terrain = None
            if generation == "random":
                terrain = random.choices(
                    tuple(TERRAINS),
                    weights=tuple(item.weight for item in TERRAINS.values()),
                    k=1,
                )[0]
            elif source is not None:
                source_row = (2 * row + 1) * len(source) // (2 * height)
                source_column = (2 * column + 1) * len(source[0]) // (2 * width)
                terrain = MAP_TERRAINS[source[source_row][source_column]]
            tiles[(q, r)] = {
                "q": q, "r": r, "terrain": terrain, "owner": None, "building": None
            }
    if generation == "noise":
        values = {}
        ordered = sorted(
            tiles,
            key=lambda point: _noise_value(
                (point[0] + point[1] / 2) / 4,
                point[1] * math.sqrt(3) / 8,
                values,
            ),
        )
        total_weight = sum(TERRAINS[terrain].weight for terrain in NOISE_TERRAINS)
        thresholds = []
        accumulated = 0
        for terrain in NOISE_TERRAINS:
            accumulated += TERRAINS[terrain].weight
            thresholds.append((accumulated, terrain))
        for index, key in enumerate(ordered):
            tiles[key]["terrain"] = next(
                terrain for threshold, terrain in thresholds
                if index * total_weight < threshold * len(ordered)
            )
    return tiles


def _neighbor_coordinates(q, r, width, wrap):
    neighbors = []
    for dq, dr in NEIGHBORS:
        neighbor_q, neighbor_r = q + dq, r + dr
        if wrap:
            column = (neighbor_q + neighbor_r // 2 + width // 2) % width - width // 2
            neighbor_q = column - neighbor_r // 2
        neighbors.append((neighbor_q, neighbor_r))
    return neighbors


def _hex_distance(first, second):
    delta_q = first[0] - second[0]
    delta_r = first[1] - second[1]
    return min(
        max(abs(delta_q + offset), abs(delta_r), abs(delta_q + offset + delta_r))
        for offset in ((-_map_width, 0, _map_width) if _map_wrap else (0,))
    )


def _tile_movable(tile):
    building = BUILDINGS[tile["building"]] if tile["building"] is not None else None
    return TERRAINS[tile["terrain"]].movable or bool(building and building.grants_movement)


def _active_tiles_locked():
    linked_ports = {}
    for owner, first, second in _port_links:
        first_tile = _tiles.get(first)
        second_tile = _tiles.get(second)
        if (
            first_tile is None or second_tile is None
            or first_tile["owner"] != owner or second_tile["owner"] != owner
            or first_tile["building"] != "port" or second_tile["building"] != "port"
        ):
            continue
        linked_ports.setdefault(first, []).append(second)
        linked_ports.setdefault(second, []).append(first)
    active = {
        position for position, tile in _tiles.items()
        if tile["owner"] is not None and tile["building"] == "city"
    }
    pending = list(active)
    while pending:
        position = pending.pop()
        current = _tiles[position]
        if not _tile_movable(current):
            continue
        owner = current["owner"]
        neighbors = _neighbor_coordinates(*position, _map_width, _map_wrap)
        neighbors.extend(linked_ports.get(position, ()))
        for neighbor in neighbors:
            tile = _tiles.get(neighbor)
            if tile is not None and tile["owner"] == owner and neighbor not in active:
                active.add(neighbor)
                pending.append(neighbor)
    return active


def _sea_distance_locked(client_id, source, target):
    pending = deque([(source, 0)])
    visited = {source}
    while pending:
        position, distance = pending.popleft()
        for neighbor in _neighbor_coordinates(*position, _map_width, _map_wrap):
            if neighbor in visited:
                continue
            tile = _tiles.get(neighbor)
            if (
                tile is None or tile["terrain"] not in ("water", "coast")
                or tile["owner"] not in (None, client_id)
            ):
                continue
            if neighbor == target:
                return distance + 1
            visited.add(neighbor)
            pending.append((neighbor, distance + 1))
    return None


def _discard_port_links(positions):
    _port_links.difference_update(
        link for link in tuple(_port_links) if link[1] in positions or link[2] in positions
    )


def _owned_buildings_locked(client_id):
    return [
        ((tile["q"], tile["r"]), BUILDINGS[tile["building"]])
        for tile in _tiles.values()
        if tile["owner"] == client_id and tile["building"] is not None
    ]


def _tile_production(tile):
    production = dict(TERRAINS[tile["terrain"]].production)
    if tile["building"] is not None:
        for resource, amount in BUILDINGS[tile["building"]].production_bonus.items():
            production[resource] = production.get(resource, 0) + amount
    return production


def _tile_payload(tile, client_id=None, owned_buildings=None, include_building=True, active_tiles=None):
    if active_tiles is None:
        active_tiles = _active_tiles_locked()
    settings = TERRAINS[tile["terrain"]]
    owner = _players.get(tile["owner"])
    active = tile["owner"] is not None and (tile["q"], tile["r"]) in active_tiles
    building = BUILDINGS[tile["building"]] if tile["building"] is not None else None
    cost = dict(settings.cost) if settings.cost else None
    distance = None
    if cost is not None and client_id in _players:
        if owned_buildings is None:
            owned_buildings = _owned_buildings_locked(client_id)
        distance = min(
            _hex_distance((tile["q"], tile["r"]), position)
            for position, owned_building in owned_buildings
            if owned_building.is_distance_origin
        )
        increase_percent = distance * _cost_increase_rate
        cost = {
            resource: amount * (100 + increase_percent) // 100
            for resource, amount in cost.items()
        }
        for _, owned_building in owned_buildings:
            cost = owned_building.adjust_purchase_cost(cost, distance)
        if tile["owner"] is not None and tile["owner"] != client_id:
            cost = {resource: amount * 2 for resource, amount in cost.items()}
            if building is not None and include_building:
                for resource, amount in building.construction_cost(owned_buildings).items():
                    cost[resource] = cost.get(resource, 0) + amount * 2
    return {
        "q": tile["q"],
        "r": tile["r"],
        "terrain": tile["terrain"],
        "terrain_name": settings.name,
        "color": settings.color,
        "movable": _tile_movable(tile),
        "owner": owner["name"] if owner else None,
        "owner_color": owner.get("color") if owner else None,
        "active": active if tile["owner"] is not None else None,
        "building": {"type": building.type_id, "name": building.name} if building else None,
        "production": _tile_production(tile) if tile["owner"] is None or active else {},
        "cost": cost,
        "distance": distance,
    }


def _public_tiles_locked(active_tiles=None):
    if active_tiles is None:
        active_tiles = _active_tiles_locked()
    return [_tile_payload(tile, active_tiles=active_tiles) for tile in _tiles.values()]


def _resource_seconds_remaining_locked():
    if _phase != "running" or _next_resource_at is None:
        return None
    return max(0, math.ceil(_next_resource_at - time.monotonic()))


def _start_positions(tiles, count, width, wrap):
    candidates = [
        key for key, tile in tiles.items()
        if tile["terrain"] in STARTING_TERRAINS
        and BUILDINGS["city"].allows_terrain(tile["terrain"])
    ]
    for _ in range(100):
        random.shuffle(candidates)
        starts = candidates[:count]
        if len(starts) != count:
            return None
        starts_set = set(starts)
        if all([
            any([
                neighbor in tiles
                and neighbor not in starts_set
                and TERRAINS[tiles[neighbor]["terrain"]].cost is not None
                for neighbor in _neighbor_coordinates(q, r, width, wrap)
            ])
            for q, r in starts
        ]):
            return starts
    return None


def _has_neighbor_locked(client_id, q, r, active_tiles=None):
    if active_tiles is None:
        active_tiles = _active_tiles_locked()
    for neighbor in _neighbor_coordinates(q, r, _map_width, _map_wrap):
        if (
            neighbor in active_tiles
            and _tiles[neighbor]["owner"] == client_id
            and _tile_movable(_tiles[neighbor])
        ):
            return True
    return False


def _purchase_error_locked(client_id, tile, cost, active_tiles=None):
    if tile["owner"] == client_id or cost is None:
        return "해당 땅을 구매할 수 없습니다."
    if not _has_neighbor_locked(client_id, tile["q"], tile["r"], active_tiles):
        return "도시와 연결되고 이동 가능한 내 땅에 인접한 땅만 구매할 수 있습니다."
    if any(_players[client_id]["resources"][resource] < amount for resource, amount in cost.items()):
        return "자원이 부족합니다."
    return None


def _build_cost_and_error_locked(client_id, tile, building, owned_buildings, active_tiles=None):
    player = _players.get(client_id)
    if _phase != "running":
        return None, "현재 진행 중인 게임이 없습니다."
    if player is None or tile is None or tile["owner"] != client_id:
        return None, "내 땅에만 건설할 수 있습니다."
    if player.get("eliminated", False):
        return None, "탈락한 참가자는 게임에 참여할 수 없습니다."
    if tile["building"] is not None:
        return None, "이미 건물이 있습니다."
    if active_tiles is None:
        active_tiles = _active_tiles_locked()
    if (tile["q"], tile["r"]) not in active_tiles:
        return None, "도시와 연결되지 않은 땅에는 건설할 수 없습니다."
    if not building.allows_terrain(tile["terrain"]):
        return None, "이 지형에는 해당 건물을 건설할 수 없습니다."
    error = building.placement_error((tile["q"], tile["r"]), owned_buildings)
    if error is not None:
        return None, error
    cost = building.construction_cost(owned_buildings)
    if any(player["resources"][resource] < amount for resource, amount in cost.items()):
        return None, "자원이 부족합니다."
    return cost, None


def _build_locked(client_id, tile, building, owned_buildings):
    cost, error = _build_cost_and_error_locked(client_id, tile, building, owned_buildings)
    if error is not None:
        return error
    for resource, amount in cost.items():
        _players[client_id]["resources"][resource] -= amount
    tile["building"] = building.type_id
    return None


def _buy_locked(client_id, tile, include_building, quote):
    if _phase != "running":
        return "현재 진행 중인 게임이 없습니다."
    player = _players.get(client_id)
    if player is None or tile is None:
        return "해당 땅을 구매할 수 없습니다."
    if player.get("eliminated", False):
        return "탈락한 참가자는 게임에 참여할 수 없습니다."
    if "expected_building" in quote and quote["expected_building"] != tile["building"]:
        return "타일의 건물이 변경되었습니다. 다시 확인해 주세요."
    active_tiles = _active_tiles_locked()
    cost = _tile_payload(
        tile, client_id, include_building=include_building, active_tiles=active_tiles
    )["cost"]
    error = _purchase_error_locked(client_id, tile, cost, active_tiles)
    if error is not None:
        return error
    if "expected_cost" in quote and quote["expected_cost"] != cost:
        return "구매 비용이 변경되었습니다. 다시 확인해 주세요."
    for resource, amount in cost.items():
        player["resources"][resource] -= amount
    previous_owner = tile["owner"]
    captured_city = previous_owner is not None and tile["building"] == "city"
    tile["owner"] = client_id
    if previous_owner is not None and not include_building:
        if tile["building"] == "port":
            _discard_port_links({(tile["q"], tile["r"])})
        tile["building"] = None
    if captured_city and not any(
        other["owner"] == previous_owner and other["building"] == "city"
        for other in _tiles.values()
    ):
        _players[previous_owner]["eliminated"] = True
        removed_ports = set()
        for other in _tiles.values():
            if other["owner"] == previous_owner:
                if other["building"] == "port":
                    removed_ports.add((other["q"], other["r"]))
                other["owner"] = None
                other["building"] = None
        _discard_port_links(removed_ports)
    return None


def _next_player_color_locked():
    used = {player.get("color") for player in _players.values()}
    available = [color for color in PLAYER_COLORS if color not in used]
    if available:
        return random.choice(available)
    while True:
        color = f"#{random.randrange(0x1000000):06x}"
        if color not in used:
            return color


def _assign_player_locked(client_id, name):
    if client_id in _players:
        _players[client_id]["name"] = name
        return True
    available = []
    for key, tile in _tiles.items():
        if (
            tile["terrain"] not in STARTING_TERRAINS
            or not BUILDINGS["city"].allows_terrain(tile["terrain"])
            or tile["owner"] is not None
        ):
            continue
        q, r = key
        if any([
            neighbor in _tiles
            and _tiles[neighbor]["owner"] is None
            and TERRAINS[_tiles[neighbor]["terrain"]].cost is not None
            for neighbor in _neighbor_coordinates(q, r, _map_width, _map_wrap)
        ]):
            available.append(key)
    if not available:
        return False
    start = random.choice(available)
    _tiles[start]["owner"] = client_id
    _tiles[start]["building"] = "city"
    _players[client_id] = {
        "name": name,
        "color": _next_player_color_locked(),
        "resources": dict(STARTING_RESOURCES),
        "start": start,
        "eliminated": False,
    }
    return True


def _user_state_locked(client_id, active_tiles=None, public_tiles=None):
    if active_tiles is None:
        active_tiles = _active_tiles_locked()
    if public_tiles is None:
        public_tiles = _public_tiles_locked(active_tiles)
    player = _players.get(client_id)
    if player is None:
        return {
            "phase": _phase,
            "eliminated": False,
            "tiles": public_tiles,
            "map_width": _map_width,
            "map_wrap": _map_wrap,
            "resources": {},
            "production": {},
            "buyable": [],
            "resource_interval": _resource_interval,
            "game_id": _game_id,
            "cost_increase_rate": _cost_increase_rate,
            "port_cost": dict(BUILDINGS["port"].cost),
            "port_links": [],
            "resource_seconds_remaining": _resource_seconds_remaining_locked(),
            "resource_names": RESOURCE_NAMES,
            "resource_icons": RESOURCE_ICONS,
        }

    production = dict.fromkeys(RESOURCE_NAMES, 0)
    buyable = []
    owned_buildings = _owned_buildings_locked(client_id)
    if _phase == "running" and not player.get("eliminated", False):
        adjacent = {
            neighbor
            for position in active_tiles
            if _tiles[position]["owner"] == client_id and _tile_movable(_tiles[position])
            for neighbor in _neighbor_coordinates(*position, _map_width, _map_wrap)
        }
        for key, tile in _tiles.items():
            if (
                tile["owner"] != client_id
                and TERRAINS[tile["terrain"]].cost is not None
                and key in adjacent
            ):
                buyable.append(_tile_payload(tile, client_id, owned_buildings, active_tiles=active_tiles))
    owned = [
        {"q": tile["q"], "r": tile["r"], "terrain": tile["terrain"]}
        for tile in _tiles.values()
        if tile["owner"] == client_id
    ]
    for tile in _tiles.values():
        if tile["owner"] != client_id or (tile["q"], tile["r"]) not in active_tiles:
            continue
        for resource, amount in _tile_production(tile).items():
            production[resource] += amount
    return {
        "phase": _phase,
        "eliminated": player.get("eliminated", False),
        "tiles": public_tiles,
        "map_width": _map_width,
        "map_wrap": _map_wrap,
        "resources": dict(player["resources"]),
        "production": production,
        "owned": owned,
        "buyable": buyable,
        "resource_interval": _resource_interval,
        "game_id": _game_id,
        "cost_increase_rate": _cost_increase_rate,
        "port_cost": dict(BUILDINGS["port"].cost),
        "port_links": [
            {
                "source": {"q": first[0], "r": first[1]},
                "target": {"q": second[0], "r": second[1]},
                "active": (
                    first in active_tiles and second in active_tiles
                    and _tiles[first]["owner"] == client_id and _tiles[second]["owner"] == client_id
                    and _tiles[first]["building"] == "port" and _tiles[second]["building"] == "port"
                ),
            }
            for owner, first, second in _port_links if owner == client_id
        ],
        "resource_seconds_remaining": _resource_seconds_remaining_locked(),
        "resource_names": RESOURCE_NAMES,
        "resource_icons": RESOURCE_ICONS,
    }


def _host_state_locked(active_tiles=None, public_tiles=None):
    if active_tiles is None:
        active_tiles = _active_tiles_locked()
    if public_tiles is None:
        public_tiles = _public_tiles_locked(active_tiles)
    return {
        "phase": _phase,
        "resource_interval": _resource_interval,
        "cost_increase_rate": _cost_increase_rate,
        "map_width": _map_width,
        "map_height": _map_height,
        "map_generation": _map_generation,
        "map_size": _map_size,
        "map_country": _map_country,
        "map_wrap": _map_wrap,
        "ai_count": sum(player.get("is_ai", False) for player in _players.values()),
        "resource_names": RESOURCE_NAMES,
        "resource_icons": RESOURCE_ICONS,
        "terrains": [
            {"name": terrain.name, "production": terrain.production, "movable": terrain.movable}
            for terrain in TERRAINS.values()
        ],
        "tiles": public_tiles,
        "players": [
            {
                "client_id": client_id,
                "name": player["name"],
                "color": player.get("color"),
                "is_ai": player.get("is_ai", False),
                "eliminated": player.get("eliminated", False),
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
        active_tiles = _active_tiles_locked()
        public_tiles = _public_tiles_locked(active_tiles)
        host_state = _host_state_locked(active_tiles, public_tiles)
        user_states = [
            (client_id, _user_state_locked(client_id, active_tiles, public_tiles))
            for client_id, player in _players.items()
            if not player.get("is_ai", False)
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
            if cycles <= 0:
                continue
            deadline += cycles * _resource_interval
            _next_resource_at = deadline
            active_tiles = _active_tiles_locked()
            for tile in _tiles.values():
                client_id = tile["owner"]
                if client_id is None or (tile["q"], tile["r"]) not in active_tiles:
                    continue
                player = _players.get(client_id)
                if player is None:
                    continue
                for resource, amount in _tile_production(tile).items():
                    player["resources"][resource] += amount * cycles
        _broadcast_locked_state()


def _ai_take_turn_locked(client_id):
    player = _players.get(client_id)
    if _phase != "running" or player is None or player.get("eliminated", False):
        return False

    active_tiles = _active_tiles_locked()
    owned_buildings = _owned_buildings_locked(client_id)
    owned_tiles = [
        tile for tile in _tiles.values()
        if tile["owner"] == client_id and (tile["q"], tile["r"]) in active_tiles
    ]
    actions = []
    neighbors = set()
    for tile in owned_tiles:
        position = (tile["q"], tile["r"])
        if tile["building"] is None:
            for building in BUILDINGS.values():
                _cost, error = _build_cost_and_error_locked(
                    client_id, tile, building, owned_buildings, active_tiles
                )
                if error is None:
                    score = 1 + sum(building.production_bonus.values())
                    actions.append((score, "build", position, building.type_id, True))
        if _tile_movable(tile):
            neighbors.update(_neighbor_coordinates(*position, _map_width, _map_wrap))

    for position in neighbors:
        tile = _tiles.get(position)
        if tile is None or tile["owner"] == client_id:
            continue
        include_building = True
        cost = _tile_payload(tile, client_id, owned_buildings, include_building, active_tiles)["cost"]
        if _purchase_error_locked(client_id, tile, cost, active_tiles) is not None:
            if tile["owner"] is None or tile["building"] is None:
                continue
            include_building = False
            cost = _tile_payload(tile, client_id, owned_buildings, include_building, active_tiles)["cost"]
            if _purchase_error_locked(client_id, tile, cost, active_tiles) is not None:
                continue
        production = _tile_production(tile) if include_building else TERRAINS[tile["terrain"]].production
        score = 1 + sum(production.values())
        if tile["owner"] is not None and tile["building"] == "city":
            score += 4
        actions.append((score, "buy", position, "", include_building))

    if not actions:
        return False
    best_score = max(action[0] for action in actions)
    _, kind, position, building_type, include_building = random.choice(
        [action for action in actions if action[0] == best_score]
    )
    tile = _tiles[position]
    if kind == "build":
        error = _build_locked(client_id, tile, BUILDINGS[building_type], owned_buildings)
    else:
        error = _buy_locked(client_id, tile, include_building, {})
    if error is not None:
        logger.error("AI 행동을 수행하지 못했습니다 (%s): %s", client_id, error)
        return False
    return True


def _ai_loop(game_id):
    while True:
        socketio.sleep(AI_ACTION_INTERVAL)
        with _lock:
            if _game_id != game_id or _phase != "running":
                return
            ai_players = [
                client_id for client_id, player in _players.items()
                if player.get("is_ai", False) and not player.get("eliminated", False)
            ]
            if not ai_players:
                return
            random.shuffle(ai_players)
            changed = False
            for client_id in ai_players:
                if _ai_take_turn_locked(client_id):
                    changed = True
        if changed:
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
    global _map_width, _map_height, _map_generation, _map_wrap
    global _map_size, _map_country, _next_resource_at, _tiles, _players

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
    map_generation = data.get("map_generation", "random")
    if map_generation not in ("random", "noise", "world", "korea", "country"):
        return {"ok": False, "message": "지도 생성 방식이 올바르지 않습니다."}
    map_size = data.get("map_size")
    map_country = None
    if map_size is not None:
        if (
            isinstance(map_size, bool)
            or not isinstance(map_size, int)
            or not 30 <= map_size <= MAX_MAP_DIMENSION
            or map_size % 30
        ):
            return {"ok": False, "message": "지도 크기 단계를 선택해 주세요."}
        if map_generation == "country":
            map_country = data.get("map_country")
            try:
                country = next(
                    (item for item in _countries() if item["id"] == map_country), None,
                )
            except (OSError, UnicodeError, ValueError):
                logger.exception("국가 지도 목록을 불러오지 못했습니다.")
                return {"ok": False, "message": "국가 지도 목록을 불러오지 못했습니다."}
            if country is None:
                return {"ok": False, "message": "지도에 사용할 국가를 선택해 주세요."}
            map_width, map_height = _preset_dimensions(
                map_size, country["width"], country["height"],
            )
        elif map_generation == "world":
            map_width, map_height = _preset_dimensions(map_size, 100, 70)
        elif map_generation == "korea":
            map_width, map_height = _preset_dimensions(map_size, 160, 220)
        else:
            map_width = map_height = map_size
    else:
        if map_generation == "country":
            return {"ok": False, "message": "지도 크기 단계를 선택해 주세요."}
        map_width = data.get("map_width", DEFAULT_MAP_WIDTH)
        map_height = data.get("map_height", DEFAULT_MAP_HEIGHT)
    if any(
        isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or not MIN_MAP_DIMENSION <= dimension <= MAX_MAP_DIMENSION
        for dimension in (map_width, map_height)
    ):
        return {
            "ok": False,
            "message": f"지도 크기는 가로와 세로 각각 {MIN_MAP_DIMENSION}~{MAX_MAP_DIMENSION}칸 사이여야 합니다.",
        }
    map_wrap = data.get("map_wrap", False)
    if not isinstance(map_wrap, bool):
        return {"ok": False, "message": "지도 좌우 연결 설정이 올바르지 않습니다."}
    ai_count = data.get("ai_count", 0)
    if isinstance(ai_count, bool) or not isinstance(ai_count, int) or not 0 <= ai_count <= MAX_AI_PLAYERS:
        return {"ok": False, "message": f"AI 플레이어는 0~{MAX_AI_PLAYERS}명이어야 합니다."}

    online = lobby.online_users()
    participants = [
        (client_id, name, False) for client_id, name in online.items()
    ] + [
        (f"ai:{index}", f"AI {index}", True) for index in range(1, ai_count + 1)
    ]
    try:
        tiles = _make_map(map_width, map_height, map_generation, map_country)
    except (OSError, UnicodeError, ValueError):
        logger.exception("실제 지도 데이터를 불러오지 못했습니다: %s", map_generation)
        return {"ok": False, "message": "지도 데이터를 불러오지 못했습니다."}
    starts = _start_positions(tiles, len(participants), map_width, map_wrap)
    attempts = 0
    while starts is None and attempts < 100 and map_generation not in (*REAL_MAP_FILES, "country"):
        tiles = _make_map(map_width, map_height, map_generation)
        starts = _start_positions(tiles, len(participants), map_width, map_wrap)
        attempts += 1
    if starts is None:
        return {"ok": False, "message": "시작 땅과 인접한 구매 가능 땅을 배정하지 못했습니다."}

    with _lock:
        _game_id += 1
        game_id = _game_id
        _resource_interval = interval
        _cost_increase_rate = cost_increase_rate
        _map_width = map_width
        _map_height = map_height
        _map_generation = map_generation
        _map_size = map_size
        _map_country = map_country
        _map_wrap = map_wrap
        _next_resource_at = time.monotonic() + interval
        _tiles = tiles
        _players = {}
        _port_links.clear()
        _phase = "running"
        for ((q, r), (client_id, name, is_ai)) in zip(starts, participants):
            _tiles[(q, r)]["owner"] = client_id
            _tiles[(q, r)]["building"] = "city"
            _players[client_id] = {
                "name": name,
                "color": _next_player_color_locked(),
                "resources": dict(STARTING_RESOURCES),
                "start": (q, r),
                "eliminated": False,
                "is_ai": is_ai,
            }
        state = _host_state_locked()

    socketio.start_background_task(
        _resource_loop, game_id, _next_resource_at
    )
    if ai_count:
        socketio.start_background_task(_ai_loop, game_id)
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


@socketio.on("landgrab_tile_info")
def on_landgrab_tile_info(data=None):
    client_id, _user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "타일 정보가 올바르지 않습니다."}
    q, r = data.get("q"), data.get("r")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (q, r)):
        return {"ok": False, "message": "좌표가 올바르지 않습니다."}

    with _lock:
        player = _players.get(client_id)
        tile = _tiles.get((q, r))
        if _phase != "running" or player is None or tile is None:
            return {"ok": False, "message": "해당 타일을 확인할 수 없습니다."}
        if player.get("eliminated", False):
            return {"ok": False, "message": "탈락한 참가자는 게임에 참여할 수 없습니다."}
        active_tiles = _active_tiles_locked()
        owned_buildings = _owned_buildings_locked(client_id)
        result = {
            "ok": True,
            "tile": _tile_payload(tile, client_id, owned_buildings, active_tiles=active_tiles),
            "owned": tile["owner"] == client_id,
        }
        if result["owned"]:
            options = []
            for building in BUILDINGS.values():
                if not building.allows_terrain(tile["terrain"]):
                    continue
                cost = building.construction_cost(owned_buildings)
                placement_error = (
                    None if tile["building"] is not None
                    else building.placement_error((q, r), owned_buildings)
                )
                error = (
                    "이미 건물이 있습니다."
                    if tile["building"] is not None
                    else "도시와 연결되지 않은 땅에는 건설할 수 없습니다."
                    if (q, r) not in active_tiles
                    else placement_error
                )
                if error is None and any(
                    player["resources"][resource] < amount for resource, amount in cost.items()
                ):
                    error = "자원이 부족합니다."
                options.append({
                    "type": building.type_id,
                    "name": building.name,
                    "description": building.description,
                    "cost": cost,
                    "error": error,
                    "placement_error": placement_error is not None,
                })
            result["buildings"] = options
        else:
            with_building = result["tile"]["cost"]
            land_only = _tile_payload(tile, client_id, owned_buildings, False, active_tiles)["cost"]
            result["purchase_options"] = {
                "with_building": {
                    "cost": with_building,
                    "error": _purchase_error_locked(client_id, tile, with_building, active_tiles),
                },
                "land_only": {
                    "cost": land_only,
                    "error": _purchase_error_locked(client_id, tile, land_only, active_tiles),
                },
            }
            result["purchase_error"] = result["purchase_options"]["with_building"]["error"]
        return result


@socketio.on("landgrab_build_linked_port")
def on_landgrab_build_linked_port(data=None):
    client_id, _user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "연결 항구 정보가 올바르지 않습니다."}
    source = data.get("source")
    target = data.get("target")
    if not isinstance(source, dict) or not isinstance(target, dict):
        return {"ok": False, "message": "항구 좌표가 올바르지 않습니다."}
    coordinates = (source.get("q"), source.get("r"), target.get("q"), target.get("r"))
    if any(isinstance(value, bool) or not isinstance(value, int) for value in coordinates):
        return {"ok": False, "message": "항구 좌표가 올바르지 않습니다."}
    if (
        isinstance(data.get("game_id"), bool) or not isinstance(data.get("game_id"), int)
        or isinstance(data.get("expected_distance"), bool)
        or not isinstance(data.get("expected_distance"), int)
        or data["expected_distance"] < 1 or not isinstance(data.get("expected_cost"), dict)
    ):
        return {"ok": False, "message": "항구 건설 비용 정보가 올바르지 않습니다."}
    source_position = coordinates[:2]
    target_position = coordinates[2:]
    with _lock:
        player = _players.get(client_id)
        if (
            _phase != "running" or player is None or player.get("eliminated", False)
            or data.get("game_id") != _game_id
        ):
            return {"ok": False, "message": "게임 상태가 변경되었습니다. 다시 선택해 주세요."}
        source_tile = _tiles.get(source_position)
        target_tile = _tiles.get(target_position)
        active_tiles = _active_tiles_locked()
        if (
            source_tile is None or source_tile["owner"] != client_id
            or source_tile["building"] != "port" or source_position not in active_tiles
        ):
            return {"ok": False, "message": "출발 항구가 사용 가능한 내 항구가 아닙니다."}
        if (
            target_tile is None or target_tile["terrain"] != "coast"
            or target_tile["owner"] is not None or target_tile["building"] is not None
        ):
            return {"ok": False, "message": "소유자와 건물이 없는 연안에만 항구를 지을 수 있습니다."}
        distance = _sea_distance_locked(client_id, source_position, target_position)
        if distance is None:
            return {"ok": False, "message": "연결 가능한 바닷길이 없습니다."}
        owned_buildings = _owned_buildings_locked(client_id)
        land_cost = _tile_payload(
            target_tile, client_id, owned_buildings, active_tiles=active_tiles,
        )["cost"]
        if land_cost is None:
            return {"ok": False, "message": "해당 연안을 구매할 수 없습니다."}
        port_cost = {
            resource: amount * (100 + distance * _cost_increase_rate) // 100
            for resource, amount in BUILDINGS["port"].construction_cost(owned_buildings).items()
        }
        cost = dict(land_cost)
        for resource, amount in port_cost.items():
            cost[resource] = cost.get(resource, 0) + amount
        if data.get("expected_distance") != distance or data.get("expected_cost") != cost:
            return {"ok": False, "message": "바닷길 또는 비용이 변경되었습니다. 다시 선택해 주세요."}
        if any(player["resources"][resource] < amount for resource, amount in cost.items()):
            return {"ok": False, "message": "자원이 부족합니다."}
        for resource, amount in cost.items():
            player["resources"][resource] -= amount
        target_tile["owner"] = client_id
        target_tile["building"] = "port"
        _port_links.add((client_id, source_position, target_position))
        state = _user_state_locked(client_id)
    _broadcast_locked_state()
    return {"ok": True, **state}


@socketio.on("landgrab_build")
def on_landgrab_build(data=None):
    client_id, _user = lobby.get_user_by_sid(request.sid)
    if client_id is None:
        return {"ok": False, "message": "먼저 접속해 주세요."}
    if not isinstance(data, dict):
        return {"ok": False, "message": "건설 정보가 올바르지 않습니다."}
    q, r, building_type = data.get("q"), data.get("r"), data.get("building")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (q, r)):
        return {"ok": False, "message": "좌표가 올바르지 않습니다."}
    if not isinstance(building_type, str) or building_type not in BUILDINGS:
        return {"ok": False, "message": "건물 종류가 올바르지 않습니다."}

    with _lock:
        tile = _tiles.get((q, r))
        building = BUILDINGS[building_type]
        owned_buildings = _owned_buildings_locked(client_id)
        error = _build_locked(client_id, tile, building, owned_buildings)
        if error is not None:
            return {"ok": False, "message": error}
        state = _user_state_locked(client_id)

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
    include_building = data.get("include_building", True)
    if not isinstance(include_building, bool):
        return {"ok": False, "message": "건물 인수 설정이 올바르지 않습니다."}

    with _lock:
        tile = _tiles.get((q, r))
        error = _buy_locked(client_id, tile, include_building, data)
        if error is not None:
            return {"ok": False, "message": error}
        state = _user_state_locked(client_id)

    _broadcast_locked_state()
    return {"ok": True, **state}
