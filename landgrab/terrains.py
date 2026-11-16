from typing import Dict, Optional


class Terrain:
    type_id = ""
    name = ""
    color = ""
    weight = 0
    production: Dict[str, int] = {}
    cost: Optional[Dict[str, int]] = None
    startable = False


class Water(Terrain):
    type_id = "water"
    name = "물"
    color = "#60a5fa"
    weight = 14


class Grass(Terrain):
    type_id = "grass"
    name = "초원"
    color = "#86efac"
    weight = 30
    production = {"food": 2}
    cost = {"wood": 2, "food": 2}
    startable = True


class Desert(Terrain):
    type_id = "desert"
    name = "사막"
    color = "#fcd34d"
    weight = 18
    production = {"food": 1}
    cost = {"wood": 1, "food": 1}
    startable = True


class Forest(Terrain):
    type_id = "forest"
    name = "숲"
    color = "#4ade80"
    weight = 24
    production = {"wood": 2, "food": 1}
    cost = {"wood": 3, "food": 1}
    startable = True


class Mountain(Terrain):
    type_id = "mountain"
    name = "산"
    color = "#a8a29e"
    weight = 14
    production = {"stone": 2}
    cost = {"wood": 2, "food": 2}


TERRAINS = {
    Water.type_id: Water(),
    Grass.type_id: Grass(),
    Desert.type_id: Desert(),
    Forest.type_id: Forest(),
    Mountain.type_id: Mountain(),
}
STARTING_TERRAINS = tuple(
    terrain for terrain, settings in TERRAINS.items() if settings.startable
)
