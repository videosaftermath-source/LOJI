"""
La Larga Marcha: a poker card game (score chips x mult to clear stages), LOJI themed.

Pure logic here (cards, hands, scoring, game state); the service that charges and pays is below.
A game is a plain dict so it can be saved in Mongo and resumed after a restart.
"""

import random
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations

from core.economy.activity import LocalDay
from core.economy.constants import MARCHA, USERS
from core.economy.service import EconomyError

RANKS = "23456789TJQKA"
RANK_LABELS = {"T": "10"}
SUITS = "SHDC"  # spades, hearts, diamonds, clubs
SUIT_SYMBOLS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
FACES = "JQK"
EVEN = "2468T"
ODD = "A3579"
HAND_SIZE = 8
MAX_PLAY = 5
HANDS = 4
DISCARDS = 3

# ---- run structure (like Balatro: antes of three blinds) ----
ANTES = 8
ANTE_BASE = (300, 800, 2000, 5000, 11000, 20000, 35000, 50000)  # first blind of each ante (as in Balatro)
BLINDS = (("Patrulla", 1.0, 3), ("Muralla", 1.5, 4), ("Jefe", 2.0, 5))  # (name, x base score, ◈ reward)
START_MONEY = 4
INTEREST_EVERY, INTEREST_MAX = 5, 5  # +1 ◈ per 5 held, at most +5
MONEY_PER_HAND_LEFT = 1
JOKER_SLOTS = 5
SHOP_SLOTS = 2
REROLL_BASE = 5
PLANET_PRICE = 3
PLANET_CHANCE = 0.3  # share of shop slots that offer an upgrade instead of a joker

# Hand -> (label, chips, mult, +chips per level, +mult per level)
HANDS_TABLE = {
    "straight_flush": ("Escalera de color", 100, 8, 40, 4),
    "four": ("Póker", 60, 7, 30, 3),
    "full_house": ("Full", 40, 4, 25, 2),
    "flush": ("Color", 35, 4, 15, 2),
    "straight": ("Escalera", 30, 4, 30, 3),
    "three": ("Trío", 30, 3, 20, 2),
    "two_pair": ("Doble pareja", 20, 2, 20, 1),
    "pair": ("Pareja", 10, 2, 15, 1),
    "high": ("Carta alta", 5, 1, 10, 1),
}


# ---- bosses (the third blind of each ante) ----
# id -> (name, rule shown to players, rule). Antes 1-7 draw from BOSS_POOL at random; LOJI is always last.
BOSSES = {
    "nailoong": ("Nailoong", "Se comió tus corazones: las cartas ♥ no puntúan", {"debuff_suit": "H"}),
    "calaveras": ("El Coronado de Calaveras", "Las figuras (J, Q, K) no puntúan", {"debuff_faces": True}),
    "iracundo": ("El Iracundo", "Solo tienes 1 descarte", {"discards": 1}),
    "recaudador": ("El Recaudador", "Cada mano que juegas te cobra ◈1", {"hand_cost": 1}),
    "koala": ("El Koala", "Siesta: tu primera mano no cuenta", {"first_hand_zero": True}),
    "heisenberg": ("Heisenberg", "Say my name: si juegas tu jugada más usada, pierdes todos tus ◈", {"steal_on_favorite": True}),
    "griton": ("Gunther Fehlinger", "Debes jugar exactamente 5 cartas", {"exact_cards": 5}),
    "corvus": ("Corvus", "Cada jugada que hagas baja 1 nivel", {"level_down": True}),
    "loji": ("LOJI", "En cada mano anula uno de tus comodines al azar", {"seal_joker": True}),
}
FINAL_BOSS = "loji"
BOSS_POOL = [B for B in BOSSES if B != FINAL_BOSS]


def BossOrder(rng: random.Random) -> list[str]:
    """A boss per ante: the pool shuffled (repeating once it runs out), then LOJI."""
    Order: list[str] = []
    while len(Order) < ANTES - 1:
        Pool = BOSS_POOL[:]
        rng.shuffle(Pool)
        Order += Pool
    return Order[: ANTES - 1] + [FINAL_BOSS]


def BossOf(game: dict, ante: int | None = None) -> str:
    return game["bosses"][game["ante"] if ante is None else ante]


def Rule(game: dict) -> dict:
    """The current boss rule (empty outside boss blinds)."""
    if game.get("blind") != len(BLINDS) - 1 or "bosses" not in game:
        return {}
    return BOSSES[BossOf(game)][2]


def Favorite(game: dict) -> str | None:
    """The hand type played most this run (ties: none)."""
    Counts = game.get("played", {})
    if not Counts:
        return None
    Top = max(Counts.values())
    Best = [H for H, N in Counts.items() if N == Top]
    return Best[0] if len(Best) == 1 else None


def Debuffed(card: str, rule: dict) -> bool:
    return card[1] == rule.get("debuff_suit") or (rule.get("debuff_faces", False) and card[0] in FACES)


def Target(ante: int, blind: int) -> int:
    return int(ANTE_BASE[ante] * BLINDS[blind][1])


def Rank(card: str) -> int:
    return RANKS.index(card[0])


def Label(card: str) -> str:
    return RANK_LABELS.get(card[0], card[0]) + SUIT_SYMBOLS[card[1]]


def CardChips(card: str) -> int:
    R = card[0]
    if R == "A":
        return 11
    if R in "TJQK":
        return 10
    return int(R)


def NewDeck(rng: random.Random) -> list[str]:
    Deck = [R + S for R in RANKS for S in SUITS]
    rng.shuffle(Deck)
    return Deck


def IsStraight(ranks: list[int]) -> bool:
    Unique = sorted(set(ranks))
    if len(Unique) != 5:
        return False
    return Unique[-1] - Unique[0] == 4 or Unique == [0, 1, 2, 3, 12]  # A-2-3-4-5


def Evaluate(cards: list[str]) -> tuple[str, list[str]]:
    """(hand type, scoring cards) for 1 to 5 cards. Straights and flushes need all 5."""
    Ranks = [Rank(C) for C in cards]
    Counts = Counter(Ranks)
    Groups = sorted(Counts.items(), key=lambda G: (G[1], G[0]), reverse=True)
    Flush = len(cards) == 5 and len({C[1] for C in cards}) == 1
    Straight = len(cards) == 5 and IsStraight(Ranks)
    if Flush and Straight:
        return "straight_flush", list(cards)
    if Groups[0][1] == 4:
        return "four", [C for C in cards if Rank(C) == Groups[0][0]]
    if Groups[0][1] == 3 and len(Groups) > 1 and Groups[1][1] >= 2:
        return "full_house", list(cards)
    if Flush:
        return "flush", list(cards)
    if Straight:
        return "straight", list(cards)
    if Groups[0][1] == 3:
        return "three", [C for C in cards if Rank(C) == Groups[0][0]]
    if Groups[0][1] == 2 and len(Groups) > 1 and Groups[1][1] == 2:
        Pairs = {Groups[0][0], Groups[1][0]}
        return "two_pair", [C for C in cards if Rank(C) in Pairs]
    if Groups[0][1] == 2:
        return "pair", [C for C in cards if Rank(C) == Groups[0][0]]
    return "high", [max(cards, key=Rank)]


def Contains(cards: list[str], hand: str) -> set[str]:
    """Every hand type inside the played cards (a full house contains a pair and a trio...)."""
    Counts = sorted(Counter(Rank(C) for C in cards).values(), reverse=True)
    Inside = {hand, "high"}
    if Counts[0] >= 2:
        Inside.add("pair")
    if Counts[0] >= 3:
        Inside.add("three")
    if Counts[0] >= 4:
        Inside.add("four")
    if len(Counts) > 1 and Counts[0] >= 2 and Counts[1] >= 2:
        Inside.add("two_pair")
    if hand == "straight_flush":
        Inside |= {"straight", "flush"}
    return Inside


# ---------------- jokers ----------------
# Each joker: name, emoji, rarity, price, text, and its effect. "card" effects run for every
# scoring card (left to right); "hand" effects run once afterwards, joker by joker.

def _Suit(suit):
    return lambda c, ctx: {"mult": 3} if c[1] == suit else None


def _IfContains(hand, **bonus):
    return lambda ctx: bonus if hand in ctx["contains"] else None


JOKERS = {
    "camarada": ("Camarada", "🤝", "common", 4, "+4 multi", "hand", lambda ctx: {"mult": 4}),
    "corazon": ("Corazón de Acero", "❤️", "common", 5, "Cada ♥ que puntúa: +3 multi", "card", _Suit("H")),
    "diamante": ("Diamante Frío", "💎", "common", 5, "Cada ♦ que puntúa: +3 multi", "card", _Suit("D")),
    "pala": ("Pala del Obrero", "♠️", "common", 5, "Cada ♠ que puntúa: +3 multi", "card", _Suit("S")),
    "trebol": ("Trébol de Hierro", "☘️", "common", 5, "Cada ♣ que puntúa: +3 multi", "card", _Suit("C")),
    "doble": ("Doble Señal", "📡", "common", 4, "+8 multi si la mano contiene una pareja", "hand", _IfContains("pair", mult=8)),
    "trinidad": ("Trinidad", "🔺", "common", 4, "+12 multi si contiene un trío", "hand", _IfContains("three", mult=12)),
    "consenso": ("Consenso", "🗳️", "common", 4, "+10 multi si contiene doble pareja", "hand", _IfContains("two_pair", mult=10)),
    "recta": ("Marcha Recta", "🚶", "common", 4, "+12 multi si contiene escalera", "hand", _IfContains("straight", mult=12)),
    "bandera": ("Bandera Única", "🚩", "common", 4, "+10 multi si contiene color", "hand", _IfContains("flush", mult=10)),
    "archivista": ("Archivista", "🗂️", "common", 4, "+50 fichas si contiene una pareja", "hand", _IfContains("pair", chips=50)),
    "antena": ("Antena", "🗼", "common", 4, "+100 fichas si contiene escalera", "hand", _IfContains("straight", chips=100)),
    "media": ("Media Ración", "🍙", "common", 5, "+20 multi si juegas 3 cartas o menos", "hand",
              lambda ctx: {"mult": 20} if len(ctx["played"]) <= 3 else None),
    "escaner": ("Escáner Facial", "👁️", "common", 5, "Cada J, Q o K que puntúa: +30 fichas", "card",
                lambda c, ctx: {"chips": 30} if c[0] in FACES else None),
    "par": ("Orden Par", "⚖️", "common", 4, "Cada 2, 4, 6, 8 o 10 que puntúa: +4 multi", "card",
            lambda c, ctx: {"mult": 4} if c[0] in EVEN else None),
    "impar": ("Caos Impar", "🌀", "common", 4, "Cada A, 3, 5, 7 o 9 que puntúa: +31 fichas", "card",
              lambda c, ctx: {"chips": 31} if c[0] in ODD else None),
    "abstracto": ("Arte Abstracto", "🎨", "uncommon", 6, "+3 multi por cada comodín que tengas", "hand",
                  lambda ctx: {"mult": 3 * ctx["jokers"]}),
    "banquero": ("Banquero", "🏦", "uncommon", 6, "+2 fichas por cada ◈ que tengas", "hand",
                 lambda ctx: {"chips": 2 * ctx["money"]}),
    "cumbre": ("Cumbre", "🏔️", "uncommon", 6, "+15 multi si no te quedan descartes", "hand",
               lambda ctx: {"mult": 15} if ctx["discards"] == 0 else None),
    "colmena": ("Mente Colmena", "🐝", "uncommon", 7, "×2 multi si contiene una pareja", "hand", _IfContains("pair", xmult=2)),
    "tribu": ("La Tribu", "🏮", "rare", 8, "×2 multi si contiene color", "hand", _IfContains("flush", xmult=2)),
    "trio": ("El Trío", "🎎", "rare", 8, "×3 multi si contiene un trío", "hand", _IfContains("three", xmult=3)),
    "orden": ("El Orden", "📜", "rare", 8, "×3 multi si contiene escalera", "hand", _IfContains("straight", xmult=3)),
    "ojo": ("Ojo de LOJI", "🔴", "rare", 9, "×2 multi siempre", "hand", lambda ctx: {"xmult": 2}),
}
JOKER_RARITY_WEIGHTS = {"common": 70, "uncommon": 25, "rare": 5}
JOKER_RARITY_LABELS = {"common": "Común", "uncommon": "Poco común", "rare": "Raro"}


def JokerInfo(joker_id: str) -> dict:
    Name, Emoji, Rarity, Price, Text, Kind, _ = JOKERS[joker_id]
    return {"id": joker_id, "name": Name, "emoji": Emoji, "rarity": Rarity, "price": Price, "text": Text}


def SellValue(joker_id: str) -> int:
    return max(1, JOKERS[joker_id][3] // 2)


def HandBase(hand: str, level: int) -> tuple[int, int]:
    _, Chips, Mult, PlusChips, PlusMult = HANDS_TABLE[hand]
    return Chips + PlusChips * (level - 1), Mult + PlusMult * (level - 1)


def Score(cards: list[str], game: dict | None = None) -> dict:
    """Chips, mult and total for a played hand, with the game's hand levels and jokers."""
    Game = game or {}
    Rule_ = Rule(Game)
    Hand, Scoring = Evaluate(cards)
    Level = Game.get("levels", {}).get(Hand, 1)
    Chips, Mult = HandBase(Hand, Level)
    Sealed = Game.get("sealed") if Rule_.get("seal_joker") else None
    Jokers = [J for i, J in enumerate(Game.get("jokers", [])) if i != Sealed]
    Ctx = {
        "played": cards, "scoring": Scoring, "contains": Contains(cards, Hand),
        "jokers": len(Jokers), "money": Game.get("money", 0), "discards": Game.get("discards", DISCARDS),
    }
    Triggers = []
    for Card in Scoring:
        if Debuffed(Card, Rule_):
            continue
        Chips += CardChips(Card)
        for J in Jokers:
            if JOKERS[J][5] == "card":
                Effect = JOKERS[J][6](Card, Ctx)
                if Effect:
                    Chips += Effect.get("chips", 0)
                    Mult += Effect.get("mult", 0)
                    Triggers.append(J)
    for J in Jokers:
        if JOKERS[J][5] == "hand":
            Effect = JOKERS[J][6](Ctx)
            if Effect:
                Chips += Effect.get("chips", 0)
                Mult += Effect.get("mult", 0)
                Mult *= Effect.get("xmult", 1)
                Triggers.append(J)
    Mult = round(Mult, 2)
    Siesta = Rule_.get("first_hand_zero", False) and Game.get("hands") == HANDS
    return {
        "hand": Hand, "label": HANDS_TABLE[Hand][0], "level": Level, "scoring": Scoring,
        "chips": Chips, "mult": Mult, "total": 0 if Siesta else int(Chips * Mult),
        "triggered": list(dict.fromkeys(Triggers)), "siesta": Siesta,
        "debuffed": [C for C in Scoring if Debuffed(C, Rule_)],
    }


def BestPlay(hand: list[str], game: dict | None = None) -> list[str]:
    """The highest-scoring set of up to 5 cards (used by the simulator)."""
    Best, BestScore = [], -1
    Exact = Rule(game or {}).get("exact_cards")
    for Size in [Exact] if Exact else range(1, MAX_PLAY + 1):
        for Combo in combinations(hand, Size):
            S = Score(list(Combo), game)["total"]
            if S > BestScore:
                Best, BestScore = list(Combo), S
    return Best


# ---------------- game state ----------------


def NewBlind(game: dict, rng: random.Random):
    Deck = NewDeck(rng)
    game.update(
        deck=Deck[HAND_SIZE:], hand=Deck[:HAND_SIZE], score=0, hands=HANDS, discards=DISCARDS,
        last=None, state="playing", shop=[], earned=None, sealed=None,
    )
    Rule_ = Rule(game)
    if "discards" in Rule_:
        game["discards"] = Rule_["discards"]
    Seal(game, rng)


def Seal(game: dict, rng: random.Random):
    """LOJI's rule: picks the joker that won't work for the next hand."""
    if Rule(game).get("seal_joker") and game["jokers"]:
        game["sealed"] = rng.randrange(len(game["jokers"]))
    else:
        game["sealed"] = None


def NewGame(bet: int, rng: random.Random) -> dict:
    Game = {
        "bet": bet, "ante": 0, "blind": 0, "cleared": 0, "money": START_MONEY, "jokers": [], "levels": {},
        "bosses": BossOrder(rng),
    }
    NewBlind(Game, rng)
    return Game


def Draw(game: dict):
    while len(game["hand"]) < HAND_SIZE and game["deck"]:
        game["hand"].append(game["deck"].pop(0))


def Take(game: dict, cards: list[str]) -> list[str]:
    if not 1 <= len(cards) <= MAX_PLAY or len(set(cards)) != len(cards) or any(C not in game["hand"] for C in cards):
        raise ValueError(f"Elige de 1 a {MAX_PLAY} cartas de tu mano.")
    for C in cards:
        game["hand"].remove(C)
    return cards


def Earnings(game: dict) -> dict:
    """◈ for beating the current blind: reward + unused hands + interest."""
    Reward = BLINDS[game["blind"]][2]
    Hands = game["hands"] * MONEY_PER_HAND_LEFT
    Interest = min(INTEREST_MAX, game["money"] // INTEREST_EVERY)
    return {"reward": Reward, "hands": Hands, "interest": Interest, "total": Reward + Hands + Interest}


def Play(game: dict, cards: list[str], rng: random.Random | None = None) -> dict:
    """Plays a hand. When the blind is beaten: pays ◈ and moves to the shop (or the ante choice)."""
    if game["state"] != "playing" or game["hands"] <= 0:
        raise ValueError("No puedes jugar ahora.")
    Rng = rng or random.Random()
    Rule_ = Rule(game)
    if Rule_.get("exact_cards") and len(cards) != Rule_["exact_cards"]:
        raise ValueError(f"El jefe exige jugar exactamente {Rule_['exact_cards']} cartas.")
    Result = Score(cards, game)
    Take(game, cards)
    game["score"] += Result["total"]
    game["hands"] -= 1
    game["last"] = {**Result, "cards": cards}
    Cost = Rule_.get("hand_cost", 0)
    if Cost:
        game["money"] = max(0, game["money"] - Cost)
    if Rule_.get("steal_on_favorite") and Result["hand"] == Favorite(game):
        game["money"] = 0
        game["last"]["robbed"] = True
    if Rule_.get("level_down") and game["levels"].get(Result["hand"], 1) > 1:
        game["levels"][Result["hand"]] -= 1
    game.setdefault("played", {})
    game["played"][Result["hand"]] = game["played"].get(Result["hand"], 0) + 1
    if game["score"] >= Target(game["ante"], game["blind"]):
        Earned = Earnings(game)
        game["money"] += Earned["total"]
        game["earned"] = Earned
        if game["blind"] == len(BLINDS) - 1:
            game["cleared"] = game["ante"] + 1
            game["state"] = "won" if game["cleared"] == ANTES else "ante_cleared"
        else:
            game["state"] = "shop"
        if game["state"] in ("shop", "ante_cleared"):
            game["shop"] = NewShop(game, Rng)
            game["reroll"] = REROLL_BASE
    elif game["hands"] == 0:
        game["state"] = "failed"
    else:
        Draw(game)
        Seal(game, Rng)
    return Result


def Discard(game: dict, cards: list[str]):
    if game["state"] != "playing" or game["discards"] <= 0:
        raise ValueError("No te quedan descartes.")
    Take(game, cards)
    game["discards"] -= 1
    game["last"] = None
    Draw(game)


# ---------------- shop ----------------


def Offer(game: dict, rng: random.Random) -> dict:
    if rng.random() < PLANET_CHANCE:
        Hand = rng.choice(list(HANDS_TABLE))
        return {"type": "planet", "hand": Hand, "price": PLANET_PRICE}
    Owned = set(game["jokers"])
    Rarity = rng.choices(list(JOKER_RARITY_WEIGHTS), list(JOKER_RARITY_WEIGHTS.values()))[0]
    Pool = [J for J, D in JOKERS.items() if D[2] == Rarity and J not in Owned] or [J for J in JOKERS if J not in Owned]
    J = rng.choice(Pool)
    return {"type": "joker", "id": J, "price": JOKERS[J][3]}


def NewShop(game: dict, rng: random.Random) -> list[dict]:
    return [Offer(game, rng) for _ in range(SHOP_SLOTS)]


def InShop(game: dict):
    if game["state"] != "shop":
        raise ValueError("La tienda está cerrada.")


def Buy(game: dict, slot: int) -> dict:
    InShop(game)
    if not 0 <= slot < len(game["shop"]) or game["shop"][slot] is None:
        raise ValueError("Eso ya no está a la venta.")
    Item = game["shop"][slot]
    if game["money"] < Item["price"]:
        raise ValueError(f"No te alcanza: cuesta ◈{Item['price']} y tienes ◈{game['money']}.")
    if Item["type"] == "joker":
        if len(game["jokers"]) >= JOKER_SLOTS:
            raise ValueError(f"Ya tienes {JOKER_SLOTS} comodines. Vende uno primero.")
        game["jokers"].append(Item["id"])
    else:
        game["levels"][Item["hand"]] = game["levels"].get(Item["hand"], 1) + 1
    game["money"] -= Item["price"]
    game["shop"][slot] = None
    return Item


def Sell(game: dict, index: int) -> int:
    InShop(game)
    if not 0 <= index < len(game["jokers"]):
        raise ValueError("Ese comodín no existe.")
    Value = SellValue(game["jokers"].pop(index))
    game["money"] += Value
    return Value


def Reroll(game: dict, rng: random.Random):
    InShop(game)
    if game["money"] < game["reroll"]:
        raise ValueError(f"Renovar cuesta ◈{game['reroll']} y tienes ◈{game['money']}.")
    game["money"] -= game["reroll"]
    game["reroll"] += 1
    game["shop"] = NewShop(game, rng)


def EnterShop(game: dict):
    """After beating a boss and choosing to keep marching."""
    if game["state"] != "ante_cleared":
        raise ValueError("No puedes seguir ahora.")
    game["state"] = "shop"


def NextBlind(game: dict, rng: random.Random):
    InShop(game)
    if game["blind"] == len(BLINDS) - 1:
        game["ante"] += 1
        game["blind"] = 0
    else:
        game["blind"] += 1
    NewBlind(game, rng)


# ---------------- prizes ----------------

GAME = "marcha"  # key in config["casino"] and in the casino ledger refs
# What cashing out after beating each ante's boss pays (x bet). With the boss rules, a simple
# simulated player beats antes 1-6 about 95%, 94%, 80%, 36%, 9% and 2% of the time.
# Deep antes pay a lot because they need a good joker build; the daily limit and bet cap keep it safe.
LADDER = (0.6, 0.8, 1.1, 2, 5, 12, 30, 75)


def Prize(game: dict) -> int:
    """What cashing out right now pays (0 before beating the first boss)."""
    return int(game["bet"] * LADDER[game["cleared"] - 1]) if game["cleared"] else 0


# ---------------- service ----------------

class MarchaError(EconomyError):
    """Message is safe to show to users."""


class Marcha:
    """Charges the entry, keeps the game saved (so it survives restarts) and pays."""

    def __init__(self, db, economy, casino):
        self.games = db[MARCHA]
        self.users = db[USERS]
        self.economy = economy
        self.casino = casino
        self.rng = random.SystemRandom()

    async def Setup(self):
        await self.games.create_index([("guild_id", 1), ("user_id", 1)], unique=True)

    async def Active(self, guild_id: int, user_id: int) -> dict | None:
        Doc = await self.games.find_one({"guild_id": guild_id, "user_id": user_id})
        return Doc["game"] if Doc else None

    async def UseDailySlot(self, guild_id: int, user_id: int, config: dict) -> int:
        """Counts one game for today. Raises MarchaError at the limit. Returns games left."""
        Limit = config["casino"][GAME]["daily_limit"]
        Today = LocalDay(datetime.now(timezone.utc), config["activity"]["utc_offset"]).isoformat()
        await self.economy.Account(guild_id, user_id)
        Key = {"guild_id": guild_id, "user_id": user_id}
        await self.users.update_one({**Key, "marcha.day": {"$ne": Today}}, {"$set": {"marcha.day": Today, "marcha.count": 0}})
        Doc = await self.users.find_one_and_update(
            {**Key, "marcha.day": Today, "marcha.count": {"$lt": Limit}}, {"$inc": {"marcha.count": 1}}
        )
        if Doc is None:
            raise MarchaError(f"Ya marchaste {Limit} veces hoy. Vuelve mañana.")
        return Limit - int(Doc["marcha"]["count"]) - 1

    async def GiveBackSlot(self, guild_id: int, user_id: int):
        await self.users.update_one({"guild_id": guild_id, "user_id": user_id}, {"$inc": {"marcha.count": -1}})

    async def Start(self, member, raw_bet: str, config: dict) -> tuple[dict, int]:
        """New game (charges the bet). Returns (game, games left today)."""
        Guild = member.guild.id
        if await self.Active(Guild, member.id):
            raise MarchaError("Ya tienes una marcha en curso: usa `/casino marcha` sin cantidad para seguirla.")
        Left = await self.UseDailySlot(Guild, member.id, config)
        try:
            Bet, _, _ = await self.casino.Start(member, GAME, raw_bet, config)
        except Exception:
            await self.GiveBackSlot(Guild, member.id)
            raise
        Game = NewGame(Bet, self.rng)
        await self.games.insert_one({"guild_id": Guild, "user_id": member.id, "game": Game, "updated_at": datetime.now(timezone.utc)})
        return Game, Left

    async def Save(self, guild_id: int, user_id: int, game: dict):
        await self.games.update_one(
            {"guild_id": guild_id, "user_id": user_id}, {"$set": {"game": game, "updated_at": datetime.now(timezone.utc)}}
        )

    async def Finish(self, member, game: dict, cash_out: bool) -> int:
        """Ends the game (paying the prize if cashing out). Paid once: the saved game is deleted first."""
        Deleted = await self.games.delete_one({"guild_id": member.guild.id, "user_id": member.id})
        if not Deleted.deleted_count:
            return 0
        Amount = Prize(game) if cash_out else 0
        await self.casino.Pay(member, GAME, Amount)
        return Amount
