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
HAND_SIZE = 8
MAX_PLAY = 5
HANDS = 4
DISCARDS = 3
# Score needed to clear each stage.
TARGETS = (450, 650, 900)

# Hand -> (label, chips, mult). Scoring cards add their own chips on top.
HANDS_TABLE = {
    "straight_flush": ("Escalera de color", 100, 8),
    "four": ("Póker", 60, 7),
    "full_house": ("Full", 40, 4),
    "flush": ("Color", 35, 4),
    "straight": ("Escalera", 30, 4),
    "three": ("Trío", 30, 3),
    "two_pair": ("Doble pareja", 20, 2),
    "pair": ("Pareja", 10, 2),
    "high": ("Carta alta", 5, 1),
}


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


def Score(cards: list[str]) -> dict:
    """Chips, mult and total for a played hand."""
    Hand, Scoring = Evaluate(cards)
    LabelText, Chips, Mult = HANDS_TABLE[Hand]
    Chips += sum(CardChips(C) for C in Scoring)
    return {"hand": Hand, "label": LabelText, "scoring": Scoring, "chips": Chips, "mult": Mult, "total": Chips * Mult}


def BestPlay(hand: list[str]) -> list[str]:
    """The highest-scoring set of up to 5 cards (used by the simulator and the hint)."""
    Best, BestScore = [], -1
    for Size in range(1, MAX_PLAY + 1):
        for Combo in combinations(hand, Size):
            S = Score(list(Combo))["total"]
            if S > BestScore:
                Best, BestScore = list(Combo), S
    return Best


# ---------------- game state ----------------


def NewStage(game: dict, rng: random.Random):
    Deck = NewDeck(rng)
    game.update(
        deck=Deck[HAND_SIZE:],
        hand=Deck[:HAND_SIZE],
        score=0,
        hands=HANDS,
        discards=DISCARDS,
        last=None,
        state="playing",
    )


def NewGame(bet: int, rng: random.Random) -> dict:
    Game = {"bet": bet, "stage": 0, "cleared": 0}
    NewStage(Game, rng)
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


def Play(game: dict, cards: list[str]) -> dict:
    """Plays a hand. Moves the game to 'cleared', 'failed' or keeps 'playing'."""
    if game["state"] != "playing" or game["hands"] <= 0:
        raise ValueError("No puedes jugar ahora.")
    Result = Score(Take(game, cards))
    game["score"] += Result["total"]
    game["hands"] -= 1
    game["last"] = {**Result, "cards": cards}
    if game["score"] >= TARGETS[game["stage"]]:
        game["cleared"] = game["stage"] + 1
        game["state"] = "won" if game["cleared"] == len(TARGETS) else "cleared"
    elif game["hands"] == 0:
        game["state"] = "failed"
    else:
        Draw(game)
    return Result


def Discard(game: dict, cards: list[str]):
    if game["state"] != "playing" or game["discards"] <= 0:
        raise ValueError("No te quedan descartes.")
    Take(game, cards)
    game["discards"] -= 1
    game["last"] = None
    Draw(game)


def NextStage(game: dict, rng: random.Random):
    if game["state"] != "cleared":
        raise ValueError("Todavía no superaste esta etapa.")
    game["stage"] += 1
    NewStage(game, rng)


# ---------------- prizes ----------------

GAME = "marcha"  # key in config["casino"] and in the casino ledger refs
# What cashing out after each stage pays (x bet). Calibrated by simulating thousands of games with
# a simple player: it gets back ~90-93% whatever it does, so the house keeps a little.
LADDER = (1.0, 1.3, 3.3)


def Prize(game: dict) -> int:
    """What cashing out right now pays (0 before clearing a stage)."""
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
