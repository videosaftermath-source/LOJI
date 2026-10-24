"""Example species admins can load with one click. Each one evolves into the next rarity of its archetype."""

EVOLVE_LEVELS = {"common": 10, "rare": 20, "epic": 25}

STARTER_SPECIES = [
    # Farmeador
    ("hamster", "Hámster Currante", "🐹", "common", "farmer", "Corre en su ruedita para generar créditos."),
    ("beaver", "Castor Obrero", "🦫", "rare", "farmer", "Construye represas y cobra peaje."),
    ("ox", "Buey Titán", "🐂", "epic", "farmer", "Ara el campo entero antes del desayuno."),
    ("dragon", "Dragón Minero", "🐉", "legendary", "farmer", "Duerme sobre una montaña de oro que él mismo minó."),
    # Charlatán
    ("parrot", "Loro Chismoso", "🦜", "common", "talker", "Repite todo lo que escucha (y algo más)."),
    ("penguin", "Pingüino Parlanchín", "🐧", "rare", "talker", "Nunca se calla, ni bajo el agua."),
    ("dolphin", "Delfín DJ", "🐬", "epic", "talker", "Anima cualquier chat con sus clics."),
    ("eagle", "Águila Oradora", "🦅", "legendary", "talker", "Sus discursos se escuchan desde las nubes."),
    # Suertudo
    ("blackcat", "Gato Negro", "🐈‍⬛", "common", "lucky", "Dicen que da mala suerte. Mienten."),
    ("bunny", "Conejo de la Suerte", "🐇", "rare", "lucky", "Su pata trae suerte... y la quiere de vuelta."),
    ("fox", "Zorro Tahúr", "🦊", "epic", "lucky", "Siempre tiene un as bajo la cola."),
    ("unicorn", "Unicornio Dorado", "🦄", "legendary", "lucky", "Donde pisa sale un arcoíris de jackpots."),
    # Ahorrador
    ("squirrel", "Ardilla Ahorradora", "🐿️", "common", "saver", "Guarda bellotas para el invierno económico."),
    ("raccoon", "Mapache Regateador", "🦝", "rare", "saver", "Consigue descuentos hasta en la basura."),
    ("owl", "Búho Contable", "🦉", "epic", "saver", "Revisa cada factura con sus ojos enormes."),
    ("turtle", "Tortuga Millonaria", "🐢", "legendary", "saver", "Lenta pero con interés compuesto."),
    # Exclusivas del gacha (no son parte de ninguna cadena de evolución)
    ("wolf", "Lobo de Luna Llena", "🐺", "legendary", "talker", "Aúlla a la luna llena... y el chat entero le contesta."),
    ("shiba", "Shiba Samurái", "🐕", "epic", "earner", "Leal hasta el final: cada día vuelve a casa con unas monedas en el pañuelo."),
    ("pumpkin", "Calabaza Traviesa", "🎃", "legendary", "lucky", "Nació la noche de Halloween. ¿Truco o trato? Siempre trato... para ti."),
]
# Bundled drawings (assets/pets/<name>.png) used on the cards instead of the emoji.
ART = {"pumpkin": "pumpkin", "shiba": "shiba"}
# Exclusive species: outside every evolution chain, only obtainable from the gacha (or an admin gift).
STANDALONE = {"wolf", "pumpkin", "shiba"}

ORDER = ["common", "rare", "epic", "legendary"]


def StarterDocs(guild_id: int) -> list[dict]:
    """The example species as eco_pet_species documents, with their evolution chain."""
    ByArchetype = {}
    for Row in STARTER_SPECIES:
        if Row[0] in STANDALONE:
            continue
        ByArchetype.setdefault(Row[4], {})[Row[3]] = Row[0]
    Docs = []
    for Key, Name, Emoji, Rarity, Archetype, Description in STARTER_SPECIES:
        Next = ORDER.index(Rarity) + 1
        EvolvesTo = ByArchetype.get(Archetype, {}).get(ORDER[Next]) if Next < len(ORDER) and Key not in STANDALONE else None
        Docs.append(
            {
                "guild_id": guild_id,
                "species_id": Key.upper(),
                "name": Name,
                "emoji": Emoji,
                "rarity": Rarity,
                "archetype": Archetype,
                "description": Description,
                "image": None,
                "art": ART.get(Key),
                "exclusive": Key in STANDALONE,
                "evolves_to": EvolvesTo.upper() if EvolvesTo else None,
                "evolve_level": EVOLVE_LEVELS.get(Rarity) if EvolvesTo else None,
                "enabled": True,
            }
        )
    return Docs
