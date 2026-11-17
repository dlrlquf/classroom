class Building:
    type_id = ""
    name = ""
    description = ""
    production_bonus = {}
    is_distance_origin = False
    terrain_condition = None
    cost = {}
    grants_movement = False

    def allows_terrain(self, terrain):
        return self.terrain_condition is None or terrain in self.terrain_condition

    def construction_cost(self, owned_buildings):
        raise NotImplementedError

    def placement_error(self, position, owned_buildings):
        return None

    def adjust_purchase_cost(self, cost, distance):
        return cost


class City(Building):
    type_id = "city"
    name = "도시"
    description = "주기마다 식량, 목재, 석재를 각각 1씩 생산합니다."
    production_bonus = {"wood": 1, "stone": 1, "food": 1}
    is_distance_origin = True
    terrain_condition = {
        "plains", "grass", "wetland", "desert", "snow", "jungle",
        "hill", "shrub", "forest", "rocks",
    }
    cost = {"wood": 5, "stone": 5, "food": 5}

    def construction_cost(self, owned_buildings):
        count = sum(building.type_id == self.type_id for _, building in owned_buildings)
        return {resource: amount * count for resource, amount in self.cost.items()}

    def placement_error(self, position, owned_buildings):
        from . import _hex_distance

        if any(
            _hex_distance(position, existing) < 5
            for existing, building in owned_buildings
            if building.type_id == self.type_id
        ):
            return "내 도시와 5칸 이상 떨어져야 합니다."
        return None


class Farm(Building):
    type_id = "farm"
    name = "농장"
    production_bonus = {"food": 2}
    terrain_condition = {"plains", "grass", "wetland"}
    cost = {"wood": 3, "stone":3}

    def construction_cost(self, owned_buildings):
        return self.cost


class Mine(Building):
    type_id = "mine"
    name = "광산"
    production_bonus = {"stone": 2}
    terrain_condition = {"hill", "rocks", "mountain", "cliff"}
    cost = {"wood": 5, "food":2}

    def construction_cost(self, owned_buildings):
        return self.cost


class LoggingSite(Building):
    type_id = "logging_site"
    name = "벌목장"
    production_bonus = {"wood": 2}
    terrain_condition = {"hill", "shrub", "forest", "jungle"}
    cost = {"stone": 3, "food": 3}

    def construction_cost(self, owned_buildings):
        return self.cost


class Port(Building):
    type_id = "port"
    name = "항구"
    description = "식량을 2 생산하고 해당 타일의 통행을 허용합니다."
    production_bonus = {"food": 2}
    terrain_condition = {"coast", "river", "lake"}
    cost = {"wood": 5, "stone": 3}
    grants_movement = True

    def construction_cost(self, owned_buildings):
        return self.cost


BUILDINGS = {
    City.type_id: City(),
    Farm.type_id: Farm(),
    Mine.type_id: Mine(),
    LoggingSite.type_id: LoggingSite(),
    Port.type_id: Port(),
}
