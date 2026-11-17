class Resource:
    type_id = ""
    name = ""
    icon = "◈"
    starting_amount = 0


class Wood(Resource):
    type_id = "wood"
    name = "목재"
    icon = "🪵"
    starting_amount = 5


class Stone(Resource):
    type_id = "stone"
    name = "석재"
    icon = "🪨"
    starting_amount = 5


class Food(Resource):
    type_id = "food"
    name = "식량"
    icon = "🌾"
    starting_amount = 5


class Iron(Resource):
    type_id = "iron"
    name = "철"
    icon = "⛓️"


class Luxury(Resource):
    type_id = "luxury"
    name = "사치품"
    icon = "💎"


RESOURCES = {
    Wood.type_id: Wood(),
    Stone.type_id: Stone(),
    Food.type_id: Food(),
    Iron.type_id: Iron(),
    Luxury.type_id: Luxury(),
}
RESOURCE_NAMES = {key: resource.name for key, resource in RESOURCES.items()}
RESOURCE_ICONS = {key: resource.icon for key, resource in RESOURCES.items()}
STARTING_RESOURCES = {key: resource.starting_amount for key, resource in RESOURCES.items()}
