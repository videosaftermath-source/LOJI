"""
Casino games: pure rules (testable) plus the bet/payout service.

House edge: every game is tuned so that, on average, it returns (1 - edge) of what is bet.
Luck from a Suertudo pet lowers the edge proportionally (edge * (1 - luck)) and can never
turn it in the player's favor. All money moves through the economy service (kinds bet/payout).
"""

import math
import random
import re
import time
from dataclasses import dataclass, field
from itertools import product

from core.economy.constants import BET, PAYOUT
from core.economy.service import EconomyError, EconomyService

SUITS = "♠♥♦♣"
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
DECKS = 6
CRASH_GROWTH = 0.12  # multiplier = e^(growth * seconds): 2x at ~5.8s, 10x at ~19s


class CasinoError(EconomyError):
    """Message is safe to show to users."""


def EffectiveEdge(edge: float, luck: float) -> float:
    return max(0.0, edge * (1 - max(0.0, min(1.0, luck))))


# ---------------- bets ----------------

AMOUNT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([km]?)$")


def ParseBet(raw: str, balance: int, settings: dict) -> int:
    """'500', '1.5k', '2m', 'todo', 'mitad' -> credits."""
    Text = str(raw).strip().lower().replace(" ", "")
    if Text in ("todo", "all", "max", "allin", "all-in"):
        return min(balance, settings["max"])
    if Text in ("mitad", "half"):
        return balance // 2
    Match = AMOUNT.match(Text.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", Text) else Text)
    if not Match:
        raise CasinoError("Pon una cantidad válida: `500`, `1.5k`, `todo` o `mitad`.")
    Number = float(Match.group(1).replace(",", "."))
    Number *= {"": 1, "k": 1_000, "m": 1_000_000}[Match.group(2)]
    return int(Number)


# ---------------- coinflip ----------------


def CoinflipPayout(bet: int, won: bool, edge: float) -> int:
    return int(bet * 2 * (1 - edge)) if won else 0


# ---------------- slots ----------------

SLOT_SYMBOLS = [("🍒", 30), ("🍋", 25), ("🍇", 20), ("🔔", 12), ("⭐", 7), ("💎", 4), ("7️⃣", 2)]
# Base pays (before tuning to the house edge): three of a kind, or any two of a kind.
THREE_PAYS = {"🍒": 10, "🍋": 15, "🍇": 25, "🔔": 60, "⭐": 150, "💎": 400, "7️⃣": 1000}
TWO_PAYS = 1.0


def BaseMultiplier(reels: tuple[str, str, str]) -> float:
    if reels[0] == reels[1] == reels[2]:
        return THREE_PAYS[reels[0]]
    if len(set(reels)) == 2:
        return TWO_PAYS
    return 0.0


def BaseReturn() -> float:
    """Exact expected multiplier of the base paytable (all 343 combinations)."""
    Total = sum(W for _, W in SLOT_SYMBOLS)
    Expected = 0.0
    for Combo in product(SLOT_SYMBOLS, repeat=3):
        Chance = math.prod(W / Total for _, W in Combo)
        Expected += Chance * BaseMultiplier(tuple(S for S, _ in Combo))
    return Expected


BASE_RETURN = BaseReturn()


def SlotScale(edge: float) -> float:
    """Factor applied to the paytable so the game returns exactly (1 - edge)."""
    return (1 - edge) / BASE_RETURN


def SpinReels(rng: random.Random) -> tuple[str, str, str]:
    Symbols = [S for S, _ in SLOT_SYMBOLS]
    Weights = [W for _, W in SLOT_SYMBOLS]
    return tuple(rng.choices(Symbols, Weights, k=3))


def SlotsPayout(bet: int, reels, edge: float) -> int:
    return int(bet * BaseMultiplier(reels) * SlotScale(edge))


# ---------------- crash ----------------


def CrashPoint(edge: float, maximum: float, rng: random.Random) -> float:
    """
    Where the rocket explodes. P(crash >= m) = (1 - edge) / m, so cashing out at any
    target returns (1 - edge) on average. With probability `edge` it crashes at 1.00x.
    """
    U = rng.random()
    Point = (1 - edge) / (1 - U)
    return max(1.0, min(float(maximum), math.floor(Point * 100) / 100))


def CrashMultiplier(seconds: float) -> float:
    return math.floor(math.exp(CRASH_GROWTH * max(0.0, seconds)) * 100) / 100


def CrashSeconds(multiplier: float) -> float:
    """When the multiplier reaches a value."""
    return math.log(max(1.0, multiplier)) / CRASH_GROWTH


# ---------------- blackjack ----------------


def NewShoe(rng: random.Random) -> list[tuple[str, str]]:
    Shoe = [(R, S) for R in RANKS for S in SUITS] * DECKS
    rng.shuffle(Shoe)
    return Shoe


def HandValue(cards: list[tuple[str, str]]) -> tuple[int, bool]:
    """(best total, is it soft)."""
    Total, Aces = 0, 0
    for Rank, _ in cards:
        if Rank == "A":
            Aces += 1
            Total += 11
        elif Rank in ("J", "Q", "K"):
            Total += 10
        else:
            Total += int(Rank)
    while Total > 21 and Aces:
        Total -= 10
        Aces -= 1
    return Total, Aces > 0


def IsBlackjack(cards) -> bool:
    return len(cards) == 2 and HandValue(cards)[0] == 21


def ShowCards(cards, hide_second: bool = False) -> str:
    return " ".join("`🂠`" if hide_second and i == 1 else f"`{R}{S}`" for i, (R, S) in enumerate(cards))


@dataclass
class Blackjack:
    bet: int
    edge: float
    rng: random.Random
    shoe: list = field(default_factory=list)
    player: list = field(default_factory=list)
    dealer: list = field(default_factory=list)
    doubled: bool = False
    finished: bool = False
    result: str = ""  # blackjack, win, push, lose, bust
    payout: int = 0

    def Deal(self):
        self.shoe = NewShoe(self.rng)
        self.player = [self.shoe.pop(), self.shoe.pop()]
        self.dealer = [self.shoe.pop(), self.shoe.pop()]
        if IsBlackjack(self.player) or IsBlackjack(self.dealer):
            self.Settle()

    def Hit(self):
        self.player.append(self.shoe.pop())
        if HandValue(self.player)[0] > 21:
            self.Settle()

    def Double(self):
        """Doubles the bet (the caller charges it), takes one card and stands."""
        self.bet *= 2
        self.doubled = True
        self.player.append(self.shoe.pop())
        self.Stand()

    def Stand(self):
        # Dealer draws to 17 and stands on soft 17.
        if HandValue(self.player)[0] <= 21:
            while HandValue(self.dealer)[0] < 17:
                self.dealer.append(self.shoe.pop())
        self.Settle()

    def Settle(self):
        Player, Dealer = HandValue(self.player)[0], HandValue(self.dealer)[0]
        Fee = 1 - self.edge  # the house keeps `edge` of the winnings
        if IsBlackjack(self.player) and IsBlackjack(self.dealer):
            self.result, self.payout = "push", self.bet
        elif IsBlackjack(self.player):
            self.result, self.payout = "blackjack", self.bet + int(self.bet * 1.5 * Fee)
        elif IsBlackjack(self.dealer):
            self.result, self.payout = "lose", 0
        elif Player > 21:
            self.result, self.payout = "bust", 0
        elif Dealer > 21 or Player > Dealer:
            self.result, self.payout = "win", self.bet + int(self.bet * Fee)
        elif Player == Dealer:
            self.result, self.payout = "push", self.bet
        else:
            self.result, self.payout = "lose", 0
        self.finished = True


# ---------------- service ----------------


class Casino:
    def __init__(self, economy: EconomyService, pets=None):
        self.economy = economy
        self.pets = pets
        self.cooldowns: dict[tuple[int, int, str], float] = {}
        self.active: set[tuple[int, int, str]] = set()
        self.rng = random.SystemRandom()

    async def Luck(self, guild_id: int, user_id: int, config: dict) -> float:
        return await self.pets.Perk(guild_id, user_id, "luck", config) if self.pets else 0.0

    async def Start(self, member, game: str, raw_amount: str, config: dict, exclusive: bool = False) -> tuple[int, float, float]:
        """
        Validates and takes a bet. Returns (bet, effective edge, luck).
        `exclusive`: only one game of this kind at a time per user (crash, blackjack).
        """
        Settings = config["casino"][game]
        Guild = member.guild
        Key = (Guild.id, member.id, game)
        Wait = self.cooldowns.get(Key, 0) - time.monotonic()
        if Wait > 0:
            raise CasinoError(f"Espera {math.ceil(Wait)}s para volver a jugar.")
        if exclusive and Key in self.active:
            raise CasinoError("Ya tienes una partida en curso, termínala primero.")
        # Reserve before any await, so two quick commands can't both get through.
        if exclusive:
            self.active.add(Key)
        self.cooldowns[Key] = time.monotonic() + Settings["cooldown"]
        try:
            Balance = await self.economy.PeekBalance(Guild.id, member.id)
            Bet = ParseBet(raw_amount, Balance, Settings)
            if Bet < Settings["min"]:
                raise CasinoError(f"La apuesta mínima es {Settings['min']:,}.".replace(",", "."))
            if Bet > Settings["max"]:
                raise CasinoError(f"La apuesta máxima es {Settings['max']:,}.".replace(",", "."))
            Luck = await self.Luck(Guild.id, member.id, config)
            await self.economy.Remove(
                Guild.id, member.id, Bet, f"Apuesta: {game}", kind=BET, ref=f"casino:{game}",
                also_inc={"casino.games": 1, "casino.wagered": Bet},
            )
        except Exception:
            self.active.discard(Key)
            self.cooldowns.pop(Key, None)
            raise
        return Bet, EffectiveEdge(Settings["edge"], Luck), Luck

    async def Raise(self, member, game: str, amount: int):
        """Extra bet during a game (blackjack double)."""
        await self.economy.Remove(
            member.guild.id, member.id, amount, f"Apuesta extra: {game}", kind=BET, ref=f"casino:{game}",
            also_inc={"casino.wagered": amount},
        )

    async def Pay(self, member, game: str, amount: int) -> int:
        """Pays winnings (if any). Returns the new balance."""
        if amount > 0:
            Account = await self.economy.Add(
                member.guild.id, member.id, amount, f"Premio: {game}", kind=PAYOUT, ref=f"casino:{game}",
                also_inc={"casino.won": amount},
            )
            return int(Account["balance"])
        return await self.economy.PeekBalance(member.guild.id, member.id)

    def Finish(self, member, game: str):
        self.active.discard((member.guild.id, member.id, game))
