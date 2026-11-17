from typing import Dict


class Terrain:
    type_id = ""
    code = ""
    name = ""
    color = ""
    weight = 0
    production: Dict[str, int] = {}
    cost: Dict[str, int] = {}
    startable = False
    movable = True


class Water(Terrain):
    type_id, code, name, color, weight = "water", "w", "심해", "#1d4ed8", 5
    cost = {"wood": 2, "food": 1}
    movable = False


class Coast(Terrain):
    type_id, code, name, color, weight = "coast", "c", "연안", "#38bdf8", 5
    production = {"food": 1}
    cost = {"wood": 2, "food": 1}
    movable = False


class River(Terrain):
    type_id, code, name, color, weight = "river", "r", "강", "#7dd3fc", 2
    production = {"food": 1}
    cost = {"wood": 2, "food": 1}


class Lake(Terrain):
    type_id, code, name, color, weight = "lake", "l", "호수", "#60a5fa", 2
    production = {"food": 2}
    cost = {"wood": 2, "food": 1}


class Plains(Terrain):
    type_id, code, name, color, weight = "plains", "p", "평야", "#bef264", 12
    production = {"food": 3}
    cost = {"wood": 2, "food": 2}
    startable = True


class Grass(Terrain):
    type_id, code, name, color, weight = "grass", "g", "초원", "#86efac", 14
    production = {"food": 2}
    cost = {"wood": 2, "food": 2}
    startable = True


class Wetland(Terrain):
    type_id, code, name, color, weight = "wetland", "t", "습지", "#65a985", 4
    production = {"food": 2}
    cost = {"wood": 2, "food": 2}


class Desert(Terrain):
    type_id, code, name, color, weight = "desert", "d", "사막", "#fcd34d", 8
    production = {"luxury": 1}
    cost = {"wood": 1, "food": 1}
    startable = True


class Snow(Terrain):
    type_id, code, name, color, weight = "snow", "n", "설원", "#e2e8f0", 5
    production = {"luxury": 1}
    cost = {"wood": 2, "food": 1}


class Jungle(Terrain):
    type_id, code, name, color, weight = "jungle", "j", "정글", "#15803d", 5
    production = {"wood": 1, "luxury": 1}
    cost = {"wood": 2, "food": 2}


class Hill(Terrain):
    type_id, code, name, color, weight = "hill", "h", "언덕", "#a3bd70", 5
    production = {"wood": 1, "stone": 1}
    cost = {"wood": 2, "food": 2}


class Shrub(Terrain):
    type_id, code, name, color, weight = "shrub", "b", "수풀", "#84cc16", 6
    production = {"wood": 2}
    cost = {"wood": 2, "food": 1}


class Forest(Terrain):
    type_id, code, name, color, weight = "forest", "f", "숲", "#4ade80", 10
    production = {"wood": 2, "food": 1}
    cost = {"wood": 3, "food": 1}
    startable = True


class Rocks(Terrain):
    type_id, code, name, color, weight = "rocks", "k", "암석", "#a8a29e", 6
    production = {"stone": 2, "iron": 1}
    cost = {"wood": 2, "food": 2}


class Mountain(Terrain):
    type_id, code, name, color, weight = "mountain", "m", "산", "#78716c", 7
    production = {"stone": 3, "iron": 1}
    cost = {"wood": 2, "food": 2}
    movable = False


class Cliff(Terrain):
    type_id, code, name, color, weight = "cliff", "v", "절벽", "#57534e", 4
    production = {"stone": 2, "iron": 2}
    cost = {"wood": 2, "food": 2}
    movable = False


TERRAINS = {
    terrain.type_id: terrain()
    for terrain in (
        Water, Coast, River, Lake, Plains, Grass, Wetland, Desert, Snow, Jungle,
        Hill, Shrub, Forest, Rocks, Mountain, Cliff,
    )
}
STARTING_TERRAINS = tuple(
    terrain for terrain, settings in TERRAINS.items() if settings.startable
)
