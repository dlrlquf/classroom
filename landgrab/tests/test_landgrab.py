import random
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from flask import Flask, request

import landgrab
import routes
from landgrab.tools.build_landgrab_maps import world_terrain


class PackageLayoutTests(unittest.TestCase):
    def test_game_templates_and_assets_are_available(self):
        root = Path(landgrab.__file__).parent.parent
        app = Flask(__name__, template_folder=str(root / "templates"))
        app.register_blueprint(landgrab.bp)
        with app.app_context():
            app.jinja_env.get_template("apps/landgrab_host.html")
            app.jinja_env.get_template("apps/landgrab_user.html")
        with app.test_client() as client:
            for path in (
                "landgrab.css", "js/landgrab_map.js",
                "js/landgrab_host.js", "js/landgrab_user.js",
            ):
                with self.subTest(path=path):
                    response = client.get("/landgrab/static/" + path)
                    try:
                        self.assertEqual(response.status_code, 200)
                    finally:
                        response.close()

    def test_game_pages_render_with_packaged_assets(self):
        root = Path(landgrab.__file__).parent.parent
        app = Flask(__name__, template_folder=str(root / "templates"))
        app.register_blueprint(routes.bp)
        app.register_blueprint(landgrab.bp)
        with (
            patch("routes._is_admin_ip_allowed", return_value=True),
            patch("routes.set_active_app"),
            patch("routes._make_join_info", return_value={"join_url": None, "qr_code": None}),
            app.test_client() as client,
        ):
            for path, expected in (
                ("/user", b"/landgrab/static/js/landgrab_user.js"),
                ("/user/app/landgrab", b"landgrab-user-map"),
                ("/app/landgrab", b"/landgrab/static/js/landgrab_host.js"),
            ):
                with self.subTest(path=path):
                    response = client.get(path)
                    try:
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(expected, response.data)
                    finally:
                        response.close()
        with patch("routes._is_admin_ip_allowed", return_value=False), app.test_client() as client:
            for path in ("/user/app/landgrab", "/landgrab/static/js/landgrab_user.js"):
                with self.subTest(remote_path=path):
                    response = client.get(path)
                    try:
                        self.assertEqual(response.status_code, 200)
                    finally:
                        response.close()


class WorldTerrainTests(unittest.TestCase):
    def test_water_threshold_includes_exactly_ninety_percent(self):
        self.assertEqual(world_terrain([[80] * 9 + [30]], [[0] * 10]), "w")
        self.assertEqual(world_terrain([[80] * 8 + [30, 30]], [[0] * 10]), "g")

    def test_mountains_use_land_only_mean_with_inclusive_threshold(self):
        self.assertEqual(world_terrain([[80, 30, 30]], [[0, 500, 1500]]), "m")
        self.assertEqual(world_terrain([[80, 30, 30]], [[0, 500, 1499]]), "g")

    def test_land_cover_and_missing_data(self):
        self.assertEqual(world_terrain([[255, 0, 111]], [[0, 300, 400]]), "g")
        self.assertEqual(world_terrain([[80, 111, 112]], [[0, 200, 300]]), "f")
        self.assertEqual(world_terrain([[255, 0]], [[0, -50]]), "w")
        with self.assertRaises(ValueError):
            world_terrain([[254]], [[100]])
        with self.assertRaises(ValueError):
            world_terrain([], [])


class MapSizeTests(unittest.TestCase):
    def setUp(self):
        self.state = patch.multiple(
            landgrab,
            _game_id=0,
            _phase="waiting",
            _resource_interval=60,
            _cost_increase_rate=10,
            _map_width=9,
            _map_height=9,
            _map_generation="random",
            _map_size=None,
            _map_country=None,
            _map_wrap=False,
            _next_resource_at=None,
            _tiles={},
            _players={},
            _port_links=set(),
        )
        self.state.start()
        self.addCleanup(self.state.stop)
        for target in (
            "landgrab._is_host",
            "landgrab.lobby.online_users",
            "landgrab.socketio.start_background_task",
            "landgrab._broadcast_locked_state",
        ):
            mock = patch(target)
            started = mock.start()
            self.addCleanup(mock.stop)
            if target == "landgrab._is_host":
                started.return_value = True
            elif target == "landgrab.lobby.online_users":
                started.return_value = {}

    def test_selected_dimensions_create_rectangular_map(self):
        for width, height in ((3, 100), (9, 9), (100, 3), (100, 100)):
            with self.subTest(width=width, height=height):
                response = landgrab.on_landgrab_start({
                    "resource_interval": 60,
                    "cost_increase_rate": 10,
                    "map_width": width,
                    "map_height": height,
                })
                self.assertTrue(response["ok"])
                self.assertEqual(response["map_width"], width)
                self.assertEqual(response["map_height"], height)
                self.assertEqual(len(response["tiles"]), width * height)
                rows = {}
                for tile in response["tiles"]:
                    rows.setdefault(tile["r"], set()).add(tile["q"] + tile["r"] // 2)
                self.assertEqual(len(rows), height)
                self.assertTrue(all(
                    columns == set(range(-(width // 2), width - width // 2))
                    for columns in rows.values()
                ))
                tiles = {(tile["q"], tile["r"]) for tile in response["tiles"]}
                pending = [next(iter(tiles))]
                connected = set(pending)
                while pending:
                    q, r = pending.pop()
                    for dq, dr in landgrab.NEIGHBORS:
                        neighbor = (q + dq, r + dr)
                        if neighbor in tiles and neighbor not in connected:
                            connected.add(neighbor)
                            pending.append(neighbor)
                self.assertEqual(connected, tiles)
                self.assertEqual(landgrab._host_state_locked()["map_width"], width)
                self.assertEqual(landgrab._host_state_locked()["map_height"], height)

    def test_missing_dimensions_use_defaults(self):
        response = landgrab.on_landgrab_start({
            "resource_interval": 60,
            "cost_increase_rate": 10,
        })
        self.assertTrue(response["ok"])
        self.assertEqual((response["map_width"], response["map_height"]), (9, 9))
        self.assertEqual(len(response["tiles"]), 81)

    def test_maximum_dimensions_create_full_map(self):
        response = landgrab.on_landgrab_start({
            "resource_interval": 60,
            "cost_increase_rate": 10,
            "map_width": 300,
            "map_height": 300,
        })
        self.assertTrue(response["ok"])
        self.assertEqual((response["map_width"], response["map_height"]), (300, 300))
        self.assertEqual(len(response["tiles"]), 90000)

    def test_preset_size_and_country_aspect(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "country_maps").mkdir()
            (data / "country_maps" / "example.txt").write_text("gg\ngg\n", encoding="ascii")
            countries = [{"id": "example", "name": "예시", "width": 150, "height": 300}]
            with (
                patch.object(landgrab, "DATA_DIRECTORY", data),
                patch("landgrab._countries", return_value=countries),
            ):
                response = landgrab.on_landgrab_start({
                    "resource_interval": 60,
                    "cost_increase_rate": 10,
                    "map_size": 300,
                    "map_generation": "country",
                    "map_country": "example",
                })
        self.assertTrue(response["ok"])
        self.assertEqual((response["map_width"], response["map_height"]), (150, 300))
        self.assertEqual(response["map_size"], 300)
        self.assertEqual(response["map_country"], "example")

    def test_rejects_invalid_preset_or_country(self):
        for size in (29, 31, 301, True):
            with self.subTest(size=size):
                response = landgrab.on_landgrab_start({
                    "resource_interval": 60,
                    "cost_increase_rate": 10,
                    "map_size": size,
                })
                self.assertFalse(response["ok"])
        with patch("landgrab._countries", return_value=[]):
            response = landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_size": 30,
                "map_generation": "country",
                "map_country": "missing",
            })
        self.assertFalse(response["ok"])

    def test_ai_players_start_with_cities_and_resources(self):
        landgrab.lobby.online_users.return_value = {"human": "참가자"}
        with patch("landgrab.random.choices", return_value=["grass"]):
            response = landgrab.on_landgrab_start({
                "resource_interval": 60, "cost_increase_rate": 10, "ai_count": 2,
            })
        self.assertTrue(response["ok"])
        self.assertEqual(response["ai_count"], 2)
        self.assertEqual({player["name"] for player in response["players"]},
                         {"참가자", "AI 1", "AI 2"})
        for client_id in ("ai:1", "ai:2"):
            player = landgrab._players[client_id]
            self.assertTrue(player["is_ai"])
            self.assertEqual(player["resources"], landgrab.STARTING_RESOURCES)
            tile = landgrab._tiles[player["start"]]
            self.assertEqual((tile["owner"], tile["building"]), (client_id, "city"))
        self.assertEqual(landgrab.socketio.start_background_task.call_count, 2)

    def test_player_colors_are_distinct_and_persist_for_late_joins(self):
        landgrab.lobby.online_users.return_value = {"human": "참가자"}
        with patch("landgrab.random.choices", return_value=["grass"]):
            response = landgrab.on_landgrab_start({
                "resource_interval": 60, "cost_increase_rate": 10, "ai_count": 1,
            })
        self.assertTrue(response["ok"])
        self.assertTrue(landgrab._assign_player_locked("late", "나중 참가자"))
        colors = {client_id: player["color"] for client_id, player in landgrab._players.items()}
        self.assertEqual(len(set(colors.values())), 3)
        host_state = landgrab._host_state_locked()
        user_state = landgrab._user_state_locked("human")
        for client_id, color in colors.items():
            player = landgrab._players[client_id]
            position = player["start"]
            tile = next(item for item in host_state["tiles"]
                        if (item["q"], item["r"]) == position)
            user_tile = next(item for item in user_state["tiles"]
                             if (item["q"], item["r"]) == position)
            self.assertEqual(tile["owner_color"], color)
            self.assertEqual(user_tile["owner_color"], color)
        self.assertTrue(landgrab._assign_player_locked("human", "다시 접속"))
        self.assertEqual(landgrab._players["human"]["color"], colors["human"])

    def test_captured_tile_uses_new_owners_color(self):
        landgrab._phase = "running"
        landgrab._players.update({
            "buyer": {"name": "구매자", "color": "#123456",
                      "resources": {"wood": 20, "stone": 20, "food": 20}},
            "owner": {"name": "소유자", "color": "#abcdef",
                      "resources": dict(landgrab.STARTING_RESOURCES)},
        })
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "buyer", "building": "city"},
            (1, 0): {"q": 1, "r": 0, "terrain": "grass", "owner": "owner", "building": None},
            (2, 0): {"q": 2, "r": 0, "terrain": "grass", "owner": "owner", "building": "city"},
        })
        tile = landgrab._tiles[(1, 0)]
        self.assertEqual(landgrab._tile_payload(tile)["owner_color"], "#abcdef")
        self.assertIsNone(landgrab._buy_locked("buyer", tile, True, {}))
        self.assertEqual(landgrab._tile_payload(tile)["owner_color"], "#123456")
        tile["owner"] = None
        self.assertIsNone(landgrab._tile_payload(tile)["owner_color"])

    def test_player_color_remains_unique_when_palette_is_exhausted(self):
        landgrab._players.update({
            str(index): {"color": color}
            for index, color in enumerate(landgrab.PLAYER_COLORS)
        })
        with patch("landgrab.random.randrange", return_value=0x010203):
            self.assertEqual(landgrab._next_player_color_locked(), "#010203")

    def test_invalid_or_unplaceable_ai_count_does_not_start(self):
        for value in (True, -1, 11, 1.5, None):
            with self.subTest(value=value):
                result = landgrab.on_landgrab_start({
                    "resource_interval": 60, "cost_increase_rate": 10, "ai_count": value,
                })
                self.assertFalse(result["ok"])
                self.assertEqual(landgrab._phase, "waiting")
        with patch("landgrab.random.choices", return_value=["grass"]):
            result = landgrab.on_landgrab_start({
                "resource_interval": 60, "cost_increase_rate": 10,
                "map_width": 3, "map_height": 3, "ai_count": 10,
            })
        self.assertFalse(result["ok"])
        self.assertEqual(landgrab._phase, "waiting")

    def test_ai_builds_using_normal_rules(self):
        landgrab._phase = "running"
        landgrab._players["ai:1"] = {
            "name": "AI 1", "is_ai": True, "resources": dict(landgrab.STARTING_RESOURCES),
        }
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "ai:1", "building": "city"},
            (1, 0): {"q": 1, "r": 0, "terrain": "grass", "owner": "ai:1", "building": None},
        })
        self.assertTrue(landgrab._ai_take_turn_locked("ai:1"))
        self.assertEqual(landgrab._tiles[(1, 0)]["building"], "farm")
        self.assertEqual(landgrab._players["ai:1"]["resources"]["wood"], 0)
        landgrab._players["ai:1"]["eliminated"] = True
        self.assertFalse(landgrab._ai_take_turn_locked("ai:1"))

    def test_ai_buys_adjacent_land_only_when_affordable(self):
        landgrab._phase = "running"
        landgrab._players["ai:1"] = {
            "name": "AI 1", "is_ai": True, "resources": {"wood": 0, "stone": 5, "food": 5},
        }
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "ai:1", "building": "city"},
            (1, 0): {"q": 1, "r": 0, "terrain": "grass", "owner": None, "building": None},
        })
        self.assertFalse(landgrab._ai_take_turn_locked("ai:1"))
        self.assertIsNone(landgrab._tiles[(1, 0)]["owner"])
        landgrab._players["ai:1"]["resources"]["wood"] = 5
        self.assertTrue(landgrab._ai_take_turn_locked("ai:1"))
        self.assertEqual(landgrab._tiles[(1, 0)]["owner"], "ai:1")
        self.assertEqual(landgrab._players["ai:1"]["resources"], {"wood": 3, "stone": 5, "food": 3})

    def test_ai_capture_uses_normal_cost_and_eliminates_defender(self):
        landgrab._phase = "running"
        landgrab._players.update({
            "ai:1": {"name": "AI 1", "is_ai": True, "resources": {"wood": 30, "stone": 30, "food": 30}},
            "human": {"name": "참가자", "resources": dict(landgrab.STARTING_RESOURCES)},
        })
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "ai:1", "building": "city"},
            (1, 0): {"q": 1, "r": 0, "terrain": "grass", "owner": "human", "building": "city"},
            (2, 0): {"q": 2, "r": 0, "terrain": "grass", "owner": "human", "building": "farm"},
        })
        self.assertTrue(landgrab._ai_take_turn_locked("ai:1"))
        self.assertEqual(landgrab._tiles[(1, 0)]["owner"], "ai:1")
        self.assertEqual(landgrab._tiles[(1, 0)]["building"], "city")
        self.assertEqual(landgrab._players["ai:1"]["resources"], {"wood": 16, "stone": 20, "food": 16})
        self.assertTrue(landgrab._players["human"]["eliminated"])
        self.assertIsNone(landgrab._tiles[(2, 0)]["owner"])
        self.assertIsNone(landgrab._tiles[(2, 0)]["building"])

    def test_ai_loop_stops_after_game_changes_and_skips_eliminated_players(self):
        landgrab._phase = "running"
        landgrab._game_id = 1
        landgrab._players.update({
            "ai:1": {"is_ai": True, "eliminated": False},
            "ai:2": {"is_ai": True, "eliminated": True},
        })
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                landgrab._game_id += 1

        with (
            patch("landgrab.socketio.sleep", side_effect=sleep),
            patch("landgrab._ai_take_turn_locked", return_value=True) as turn,
        ):
            landgrab._ai_loop(1)
        turn.assert_called_once_with("ai:1")
        landgrab._broadcast_locked_state.assert_called_once()
        self.assertEqual(sleeps, [10, 10])

    def test_host_and_user_receive_registered_resource_names(self):
        response = landgrab.on_landgrab_start({
            "resource_interval": 60,
            "cost_increase_rate": 10,
        })
        self.assertTrue(response["ok"])
        self.assertEqual(response["resource_names"], {
            "wood": "목재", "stone": "석재", "food": "식량", "iron": "철", "luxury": "사치품",
        })
        self.assertEqual(landgrab._user_state_locked("unknown")["resource_names"],
                         response["resource_names"])

    def test_host_and_user_receive_registered_resource_icons(self):
        response = landgrab.on_landgrab_start({
            "resource_interval": 60,
            "cost_increase_rate": 10,
        })
        self.assertTrue(response["ok"])
        self.assertEqual(response["resource_icons"], {
            "wood": "🪵", "stone": "🪨", "food": "🌾", "iron": "⛓️", "luxury": "💎",
        })
        self.assertEqual(landgrab._user_state_locked("unknown")["resource_icons"],
                         response["resource_icons"])
        landgrab._players["player"] = {
            "name": "참가자", "resources": dict(landgrab.STARTING_RESOURCES),
        }
        self.assertEqual(landgrab._user_state_locked("player")["resource_icons"],
                         response["resource_icons"])

    def test_invalid_dimensions_do_not_start_game(self):
        for dimension in ("map_width", "map_height"):
            for value in (2, 301, True, 3.5, "9", None):
                with self.subTest(dimension=dimension, value=value):
                    response = landgrab.on_landgrab_start({
                        "resource_interval": 60,
                        "cost_increase_rate": 10,
                        dimension: value,
                    })
                    self.assertFalse(response["ok"])
                    self.assertIn("3~300", response["message"])
                    self.assertEqual(landgrab._phase, "waiting")
                    self.assertEqual(landgrab._tiles, {})

    def test_player_can_buy_adjacent_tile_on_rectangular_map(self):
        landgrab.lobby.online_users.return_value = {"player": "참가자"}
        with patch("landgrab.random.choices", return_value=["grass"]):
            response = landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 3,
                "map_height": 5,
            })
        self.assertTrue(response["ok"])
        buyable = landgrab._user_state_locked("player")["buyable"]
        self.assertTrue(buyable)
        tile = buyable[0]
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("player", {})),
        ):
            request.sid = "socket"
            purchase = landgrab.on_landgrab_buy({"q": tile["q"], "r": tile["r"]})
        self.assertTrue(purchase["ok"])
        self.assertEqual(landgrab._tiles[(tile["q"], tile["r"])]["owner"], "player")

    def setup_occupied_tiles(self, target_building="farm", defender_has_other_city=True):
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 15,
                "map_height": 7,
            })
        for player, start in (("buyer", (0, 0)), ("defender", (5, 0))):
            landgrab._players[player] = {
                "name": player, "resources": {"wood": 100, "stone": 100, "food": 100},
                "start": start, "eliminated": False,
            }
        landgrab._tiles[(0, 0)]["owner"] = "buyer"
        landgrab._tiles[(0, 0)]["building"] = "city"
        landgrab._tiles[(1, 0)]["owner"] = "defender"
        landgrab._tiles[(1, 0)]["building"] = target_building
        landgrab._tiles[(5, 0)]["owner"] = "defender"
        landgrab._tiles[(5, 0)]["building"] = "city" if defender_has_other_city else "farm"

    def test_occupied_tile_purchase_can_include_building(self):
        self.setup_occupied_tiles()
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
        ):
            request.sid = "socket"
            info = landgrab.on_landgrab_tile_info({"q": 1, "r": 0})
            self.assertEqual(info["purchase_options"]["land_only"]["cost"], {"wood": 4, "food": 4})
            self.assertEqual(info["purchase_options"]["with_building"]["cost"], {"wood": 14, "food": 4})
            self.assertIsNone(info["purchase_options"]["with_building"]["error"])
            self.assertIn((1, 0), {
                (tile["q"], tile["r"]) for tile in landgrab._user_state_locked("buyer")["buyable"]
            })
            result = landgrab.on_landgrab_buy({"q": 1, "r": 0, "include_building": True})
        self.assertTrue(result["ok"])
        self.assertEqual(landgrab._tiles[(1, 0)]["owner"], "buyer")
        self.assertEqual(landgrab._tiles[(1, 0)]["building"], "farm")
        self.assertEqual(landgrab._players["buyer"]["resources"], {
            "wood": 86, "stone": 100, "food": 96,
        })
        self.assertFalse(landgrab._players["defender"]["eliminated"])

    def test_occupied_tile_purchase_can_demolish_building(self):
        self.setup_occupied_tiles()
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
        ):
            request.sid = "socket"
            result = landgrab.on_landgrab_buy({"q": 1, "r": 0, "include_building": False})
        self.assertTrue(result["ok"])
        self.assertIsNone(landgrab._tiles[(1, 0)]["building"])
        self.assertEqual(landgrab._players["buyer"]["resources"], {
            "wood": 96, "stone": 100, "food": 96,
        })

    def test_last_city_capture_eliminates_defender(self):
        for include in (True, False):
            with self.subTest(include_building=include):
                self.setup_occupied_tiles(target_building="city", defender_has_other_city=False)
                with (
                    Flask(__name__).test_request_context(),
                    patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
                ):
                    request.sid = "socket"
                    info = landgrab.on_landgrab_tile_info({"q": 1, "r": 0})
                    self.assertEqual(info["purchase_options"]["with_building"]["cost"], {
                        "wood": 14, "stone": 10, "food": 14,
                    })
                    result = landgrab.on_landgrab_buy({
                        "q": 1, "r": 0, "include_building": include,
                    })
                self.assertTrue(result["ok"])
                self.assertEqual(landgrab._tiles[(1, 0)]["building"], "city" if include else None)
                self.assertTrue(landgrab._players["defender"]["eliminated"])
                self.assertIsNone(landgrab._tiles[(5, 0)]["owner"])
                self.assertIsNone(landgrab._tiles[(5, 0)]["building"])
                self.assertEqual(landgrab._user_state_locked("defender")["buyable"], [])
                self.assertTrue(landgrab._assign_player_locked("defender", "defender"))
                self.assertTrue(landgrab._players["defender"]["eliminated"])
                with (
                    Flask(__name__).test_request_context(),
                    patch("landgrab.lobby.get_user_by_sid", return_value=("defender", {})),
                ):
                    request.sid = "socket"
                    self.assertFalse(landgrab.on_landgrab_buy({"q": 0, "r": 0})["ok"])

    def test_capture_keeps_defender_active_when_another_city_remains(self):
        self.setup_occupied_tiles(target_building="city")
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
        ):
            request.sid = "socket"
            result = landgrab.on_landgrab_buy({"q": 1, "r": 0, "include_building": True})
        self.assertTrue(result["ok"])
        self.assertFalse(landgrab._players["defender"]["eliminated"])
        self.assertEqual(landgrab._tiles[(5, 0)]["owner"], "defender")

    def setup_connected_territory(self):
        landgrab._phase = "running"
        landgrab._players.update({
            "owner": {"name": "소유자", "resources": {"wood": 100, "stone": 100, "food": 100}},
            "attacker": {"name": "공격자", "resources": {"wood": 100, "stone": 100, "food": 100}},
        })
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "owner", "building": "city"},
            (1, 0): {"q": 1, "r": 0, "terrain": "grass", "owner": "owner", "building": None},
            (2, 0): {"q": 2, "r": 0, "terrain": "grass", "owner": "owner", "building": "farm"},
            (3, 0): {"q": 3, "r": 0, "terrain": "grass", "owner": "owner", "building": None},
            (4, 0): {"q": 4, "r": 0, "terrain": "grass", "owner": None, "building": None},
            (1, -1): {"q": 1, "r": -1, "terrain": "grass", "owner": "attacker", "building": "city"},
        })

    def test_linked_port_purchase_capture_and_destruction(self):
        landgrab._phase = "running"
        landgrab._players.update({
            "player": {
                "name": "참가자", "resources": {**landgrab.STARTING_RESOURCES, "wood": 100, "stone": 100, "food": 100},
            },
            "attacker": {
                "name": "상대", "resources": {**landgrab.STARTING_RESOURCES, "wood": 100, "stone": 100, "food": 100},
            },
        })
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "player", "building": "city"},
            (1, 0): {"q": 1, "r": 0, "terrain": "coast", "owner": "player", "building": "port"},
            (2, 0): {"q": 2, "r": 0, "terrain": "water", "owner": None, "building": None},
            (3, 0): {"q": 3, "r": 0, "terrain": "coast", "owner": None, "building": None},
            (4, 0): {"q": 4, "r": 0, "terrain": "grass", "owner": "player", "building": None},
            (1, -1): {"q": 1, "r": -1, "terrain": "grass", "owner": "attacker", "building": "city"},
        })
        data = {
            "source": {"q": 1, "r": 0}, "target": {"q": 3, "r": 0},
            "game_id": 0, "expected_distance": 2,
            "expected_cost": {"wood": 8, "stone": 3, "food": 1},
        }
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("player", {})),
        ):
            request.sid = "socket"
            for invalid in (
                {**data, "game_id": 1},
                {**data, "expected_distance": 3},
                {**data, "expected_cost": {"wood": 1}},
            ):
                with self.subTest(invalid=invalid):
                    before = deepcopy((landgrab._tiles, landgrab._players, landgrab._port_links))
                    self.assertFalse(landgrab.on_landgrab_build_linked_port(invalid)["ok"])
                    self.assertEqual((landgrab._tiles, landgrab._players, landgrab._port_links), before)
            for tile, changes in (
                (landgrab._tiles[(1, 0)], {"owner": "attacker"}),
                (landgrab._tiles[(1, 0)], {"building": None}),
                (landgrab._tiles[(3, 0)], {"owner": "player"}),
                (landgrab._tiles[(3, 0)], {"building": "port"}),
                (landgrab._tiles[(2, 0)], {"owner": "attacker"}),
                (landgrab._players["player"]["resources"], {"wood": 0}),
            ):
                with self.subTest(changes=changes), patch.dict(tile, changes):
                    before = deepcopy((landgrab._tiles, landgrab._players, landgrab._port_links))
                    self.assertFalse(landgrab.on_landgrab_build_linked_port(data)["ok"])
                    self.assertEqual((landgrab._tiles, landgrab._players, landgrab._port_links), before)
            result = landgrab.on_landgrab_build_linked_port(data)
        self.assertTrue(result["ok"])
        self.assertEqual(landgrab._players["player"]["resources"]["wood"], 92)
        self.assertEqual(landgrab._players["player"]["resources"]["stone"], 97)
        self.assertEqual(landgrab._players["player"]["resources"]["food"], 99)
        self.assertIn((4, 0), landgrab._active_tiles_locked())
        self.assertTrue(result["port_links"][0]["active"])

        source = landgrab._tiles[(1, 0)]
        self.assertIsNone(landgrab._buy_locked("attacker", source, True, {}))
        self.assertNotIn((4, 0), landgrab._active_tiles_locked())
        self.assertIsNone(landgrab._buy_locked("player", source, True, {}))
        self.assertIn((4, 0), landgrab._active_tiles_locked())
        self.assertIsNone(landgrab._buy_locked("attacker", source, False, {}))
        self.assertFalse(landgrab._port_links)
        self.assertIsNone(landgrab._buy_locked("player", source, True, {}))
        self.assertIsNone(landgrab._build_locked(
            "player", source, landgrab.BUILDINGS["port"], landgrab._owned_buildings_locked("player"),
        ))
        self.assertNotIn((4, 0), landgrab._active_tiles_locked())

    def test_sea_route_blocks_other_owners_and_obeys_wrap(self):
        landgrab._tiles = {
            (-2, 0): {"q": -2, "r": 0, "terrain": "coast", "owner": "player", "building": "port"},
            (-1, 0): {"q": -1, "r": 0, "terrain": "water", "owner": "other", "building": None},
            (0, 0): {"q": 0, "r": 0, "terrain": "coast", "owner": None, "building": None},
            (2, 0): {"q": 2, "r": 0, "terrain": "coast", "owner": None, "building": None},
        }
        landgrab._map_width = 5
        self.assertIsNone(landgrab._sea_distance_locked("player", (-2, 0), (0, 0)))
        landgrab._tiles[(-1, 0)]["owner"] = "player"
        self.assertEqual(landgrab._sea_distance_locked("player", (-2, 0), (0, 0)), 2)
        landgrab._map_wrap = True
        self.assertEqual(landgrab._sea_distance_locked("player", (-2, 0), (2, 0)), 1)

    def test_port_opens_coast_for_connection_and_expansion(self):
        landgrab._phase = "running"
        landgrab._players["player"] = {
            "name": "참가자",
            "resources": {**landgrab.STARTING_RESOURCES, "wood": 20, "stone": 20, "food": 20},
        }
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "player", "building": "city"},
            (1, 0): {"q": 1, "r": 0, "terrain": "coast", "owner": None, "building": None},
            (2, 0): {"q": 2, "r": 0, "terrain": "grass", "owner": "player", "building": None},
            (3, 0): {"q": 3, "r": 0, "terrain": "grass", "owner": None, "building": None},
        })
        coast = landgrab._tiles[(1, 0)]
        self.assertIsNone(landgrab._buy_locked("player", coast, True, {}))
        self.assertTrue(landgrab._tile_payload(coast)["active"])
        self.assertFalse(landgrab._tile_payload(coast)["movable"])
        self.assertFalse(landgrab._tile_payload(landgrab._tiles[(2, 0)])["active"])
        self.assertFalse(landgrab._has_neighbor_locked("player", 2, 0))
        self.assertIsNone(landgrab._build_locked(
            "player", coast, landgrab.BUILDINGS["port"], landgrab._owned_buildings_locked("player"),
        ))
        self.assertTrue(landgrab._tile_payload(coast)["movable"])
        self.assertTrue(landgrab._tile_payload(landgrab._tiles[(2, 0)])["active"])
        self.assertTrue(landgrab._has_neighbor_locked("player", 3, 0))
        coast["building"] = None
        self.assertFalse(landgrab._tile_payload(landgrab._tiles[(2, 0)])["active"])

    def test_impassable_terrain_is_buyable_but_cannot_expand(self):
        for terrain in ("water", "coast", "mountain", "cliff"):
            with self.subTest(terrain=terrain):
                tile = {"q": 1, "r": 0, "terrain": terrain, "owner": None, "building": None}
                landgrab._tiles = {
                    (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "player", "building": "city"},
                    (1, 0): tile,
                }
                landgrab._phase = "running"
                landgrab._players["player"] = {
                    "name": "참가자", "resources": dict(landgrab.STARTING_RESOURCES),
                }
                self.assertIsNone(landgrab._buy_locked("player", tile, True, {}))
                self.assertTrue(landgrab._tile_payload(tile)["active"])
                self.assertFalse(landgrab._has_neighbor_locked("player", 2, 0))

    def test_cut_off_land_stops_production_and_actions_until_reconnected(self):
        self.setup_connected_territory()
        bridge = landgrab._tiles[(1, 0)]
        island = landgrab._tiles[(2, 0)]
        self.assertEqual(landgrab._user_state_locked("owner")["production"], {
            "wood": 1, "stone": 1, "food": 11, "iron": 0, "luxury": 0,
        })
        self.assertIsNone(landgrab._buy_locked("attacker", bridge, True, {}))
        self.assertFalse(landgrab._tile_payload(island)["active"])
        self.assertEqual(landgrab._tile_payload(island)["production"], {})
        self.assertEqual(landgrab._user_state_locked("owner")["production"], {
            "wood": 1, "stone": 1, "food": 3, "iron": 0, "luxury": 0,
        })
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("owner", {})),
        ):
            request.sid = "socket"
            info = landgrab.on_landgrab_tile_info({"q": 3, "r": 0})
            farm = next(building for building in info["buildings"] if building["type"] == "farm")
            self.assertIn("연결되지", farm["error"])
            self.assertFalse(landgrab.on_landgrab_build({"q": 3, "r": 0, "building": "farm"})["ok"])
            self.assertFalse(landgrab.on_landgrab_buy({"q": 4, "r": 0})["ok"])

        def award_tick():
            calls = []

            def sleep(_seconds):
                calls.append(None)
                if len(calls) == 2:
                    landgrab._phase = "ended"

            with (
                patch("landgrab.socketio.sleep", side_effect=sleep),
                patch("landgrab.time.monotonic", return_value=60),
            ):
                landgrab._resource_loop(landgrab._game_id, 60)
            landgrab._phase = "running"

        award_tick()
        self.assertEqual(landgrab._players["owner"]["resources"], {
            "wood": 101, "stone": 101, "food": 103,
        })
        self.assertIsNone(landgrab._buy_locked("owner", bridge, True, {}))
        self.assertTrue(landgrab._tile_payload(island)["active"])
        self.assertEqual(landgrab._tile_payload(island)["production"], {"food": 4})
        award_tick()
        self.assertEqual(landgrab._players["owner"]["resources"], {
            "wood": 98, "stone": 102, "food": 110,
        })
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("owner", {})),
        ):
            request.sid = "socket"
            self.assertTrue(landgrab.on_landgrab_build({"q": 3, "r": 0, "building": "farm"})["ok"])

    def test_cut_off_land_connected_to_another_city_stays_active(self):
        self.setup_connected_territory()
        landgrab._tiles[(4, 0)]["owner"] = "owner"
        for q in (5, 6):
            landgrab._tiles[(q, 0)] = {
                "q": q, "r": 0, "terrain": "grass", "owner": "owner",
                "building": "city" if q == 6 else None,
            }
        self.assertIsNone(landgrab._buy_locked("attacker", landgrab._tiles[(1, 0)], True, {}))
        self.assertTrue(landgrab._tile_payload(landgrab._tiles[(2, 0)])["active"])
        self.assertEqual(landgrab._tile_payload(landgrab._tiles[(2, 0)])["production"], {"food": 4})

    def test_city_connectivity_obeys_horizontal_wrap(self):
        landgrab._map_width = 5
        landgrab._tiles.update({
            (-2, 0): {"q": -2, "r": 0, "terrain": "grass", "owner": "player", "building": "city"},
            (2, 0): {"q": 2, "r": 0, "terrain": "grass", "owner": "player", "building": "farm"},
        })
        landgrab._map_wrap = False
        self.assertFalse(landgrab._tile_payload(landgrab._tiles[(2, 0)])["active"])
        landgrab._map_wrap = True
        self.assertTrue(landgrab._tile_payload(landgrab._tiles[(2, 0)])["active"])

    def test_ai_cannot_use_disconnected_land(self):
        landgrab._phase = "running"
        landgrab._players["ai:1"] = {
            "name": "AI 1", "is_ai": True, "resources": {"wood": 100, "stone": 100, "food": 100},
        }
        landgrab._tiles.update({
            (0, 0): {"q": 0, "r": 0, "terrain": "grass", "owner": "ai:1", "building": "city"},
            (3, 0): {"q": 3, "r": 0, "terrain": "grass", "owner": "ai:1", "building": None},
            (4, 0): {"q": 4, "r": 0, "terrain": "grass", "owner": None, "building": None},
        })
        self.assertFalse(landgrab._ai_take_turn_locked("ai:1"))
        self.assertIsNone(landgrab._tiles[(3, 0)]["building"])
        self.assertIsNone(landgrab._tiles[(4, 0)]["owner"])

    def test_city_capture_cost_uses_buyers_city_count(self):
        self.setup_occupied_tiles(target_building="city")
        landgrab._tiles[(-6, 0)]["owner"] = "buyer"
        landgrab._tiles[(-6, 0)]["building"] = "city"
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
        ):
            request.sid = "socket"
            info = landgrab.on_landgrab_tile_info({"q": 1, "r": 0})
        self.assertEqual(info["purchase_options"]["with_building"]["cost"], {
            "wood": 24, "stone": 20, "food": 24,
        })

    def test_purchase_rejects_stale_quotes_and_nonadjacent_tiles(self):
        self.setup_occupied_tiles()
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
        ):
            request.sid = "socket"
            for data in (
                {"q": 1, "r": 0, "include_building": True, "expected_building": None},
                {"q": 1, "r": 0, "include_building": True, "expected_cost": {"wood": 4}},
                {"q": 5, "r": 0},
            ):
                with self.subTest(data=data):
                    self.assertFalse(landgrab.on_landgrab_buy(data)["ok"])
        self.assertEqual(landgrab._tiles[(1, 0)]["owner"], "defender")
        self.assertEqual(landgrab._players["buyer"]["resources"], {
            "wood": 100, "stone": 100, "food": 100,
        })

    def test_purchase_options_check_affordability_separately(self):
        self.setup_occupied_tiles()
        landgrab._players["buyer"]["resources"] = {"wood": 5, "stone": 0, "food": 5}
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
        ):
            request.sid = "socket"
            info = landgrab.on_landgrab_tile_info({"q": 1, "r": 0})
            self.assertIsNone(info["purchase_options"]["land_only"]["error"])
            self.assertEqual(info["purchase_options"]["with_building"]["error"], "자원이 부족합니다.")
            self.assertFalse(landgrab.on_landgrab_buy({
                "q": 1, "r": 0, "include_building": True,
            })["ok"])
            self.assertFalse(landgrab.on_landgrab_buy({
                "q": 1, "r": 0, "include_building": "false",
            })["ok"])
            self.assertTrue(landgrab.on_landgrab_buy({
                "q": 1, "r": 0, "include_building": False,
            })["ok"])

    def test_capture_across_wrapped_edge(self):
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60, "cost_increase_rate": 10,
                "map_width": 5, "map_height": 5, "map_wrap": True,
            })
        for player, position in (("buyer", (-2, 0)), ("defender", (2, 0))):
            landgrab._players[player] = {
                "name": player, "resources": {"wood": 100, "stone": 100, "food": 100},
                "start": position, "eliminated": False,
            }
            landgrab._tiles[position]["owner"] = player
            landgrab._tiles[position]["building"] = "city"
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("buyer", {})),
        ):
            request.sid = "socket"
            info = landgrab.on_landgrab_tile_info({"q": 2, "r": 0})
            self.assertEqual(info["tile"]["distance"], 1)
            self.assertTrue(landgrab.on_landgrab_buy({
                "q": 2, "r": 0, "include_building": False,
            })["ok"])
        self.assertTrue(landgrab._players["defender"]["eliminated"])

    def test_wrapped_neighbors_and_distance_allow_purchase_across_edge(self):
        with patch("landgrab.random.choices", return_value=["grass"]):
            response = landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 5,
                "map_height": 5,
                "map_wrap": True,
            })
        self.assertTrue(response["ok"])
        self.assertTrue(response["map_wrap"])
        start = (-2, 0)
        landgrab._tiles[start]["owner"] = "player"
        landgrab._tiles[start]["building"] = "city"
        landgrab._players["player"] = {
            "name": "참가자",
            "resources": dict(landgrab.STARTING_RESOURCES),
            "start": start,
        }
        state = landgrab._user_state_locked("player")
        self.assertTrue(state["map_wrap"])
        buyable = {(tile["q"], tile["r"]): tile for tile in state["buyable"]}
        self.assertEqual(buyable[(2, 0)]["distance"], 1)
        self.assertEqual(buyable[(2, 1)]["distance"], 1)
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("player", {})),
        ):
            request.sid = "socket"
            purchase = landgrab.on_landgrab_buy({"q": 2, "r": 0})
        self.assertTrue(purchase["ok"])
        self.assertEqual(landgrab._tiles[(2, 0)]["owner"], "player")

    def test_wrapping_is_optional_and_does_not_wrap_vertically(self):
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 5,
                "map_height": 5,
            })
        landgrab._tiles[(-2, 0)]["owner"] = "player"
        landgrab._tiles[(-2, 0)]["building"] = "city"
        self.assertFalse(landgrab._has_neighbor_locked("player", 2, 0))
        landgrab._map_wrap = True
        self.assertTrue(landgrab._has_neighbor_locked("player", 2, 0))
        landgrab._tiles[(-2, 0)]["owner"] = None
        landgrab._tiles[(-1, -2)]["owner"] = "player"
        self.assertFalse(landgrab._has_neighbor_locked("player", -3, 2))

    def test_wrapped_neighbors_are_symmetric_for_even_and_odd_widths(self):
        for width in (4, 5):
            for row in (-1, 0, 1):
                with self.subTest(width=width, row=row):
                    left = (-(width // 2) - row // 2, row)
                    right = (left[0] + width - 1, row)
                    self.assertIn(right, landgrab._neighbor_coordinates(*left, width, True))
                    self.assertIn(left, landgrab._neighbor_coordinates(*right, width, True))

    def test_initial_positions_consider_wrapped_neighbors(self):
        tiles = {
            (-2, 0): {"terrain": "grass"},
            (2, 0): {"terrain": "grass"},
        }
        self.assertIsNone(landgrab._start_positions(tiles, 1, 5, False))
        self.assertIsNotNone(landgrab._start_positions(tiles, 1, 5, True))

    def test_invalid_wrap_option_does_not_start_game(self):
        response = landgrab.on_landgrab_start({
            "resource_interval": 60,
            "cost_increase_rate": 10,
            "map_wrap": "true",
        })
        self.assertFalse(response["ok"])
        self.assertEqual(landgrab._phase, "waiting")

    def test_start_city_is_created_for_initial_and_late_players(self):
        landgrab.lobby.online_users.return_value = {"first": "첫 참가자"}
        with patch("landgrab.random.choices", return_value=["grass"]):
            response = landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 9,
                "map_height": 9,
            })
        self.assertTrue(response["ok"])
        self.assertTrue(landgrab._assign_player_locked("second", "나중 참가자"))
        for player in ("first", "second"):
            with self.subTest(player=player):
                start = landgrab._players[player]["start"]
                tile = landgrab._tiles[start]
                self.assertEqual(tile["building"], "city")
                self.assertEqual(landgrab._user_state_locked(player)["production"], {
                    "wood": 1, "stone": 1, "food": 3, "iron": 0, "luxury": 0,
                })

    def test_city_cost_spacing_and_nearest_city(self):
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 30,
                "map_height": 7,
            })
        for q in range(11):
            landgrab._tiles[(q, 0)]["owner"] = "player"
        landgrab._tiles[(0, 0)]["building"] = "city"
        landgrab._players["player"] = {
            "name": "참가자",
            "resources": {"wood": 5, "stone": 5, "food": 5},
            "start": (0, 0),
        }
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("player", {})),
        ):
            request.sid = "socket"
            too_close = landgrab.on_landgrab_build({"q": 4, "r": 0, "building": "city"})
            self.assertFalse(too_close["ok"])
            info = landgrab.on_landgrab_tile_info({"q": 4, "r": 0})
            city = next(building for building in info["buildings"] if building["type"] == "city")
            self.assertTrue(city["placement_error"])
            self.assertEqual(city["error"], too_close["message"])
            self.assertEqual(landgrab._players["player"]["resources"], {
                "wood": 5, "stone": 5, "food": 5,
            })
            built = landgrab.on_landgrab_build({"q": 5, "r": 0, "building": "city"})
            self.assertTrue(built["ok"])
            self.assertEqual(landgrab._players["player"]["resources"], {
                "wood": 0, "stone": 0, "food": 0,
            })
            self.assertEqual(landgrab._tile_payload(landgrab._tiles[(6, 0)], "player")["distance"], 1)
            self.assertEqual(landgrab._user_state_locked("player")["production"], {
                "wood": 2, "stone": 2, "food": 24, "iron": 0, "luxury": 0,
            })
            info = landgrab.on_landgrab_tile_info({"q": 10, "r": 0})
            self.assertEqual(info["buildings"][0]["cost"], {
                "wood": 10, "stone": 10, "food": 10,
            })
            self.assertFalse(landgrab.on_landgrab_build(
                {"q": 10, "r": 0, "building": "city"}
            )["ok"])
            landgrab._players["player"]["resources"] = {
                "wood": 10, "stone": 10, "food": 10,
            }
            self.assertTrue(landgrab.on_landgrab_build(
                {"q": 10, "r": 0, "building": "city"}
            )["ok"])
            self.assertFalse(landgrab.on_landgrab_build(
                {"q": 10, "r": 0, "building": "city"}
            )["ok"])

    def test_city_production_is_awarded_on_resource_tick(self):
        landgrab.lobby.online_users.return_value = {"player": "참가자"}
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 9,
                "map_height": 9,
            })
        calls = 0

        def sleep(_seconds):
            nonlocal calls
            calls += 1
            if calls == 2:
                landgrab._phase = "ended"

        with (
            patch("landgrab.socketio.sleep", side_effect=sleep),
            patch("landgrab.time.monotonic", return_value=60),
        ):
            landgrab._resource_loop(landgrab._game_id, 60)
        self.assertEqual(landgrab._players["player"]["resources"], {
            "wood": 6, "stone": 6, "food": 8,
        })

    def test_city_spacing_uses_wrapped_distance_and_checks_ownership(self):
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 12,
                "map_height": 7,
                "map_wrap": True,
            })
        landgrab._tiles[(-6, 0)]["owner"] = "player"
        landgrab._tiles[(-6, 0)]["building"] = "city"
        landgrab._tiles[(5, 0)]["owner"] = "player"
        landgrab._players["player"] = {
            "name": "참가자", "resources": dict(landgrab.STARTING_RESOURCES),
            "start": (-6, 0),
        }
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("player", {})),
        ):
            request.sid = "socket"
            too_close = landgrab.on_landgrab_build({"q": 5, "r": 0, "building": "city"})
            self.assertFalse(too_close["ok"])
            self.assertIn("5칸", too_close["message"])
            not_owned = landgrab.on_landgrab_build({"q": 0, "r": 0, "building": "city"})
            self.assertFalse(not_owned["ok"])

    def test_buildings_are_filtered_and_enforced_by_terrain(self):
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 15,
                "map_height": 7,
            })
        for q in range(7):
            landgrab._tiles[(q, 0)]["owner"] = "player"
        landgrab._tiles[(0, 0)]["building"] = "city"
        landgrab._tiles[(6, 0)]["terrain"] = "mountain"
        landgrab._players["player"] = {
            "name": "참가자", "resources": dict(landgrab.STARTING_RESOURCES),
            "start": (0, 0),
        }
        with (
            Flask(__name__).test_request_context(),
            patch("landgrab.lobby.get_user_by_sid", return_value=("player", {})),
            patch.dict(landgrab.BUILDINGS, {
                "city": landgrab.BUILDINGS["city"],
                "farm": landgrab.BUILDINGS["farm"],
            }, clear=True),
            patch.object(landgrab.BUILDINGS["farm"], "terrain_condition", None),
        ):
            request.sid = "socket"
            grass = landgrab.on_landgrab_tile_info({"q": 5, "r": 0})
            mountain = landgrab.on_landgrab_tile_info({"q": 6, "r": 0})
            self.assertEqual({building["type"] for building in grass["buildings"]}, {"city", "farm"})
            self.assertEqual({building["type"] for building in mountain["buildings"]}, {"farm"})
            rejected = landgrab.on_landgrab_build({"q": 6, "r": 0, "building": "city"})
            self.assertFalse(rejected["ok"])
            self.assertEqual(landgrab._players["player"]["resources"], landgrab.STARTING_RESOURCES)
            with patch.object(landgrab.BUILDINGS["farm"], "terrain_condition", set()):
                self.assertEqual(landgrab.on_landgrab_tile_info({"q": 6, "r": 0})["buildings"], [])
                self.assertFalse(landgrab.on_landgrab_build({
                    "q": 6, "r": 0, "building": "farm",
                })["ok"])
            self.assertTrue(landgrab.on_landgrab_build({
                "q": 6, "r": 0, "building": "farm",
            })["ok"])

    def test_start_city_obeys_terrain_condition(self):
        with patch("landgrab.random.choices", return_value=["grass"]):
            landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_width": 9,
                "map_height": 9,
            })
        with patch.object(landgrab.BUILDINGS["city"], "terrain_condition", {"forest"}):
            self.assertIsNone(landgrab._start_positions(landgrab._tiles, 1, 9, False))
            self.assertFalse(landgrab._assign_player_locked("player", "참가자"))

    def test_noise_generation_clusters_terrain(self):
        rng = random.Random(42)
        with patch("landgrab.random.random", side_effect=rng.random):
            tiles = landgrab._make_map(21, 21, "noise")
        self.assertEqual({tile["terrain"] for tile in tiles.values()}, set(landgrab.TERRAINS))
        neighbors = [
            (tile, tiles[(q + dq, r + dr)])
            for (q, r), tile in tiles.items()
            for dq, dr in ((1, 0), (0, 1), (1, -1))
            if (q + dq, r + dr) in tiles
        ]
        matching = sum(a["terrain"] == b["terrain"] for a, b in neighbors)
        total_weight = sum(terrain.weight for terrain in landgrab.TERRAINS.values())
        random_match = sum(
            (terrain.weight / total_weight) ** 2 for terrain in landgrab.TERRAINS.values()
        )
        self.assertGreater(matching / len(neighbors), random_match)

    def test_noise_mode_is_used_and_reported(self):
        response = landgrab.on_landgrab_start({
            "resource_interval": 60,
            "cost_increase_rate": 10,
            "map_width": 100,
            "map_height": 100,
            "map_generation": "noise",
        })
        self.assertTrue(response["ok"])
        self.assertEqual(response["map_generation"], "noise")
        self.assertEqual(len(response["tiles"]), 10000)
        self.assertEqual(landgrab._host_state_locked()["map_generation"], "noise")

    def test_invalid_generation_mode_does_not_start_game(self):
        for mode in ("unknown", None, [], True):
            with self.subTest(mode=mode):
                response = landgrab.on_landgrab_start({
                    "resource_interval": 60,
                    "cost_increase_rate": 10,
                    "map_generation": mode,
                })
                self.assertFalse(response["ok"])
                self.assertEqual(landgrab._phase, "waiting")
                self.assertEqual(landgrab._tiles, {})

    def test_real_maps_are_fixed_and_support_selected_dimensions(self):
        for mode, width, height in (
            ("world", 100, 70), ("korea", 30, 50),
            ("world", 100, 100), ("korea", 100, 100),
        ):
            with self.subTest(mode=mode):
                settings = {
                    "resource_interval": 60,
                    "cost_increase_rate": 10,
                    "map_width": width,
                    "map_height": height,
                    "map_generation": mode,
                }
                first = landgrab.on_landgrab_start(settings)
                second = landgrab.on_landgrab_start(settings)
                self.assertTrue(first["ok"])
                self.assertTrue(second["ok"])
                self.assertEqual(first["map_generation"], mode)
                self.assertEqual(len(first["tiles"]), width * height)
                self.assertEqual(first["tiles"], second["tiles"])
                terrains = {tile["terrain"] for tile in first["tiles"]}
                self.assertIn("water", terrains)
                self.assertIn("forest", terrains)
                self.assertIn("mountain", terrains)

    def test_missing_real_map_is_reported(self):
        with (
            patch("pathlib.Path.read_text", side_effect=FileNotFoundError("missing")),
            self.assertLogs("landgrab", level="ERROR"),
        ):
            result = landgrab.on_landgrab_start({
                "resource_interval": 60,
                "cost_increase_rate": 10,
                "map_generation": "world",
            })
        self.assertFalse(result["ok"])
        self.assertEqual(landgrab._phase, "waiting")

    def test_real_map_landmarks(self):
        examples = (
            ("world", 100, 70, (-180, -90, 180, 90), -140, 0, {"water", "coast"}),
            ("world", 100, 70, (-180, -90, 180, 90), -66, -3, {"forest", "jungle"}),
            ("world", 100, 70, (-180, -90, 180, 90), 85, 29, {"mountain", "rocks", "cliff", "snow"}),
            ("korea", 30, 50, (124, 32.5, 132, 43.5), 130, 37, {"water", "coast"}),
        )
        for mode, width, height, bounds, lon, lat, terrain_types in examples:
            with self.subTest(mode=mode, lon=lon, lat=lat):
                left, bottom, right, top = bounds
                column = int((lon - left) / (right - left) * width)
                row = int((top - lat) / (top - bottom) * height)
                r = row - height // 2
                q = column - width // 2 - r // 2
                self.assertIn(landgrab._make_map(width, height, mode)[(q, r)]["terrain"], terrain_types)

if __name__ == "__main__":
    unittest.main()
