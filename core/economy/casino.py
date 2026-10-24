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


def Winnings(bet: int, multiplier: float) -> int:
    """bet x multiplier, rounded down, ignoring float noise (20 x 0.99999999 must give 20)."""
    return int(bet * multiplier + 1e-6)


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
    return Winnings(bet, 2 * (1 - edge)) if won else 0


# ---------------- slots ----------------

SLOT_SYMBOLS = [("🍒", 30), ("🍋", 25), ("🍇", 20), ("🔔", 12), ("⭐", 7), ("💎", 4), ("7️⃣", 2)]
# Base pays (before tuning to the house edge): three of a kind, or a pair of the better symbols.
# The table returns ~84% as is (the default 10% edge scales it up a little), so the scale stays near 1 and every win pays more than the bet
# (no "wins" that hand back less than you bet). A pair of cherries pays nothing.
THREE_PAYS = {"🍒": 5, "🍋": 8, "🍇": 12, "🔔": 30, "⭐": 75, "💎": 200, "7️⃣": 777}
TWO_PAYS = {"🍋": 1.2, "🍇": 1.2, "🔔": 1.5, "⭐": 2, "💎": 3, "7️⃣": 5}


def BaseMultiplier(reels: tuple[str, str, str]) -> float:
    if reels[0] == reels[1] == reels[2]:
        return THREE_PAYS[reels[0]]
    if len(set(reels)) == 2:
        Pair = max(set(reels), key=reels.count)
        return TWO_PAYS.get(Pair, 0.0)
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
    return Winnings(bet, BaseMultiplier(reels) * SlotScale(edge))


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
            self.result, self.payout = "blackjack", self.bet + Winnings(self.bet, 1.5 * Fee)
        elif IsBlackjack(self.dealer):
            self.result, self.payout = "lose", 0
        elif Player > 21:
            self.result, self.payout = "bust", 0
        elif Dealer > 21 or Player > Dealer:
            self.result, self.payout = "win", self.bet + Winnings(self.bet, Fee)
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


# ---------------- roulette (European, single zero) ----------------

ROULETTE_NUMBERS = 37
RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_BETS = {
    "rojo": ("🔴 Rojo", RED),
    "negro": ("⚫ Negro", set(range(1, 37)) - RED),
    "par": ("Par", {n for n in range(1, 37) if n % 2 == 0}),
    "impar": ("Impar", {n for n in range(1, 37) if n % 2 == 1}),
    "1-18": ("Del 1 al 18", set(range(1, 19))),
    "19-36": ("Del 19 al 36", set(range(19, 37))),
    "docena1": ("1ª docena (1-12)", set(range(1, 13))),
    "docena2": ("2ª docena (13-24)", set(range(13, 25))),
    "docena3": ("3ª docena (25-36)", set(range(25, 37))),
}


def RouletteColor(number: int) -> str:
    return "🟢" if number == 0 else ("🔴" if number in RED else "⚫")


def RouletteBet(choice: str) -> tuple[str, set[int]]:
    """'rojo', 'docena2', '17'... -> (label, winning numbers)."""
    Text = choice.strip().lower().replace("ª", "").replace(" ", "")
    if Text in ROULETTE_BETS:
        return ROULETTE_BETS[Text]
    if Text.isdigit() and 0 <= int(Text) <= 36:
        return f"Número {int(Text)} {RouletteColor(int(Text))}", {int(Text)}
    raise CasinoError("Apuesta a `rojo`, `negro`, `par`, `impar`, `1-18`, `19-36`, `docena1/2/3` o un número del 0 al 36.")


def RouletteMultiplier(winning: set[int], edge: float) -> float:
    """Fair odds (37 / winning numbers) minus the house edge."""
    return (1 - edge) * ROULETTE_NUMBERS / len(winning)


# ---------------- mines ----------------

MINES_TILES = 20  # 4 rows of 5 buttons; the 5th row holds the cash-out button


def MinesFair(tiles: int, mines: int, revealed: int) -> float:
    """Fair multiplier after `revealed` safe tiles: 1 / chance of surviving them."""
    Multiplier = 1.0
    for i in range(revealed):
        Multiplier *= (tiles - i) / (tiles - mines - i)
    return Multiplier


@dataclass
class MinesGame:
    bet: int
    mines: int
    edge: float
    rng: random.Random
    tiles: int = MINES_TILES
    cap: float = 0  # highest multiplier (0 = no limit); reaching it cashes out
    bombs: set = field(default_factory=set)
    revealed: set = field(default_factory=set)
    finished: bool = False
    exploded: int | None = None
    payout: int = 0

    def __post_init__(self):
        if not 1 <= self.mines < self.tiles:
            raise CasinoError(f"Pon entre 1 y {self.tiles - 1} minas.")
        self.bombs = set(self.rng.sample(range(self.tiles), self.mines))

    def Multiplier(self, revealed: int | None = None) -> float:
        Count = len(self.revealed) if revealed is None else revealed
        Value = (1 - self.edge) * MinesFair(self.tiles, self.mines, Count)
        return min(Value, self.cap) if self.cap else Value

    def Reveal(self, tile: int) -> bool:
        """Opens a tile. Returns True if it was safe."""
        if self.finished or tile in self.revealed:
            return True
        if tile in self.bombs:
            self.exploded = tile
            self.finished, self.payout = True, 0
            return False
        self.revealed.add(tile)
        if len(self.revealed) == self.tiles - self.mines or (self.cap and self.Multiplier() >= self.cap):
            self.CashOut()  # nothing left to open, or nothing more to win
        return True

    def CashOut(self):
        if self.finished:
            return
        self.finished = True
        # Leaving without opening anything just returns the bet.
        self.payout = Winnings(self.bet, self.Multiplier()) if self.revealed else self.bet


# ---------------- higher / lower ----------------

HILO_RANKS = 13  # A=1 ... K=13, every card equally likely


def HiLoChance(value: int, higher: bool) -> float:
    """Chance the next card is strictly higher/lower (a tie loses)."""
    return (HILO_RANKS - value) / HILO_RANKS if higher else (value - 1) / HILO_RANKS


@dataclass
class HiLoGame:
    bet: int
    edge: float
    rng: random.Random
    card: tuple = None
    fair: float = 1.0
    cap: float = 0  # highest multiplier (0 = no limit); reaching it cashes out
    streak: int = 0
    finished: bool = False
    lost: bool = False
    payout: int = 0
    previous: tuple = None

    def __post_init__(self):
        self.card = self.Draw()

    def Draw(self) -> tuple[int, str]:
        return self.rng.randint(1, HILO_RANKS), self.rng.choice(SUITS)

    def Capped(self, value: float) -> float:
        return min(value, self.cap) if self.cap else value

    def Multiplier(self) -> float:
        """What cashing out now pays (1 before the first guess: you get the bet back)."""
        return self.Capped((1 - self.edge) * self.fair) if self.streak else 1.0

    def Next(self, higher: bool) -> float:
        """Multiplier you'd have after a correct guess."""
        Chance = HiLoChance(self.card[0], higher)
        return self.Capped((1 - self.edge) * self.fair / Chance) if Chance else 0.0

    def Guess(self, higher: bool) -> bool:
        Chance = HiLoChance(self.card[0], higher)
        if self.finished or not Chance:
            return False
        New = self.Draw()
        Right = New[0] > self.card[0] if higher else New[0] < self.card[0]
        self.previous, self.card = self.card, New
        if Right:
            self.fair /= Chance
            self.streak += 1
            if self.cap and self.Multiplier() >= self.cap:
                self.CashOut()
        else:
            self.finished, self.lost, self.payout = True, True, 0
        return Right

    def CashOut(self):
        if self.finished:
            return
        self.finished = True
        self.payout = Winnings(self.bet, self.Multiplier()) if self.streak else self.bet


def HiLoName(card: tuple[int, str]) -> str:
    return f"{RANKS[card[0] - 1]}{card[1]}"


# ---------------- horse race ----------------

# (name, chance of winning)
HORSES = [
    ("Relámpago", 0.35),
    ("Tortilla", 0.25),
    ("Pegaso", 0.20),
    ("Don Galopín", 0.12),
    ("Turbo Burro", 0.08),
]
RACE_LENGTH = 16
RACE_FRAMES = 5


def RaceMultiplier(horse: int, edge: float) -> float:
    return (1 - edge) / HORSES[horse][1]


def RaceWinner(rng: random.Random) -> int:
    return rng.choices(range(len(HORSES)), [C for _, C in HORSES])[0]


def RaceFrames(winner: int, rng: random.Random, frames: int = RACE_FRAMES, length: int = RACE_LENGTH) -> list[list[int]]:
    """Positions of every horse per frame. The winner crosses the line first, on the last frame."""
    Finish = [length if H == winner else rng.randint(length // 2, length - 1) for H in range(len(HORSES))]
    Steps = []
    for F in range(1, frames + 1):
        T = F / frames
        Row = []
        for H, End in enumerate(Finish):
            # Wobble along the way so the race doesn't look scripted.
            Wobble = 0 if F == frames else rng.randint(-2, 2)
            Row.append(max(0, min(length - (0 if H == winner and F == frames else 1), round(End * T) + Wobble)))
        Steps.append(Row)
    return Steps
