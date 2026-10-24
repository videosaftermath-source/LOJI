import asyncio
import logging
import math
import time
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.Module import ModuleIsEnabled
from core.bot.emojis import Emojis
from core.economy.casino import (
    SLOT_SYMBOLS,
    THREE_PAYS,
    TWO_PAYS,
    Blackjack,
    CoinflipPayout,
    CrashMultiplier,
    CrashPoint,
    CrashSeconds,
    EffectiveEdge,
    HandValue,
    ShowCards,
    SlotScale,
    SlotsPayout,
    SpinReels,
    Winnings,
    HORSES,
    MINES_TILES,
    HiLoGame,
    MinesGame,
    RaceFrames,
    RaceMultiplier,
    RaceWinner,
    RouletteBet,
    RouletteColor,
    RouletteMultiplier,
    ROULETTE_BETS,
)
from cogs.Modules.Economy.casino_games import HiLoView, HorseChoices, MinesView, RaceTrack
from core.economy.config import EcoConfig
from core.economy.constants import GAME_COMMANDS, GAMES, MODULE
from core.economy.registry import Eco
from core.economy.rewards import FormatAmount
from core.economy.service import EconomyError, InsufficientFunds

logger = logging.getLogger(__name__)

CRASH_TICK = 2.0  # seconds between message edits (safe for Discord's rate limits)
CRASH_BAR = 12
SPIN_STEP = 0.9
FLIP_TIME = 1.3
BLACKJACK_TIMEOUT = 120
RESULT = {"blackjack": "🃏 ¡BLACKJACK!", "win": "✅ ¡Ganaste!", "push": "🤝 Empate", "lose": "❌ Perdiste", "bust": "💥 Te pasaste"}


def Money(amount: int, config: dict) -> str:
    return FormatAmount(amount, config)


def EdgeNote(edge: float, luck: float) -> str:
    Note = f"Ventaja de la casa: {edge:.2%}"
    return Note + (f" (🍀 tu suerte la baja un {luck:.0%})" if luck else "")


async def Fail(ctx: commands.Context, error: Exception, config: dict):
    if isinstance(error, InsufficientFunds):
        return await ctx.send(f"{Emojis.no} No te alcanza 💸 Tienes {Money(error.balance, config)}.", ephemeral=True)
    await ctx.send(f"{Emojis.no} {error}", ephemeral=True)


# ---------------- crash ----------------


class CrashGame:
    def __init__(self, member: discord.Member, bet: int, crash: float, edge: float, luck: float, auto: float | None):
        self.member = member
        self.bet = bet
        self.crash = crash
        self.edge = edge
        self.luck = luck
        self.auto = auto
        self.start = time.monotonic()
        self.cashed: float | None = None  # multiplier the player cashed out at
        self.done = False
        self.wake = asyncio.Event()

    def Now(self) -> float:
        return CrashMultiplier(time.monotonic() - self.start)


class CrashView(discord.ui.View):
    def __init__(self, game: CrashGame):
        super().__init__(timeout=CrashSeconds(game.crash) + 30)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.member.id:
            await interaction.response.send_message("Ese cohete no es tuyo 🚀", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Retirarse", emoji="💰", style=discord.ButtonStyle.green)
    async def CashOut(self, interaction: discord.Interaction, _):
        Game = self.game
        # Decide with the server's clock, not what the message showed.
        if not Game.done:
            Multiplier = Game.Now()
            if Multiplier < Game.crash:
                Game.cashed = Multiplier
                Game.done = True
                Game.wake.set()
        await interaction.response.defer()


def CrashEmbed(game: CrashGame, multiplier: float, config: dict, state: str = "flying") -> discord.embeds.Embed:
    Height = min(CRASH_BAR - 1, int(CRASH_BAR * math.log(max(1.0, multiplier)) / math.log(10)))
    Track = "▱" * Height + ("🚀" if state != "crashed" else "💥") + "▱" * (CRASH_BAR - 1 - Height)
    if state == "flying":
        Color, Title = discord.Color.blurple(), "🚀 Crash"
        Body = f"Si te retiras ahora: **{Money(Winnings(game.bet, multiplier), config)}**"
        if game.auto:
            Body += f"\n-# Retiro automático en {game.auto:.2f}x"
    elif state == "cashed":
        Color, Title = discord.Color.green(), "💰 ¡Te retiraste a tiempo!"
        Body = f"Cobraste **{Money(Winnings(game.bet, game.cashed), config)}** · el cohete explotó en **{game.crash:.2f}x**"
    else:
        Color, Title = discord.Color.red(), f"💥 ¡CRASH en {game.crash:.2f}x!"
        Body = f"Perdiste {Money(game.bet, config)} 😭"
    Shown = game.cashed if state == "cashed" else multiplier
    embed = discord.Embed(title=Title, description=f"# {Shown:.2f}x\n{Track}\n\n{Body}", color=Color)
    embed.set_author(name=f"{game.member.display_name} apostó {game.bet:,}".replace(",", "."), icon_url=game.member.display_avatar)
    embed.set_footer(text=EdgeNote(game.edge, game.luck))
    return embed


# ---------------- blackjack ----------------


class BlackjackView(discord.ui.View):
    def __init__(self, client: discord.Client, member: discord.Member, game: Blackjack, config: dict, luck: float):
        super().__init__(timeout=BLACKJACK_TIMEOUT)
        self.client = client
        self.member = member
        self.game = game
        self.config = config
        self.luck = luck
        self.message: discord.Message | None = None
        self.busy = False
        self.Update()

    def Update(self):
        self.DoubleDown.disabled = len(self.game.player) != 2 or self.game.doubled

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Esa mano no es tuya 🃏", ephemeral=True)
            return False
        if self.busy or self.game.finished:
            await interaction.response.defer()
            return False
        return True

    async def Act(self, interaction: discord.Interaction, action):
        self.busy = True
        await interaction.response.defer()
        try:
            await action()
            self.Update()
            if self.game.finished:
                await Settle(self.client, self.member, self.game)
                self.stop()
            await interaction.edit_original_response(embed=BlackjackEmbed(self.member, self.game, self.config, self.luck), view=None if self.game.finished else self)
        finally:
            self.busy = False

    @discord.ui.button(label="Pedir", emoji="➕", style=discord.ButtonStyle.blurple)
    async def HitButton(self, interaction: discord.Interaction, _):
        async def Do():
            self.game.Hit()

        await self.Act(interaction, Do)

    @discord.ui.button(label="Plantarse", emoji="✋", style=discord.ButtonStyle.grey)
    async def StandButton(self, interaction: discord.Interaction, _):
        async def Do():
            self.game.Stand()

        await self.Act(interaction, Do)

    @discord.ui.button(label="Doblar", emoji="💸", style=discord.ButtonStyle.green)
    async def DoubleDown(self, interaction: discord.Interaction, _):
        async def Do():
            try:
                await Eco().casino.Raise(self.member, "blackjack", self.game.bet)
            except InsufficientFunds:
                await interaction.followup.send("No te alcanza para doblar 💸", ephemeral=True)
                return
            self.game.Double()

        await self.Act(interaction, Do)

    async def on_timeout(self):
        if self.game.finished:
            return
        self.game.Stand()
        await Settle(self.client, self.member, self.game)
        if self.message:
            try:
                await self.message.edit(content="⏰ Tardaste mucho: te plantaste solo.", embed=BlackjackEmbed(self.member, self.game, self.config, self.luck), view=None)
            except discord.HTTPException:
                pass


async def Settle(client: discord.Client, member: discord.Member, game: Blackjack):
    """Pays the hand (once) and frees the player to start another."""
    try:
        await Eco().casino.Pay(member, "blackjack", game.payout)
    finally:
        Eco().casino.Finish(member, "blackjack")
    client.dispatch("economy_progress", member.guild.id, member.id, "play", 1)


def BlackjackEmbed(member: discord.Member, game: Blackjack, config: dict, luck: float) -> discord.Embed:
    Player, Soft = HandValue(game.player)
    Dealer = HandValue(game.dealer)[0]
    if game.finished:
        Title = RESULT[game.result]
        Color = {"blackjack": discord.Color.gold(), "win": discord.Color.green(), "push": discord.Color.light_grey()}.get(game.result, discord.Color.red())
    else:
        Title, Color = "🃏 Blackjack", discord.Color.dark_green()
    embed = discord.Embed(title=Title, color=Color)
    embed.set_author(name=f"{member.display_name} apostó {game.bet:,}".replace(",", ".") + (" (doblado)" if game.doubled else ""), icon_url=member.display_avatar)
    embed.add_field(
        name="🎩 Crupier",
        value=f"{ShowCards(game.dealer, hide_second=not game.finished)}\n" + (f"**{Dealer}**" if game.finished else f"**{HandValue(game.dealer[:1])[0]}** + ?"),
        inline=False,
    )
    embed.add_field(name=f"🙋 {member.display_name}", value=f"{ShowCards(game.player)}\n**{Player}**" + (" (suave)" if Soft and Player < 21 else ""), inline=False)
    if game.finished:
        Net = game.payout - game.bet
        embed.add_field(
            name="Resultado",
            value=f"Cobras {Money(game.payout, config)} ({'+' if Net >= 0 else ''}{Net:,})".replace(",", "."),
            inline=False,
        )
    embed.set_footer(text=EdgeNote(game.edge, luck) + " · El crupier se planta en 17 · Blackjack paga 3:2")
    return embed


# ---------------- slots ----------------


def SlotsTable(edge: float, config: dict) -> str:
    Scale = SlotScale(edge)
    Rows = [f"{S}{S}{S} → x{THREE_PAYS[S] * Scale:.2f}" for S, _ in reversed(SLOT_SYMBOLS)]
    Pairs = " · ".join(f"{S}{S} x{TWO_PAYS[S] * Scale:.2f}" for S, _ in reversed(SLOT_SYMBOLS) if S in TWO_PAYS)
    Rows.append(f"Dos iguales: {Pairs}")
    return "\n".join(Rows)


class EconomyCasino(commands.Cog):
    """Juegos de casino."""

    def __init__(self, client: commands.Bot):
        self.client = client

    async def Begin(self, ctx: commands.Context, game: str, amount: str, exclusive: bool = False):
        """Defers, loads config and takes the bet. Returns (config, bet, edge, luck) or None."""
        await ctx.defer()
        Config = await EcoConfig().Get(ctx.guild.id)
        try:
            Bet, Edge, Luck = await Eco().casino.Start(ctx.author, game, amount, Config, exclusive=exclusive)
        except EconomyError as e:
            await Fail(ctx, e, Config)
            return None
        return Config, Bet, Edge, Luck

    def Played(self, ctx: commands.Context):
        self.client.dispatch("economy_progress", ctx.guild.id, ctx.author.id, "play", 1)

    @commands.hybrid_group(name="casino", description="Juegos de casino")
    @commands.guild_only()
    async def casino(self, ctx: commands.Context):
        pass

    @casino.command(name="info", description="Juegos, límites, ventaja de la casa y tus estadísticas")
    @ModuleIsEnabled(MODULE)
    async def info(self, ctx: commands.Context):
        Config = await EcoConfig().Get(ctx.guild.id)
        Luck = await Eco().casino.Luck(ctx.guild.id, ctx.author.id, Config)
        embed = discord.Embed(title="🎲 Casino", color=discord.Color.dark_gold())
        for Game, Label in GAMES.items():
            S = Config["casino"][Game]
            Edge = EffectiveEdge(S["edge"], Luck)
            embed.add_field(
                name=f"{Label} · `/casino {GAME_COMMANDS[Game]}`",
                value=f"Apuesta: {S['min']:,} – {S['max']:,}\nCasa: {Edge:.2%} · Espera: {S['cooldown']}s".replace(",", "."),
            )
        embed.add_field(name="🎰 Premios de slots", value=SlotsTable(EffectiveEdge(Config["casino"]["slots"]["edge"], Luck), Config), inline=False)
        Stats = (await Eco().economy.Account(ctx.guild.id, ctx.author.id)).get("casino", {})
        Net = int(Stats.get("won", 0)) - int(Stats.get("wagered", 0))
        embed.add_field(
            name=f"📊 Tus estadísticas{' · 🍀 suerte ' + format(Luck, '.0%') if Luck else ''}",
            value=(
                f"Partidas: **{Stats.get('games', 0):,}** · Apostado: **{Stats.get('wagered', 0):,}**\n"
                f"Ganado: **{Stats.get('won', 0):,}** · Balance: **{'+' if Net >= 0 else ''}{Net:,}**"
            ).replace(",", "."),
            inline=False,
        )
        embed.set_footer(text="Puedes apostar números, 1.5k, todo o mitad. Juega con cabeza 😉")
        await ctx.send(embed=embed)

    @casino.command(name="moneda", description="Cara o cruz: doblas lo apostado (menos la casa)")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)", lado="Cara o cruz")
    @ModuleIsEnabled(MODULE)
    async def moneda(self, ctx: commands.Context, cantidad: str, lado: Literal["cara", "cruz"]):
        Started = await self.Begin(ctx, "coinflip", cantidad)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        Landed = Eco().casino.rng.choice(["cara", "cruz"])
        Won = Landed == lado
        Payout = CoinflipPayout(Bet, Won, Edge)
        await Eco().casino.Pay(ctx.author, "coinflip", Payout)
        self.Played(ctx)
        embed = discord.Embed(description=f"🪙 Lanzando la moneda... elegiste **{lado}**", color=discord.Color.dark_gold())
        Message = await ctx.send(embed=embed)
        await asyncio.sleep(FLIP_TIME)
        embed = discord.Embed(
            title=("✅ ¡Ganaste!" if Won else "❌ Perdiste"),
            description=f"Salió **{Landed}** {'🌕' if Landed == 'cara' else '🌑'}\n"
            + (f"Cobras {Money(Payout, Config)}" if Won else f"Pierdes {Money(Bet, Config)}"),
            color=discord.Color.green() if Won else discord.Color.red(),
        )
        embed.set_footer(text=EdgeNote(Edge, Luck))
        await Message.edit(embed=embed)

    @casino.command(name="slots", description="Gira la tragamonedas")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)")
    @ModuleIsEnabled(MODULE)
    async def slots(self, ctx: commands.Context, cantidad: str):
        Started = await self.Begin(ctx, "slots", cantidad)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        Reels = SpinReels(Eco().casino.rng)
        Payout = SlotsPayout(Bet, Reels, Edge)
        await Eco().casino.Pay(ctx.author, "slots", Payout)
        self.Played(ctx)

        def Frame(shown: int, final: bool = False) -> discord.Embed:
            Faces = [Reels[i] if i < shown else "🔄" for i in range(3)]
            embed = discord.Embed(title="🎰 Slots", description=f"# ┃ {' ┃ '.join(Faces)} ┃", color=discord.Color.purple())
            embed.set_author(name=f"{ctx.author.display_name} apostó {Bet:,}".replace(",", "."), icon_url=ctx.author.display_avatar)
            if final:
                if Payout > Bet:
                    embed.color = discord.Color.gold() if Payout >= Bet * 10 else discord.Color.green()
                    embed.add_field(name="✅ ¡Premio!", value=f"Cobras {Money(Payout, Config)} (x{Payout / Bet:.2f})")
                elif Payout:
                    embed.color = discord.Color.light_grey()
                    embed.add_field(name="🫤 Algo es algo", value=f"Recuperas {Money(Payout, Config)}")
                else:
                    embed.color = discord.Color.red()
                    embed.add_field(name="❌ Nada", value=f"Pierdes {Money(Bet, Config)}")
                embed.set_footer(text=EdgeNote(Edge, Luck) + " · Mira los premios con /casino info")
            return embed

        Message = await ctx.send(embed=Frame(0))
        for Shown in (1, 2):
            await asyncio.sleep(SPIN_STEP)
            await Message.edit(embed=Frame(Shown))
        await asyncio.sleep(SPIN_STEP)
        await Message.edit(embed=Frame(3, final=True))

    @casino.command(name="crash", description="El cohete sube... ¡retírate antes de que explote!")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)", retiro_auto="Retirarte solo al llegar a este multiplicador (ej. 2)")
    @ModuleIsEnabled(MODULE)
    async def crash(self, ctx: commands.Context, cantidad: str, retiro_auto: app_commands.Range[float, 1.01, 1000.0] = None):
        Started = await self.Begin(ctx, "crash", cantidad, exclusive=True)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        Game = CrashGame(ctx.author, Bet, CrashPoint(Edge, Config["casino"]["crash"]["max_multiplier"], Eco().casino.rng), Edge, Luck, retiro_auto)
        View = CrashView(Game)
        try:
            Message = await ctx.send(embed=CrashEmbed(Game, 1.0, Config), view=View)
            Game.start = time.monotonic()
            while not Game.done:
                Multiplier = Game.Now()
                if Multiplier >= Game.crash:
                    Game.done = True
                    break
                if Game.auto and Multiplier >= Game.auto:
                    Game.cashed, Game.done = Game.auto, True
                    break
                # Sleep until the next edit, the crash, the auto cash-out or the button, whichever is first.
                Elapsed = time.monotonic() - Game.start
                Targets = [CRASH_TICK, CrashSeconds(Game.crash) - Elapsed]
                if Game.auto:
                    Targets.append(CrashSeconds(Game.auto) - Elapsed)
                try:
                    await asyncio.wait_for(Game.wake.wait(), timeout=max(0.05, min(Targets)))
                except asyncio.TimeoutError:
                    pass
                if not Game.done and Game.Now() < Game.crash:
                    try:
                        await Message.edit(embed=CrashEmbed(Game, Game.Now(), Config), view=View)
                    except discord.HTTPException:
                        pass
            Won = Game.cashed is not None
            await Eco().casino.Pay(ctx.author, "crash", Winnings(Bet, Game.cashed) if Won else 0)
        finally:
            Eco().casino.Finish(ctx.author, "crash")
            View.stop()
        self.Played(ctx)
        await Message.edit(embed=CrashEmbed(Game, Game.crash, Config, "cashed" if Won else "crashed"), view=None)

    @casino.command(name="blackjack", description="Llega a 21 sin pasarte y gánale al crupier")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)")
    @ModuleIsEnabled(MODULE)
    async def blackjack(self, ctx: commands.Context, cantidad: str):
        Started = await self.Begin(ctx, "blackjack", cantidad, exclusive=True)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        Game = Blackjack(Bet, Edge, Eco().casino.rng)
        Game.Deal()
        if Game.finished:
            await Settle(self.client, ctx.author, Game)
            return await ctx.send(embed=BlackjackEmbed(ctx.author, Game, Config, Luck))
        View = BlackjackView(self.client, ctx.author, Game, Config, Luck)
        View.message = await ctx.send(embed=BlackjackEmbed(ctx.author, Game, Config, Luck), view=View)


    @casino.command(name="ruleta", description="Ruleta europea: color, par/impar, mitades, docenas o número")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)", apuesta="rojo, negro, par, impar, 1-18, 19-36, docena1/2/3 o un número 0-36")
    @ModuleIsEnabled(MODULE)
    async def ruleta(self, ctx: commands.Context, cantidad: str, apuesta: str):
        try:
            Label, Winning = RouletteBet(apuesta)
        except EconomyError as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        Started = await self.Begin(ctx, "roulette", cantidad)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        Number = Eco().casino.rng.randrange(37)
        Multiplier = RouletteMultiplier(Winning, Edge)
        Won = Number in Winning
        Payout = Winnings(Bet, Multiplier) if Won else 0
        await Eco().casino.Pay(ctx.author, "roulette", Payout)
        self.Played(ctx)
        embed = discord.Embed(title="🎡 Ruleta", description=f"Apostaste a **{Label}** (paga x{Multiplier:.2f})\n# 🎡 girando...", color=discord.Color.dark_green())
        Message = await ctx.send(embed=embed)
        for Fake in Eco().casino.rng.sample(range(37), 2):
            await asyncio.sleep(0.9)
            embed.description = f"Apostaste a **{Label}** (paga x{Multiplier:.2f})\n# 🎡 {Fake} {RouletteColor(Fake)}..."
            await Message.edit(embed=embed)
        await asyncio.sleep(1.0)
        embed = discord.Embed(
            title="✅ ¡Ganaste!" if Won else "❌ Perdiste",
            description=f"La bola cae en...\n# {Number} {RouletteColor(Number)}\n"
            + (f"Cobras {Money(Payout, Config)}" if Won else f"Pierdes {Money(Bet, Config)}"),
            color=discord.Color.green() if Won else discord.Color.red(),
        )
        embed.set_author(name=f"{ctx.author.display_name} apostó {Bet:,} a {Label}".replace(",", "."), icon_url=ctx.author.display_avatar)
        embed.set_footer(text=EdgeNote(Edge, Luck))
        await Message.edit(embed=embed)

    @ruleta.autocomplete("apuesta")
    async def RuletaAutocomplete(self, interaction: discord.Interaction, current: str):
        Options = [app_commands.Choice(name=Label, value=Key) for Key, (Label, _) in ROULETTE_BETS.items()]
        if current.strip().isdigit() and 0 <= int(current) <= 36:
            Options.insert(0, app_commands.Choice(name=f"Número {int(current)}", value=str(int(current))))
        return [O for O in Options if current.lower() in O.name.lower() or current.strip().isdigit()][:25]

    @casino.command(name="mines", description="Abre casillas y evita las minas: cada diamante multiplica")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)", minas=f"Cuántas minas (1-{MINES_TILES - 1}); más minas, más paga cada diamante")
    @ModuleIsEnabled(MODULE)
    async def mines(self, ctx: commands.Context, cantidad: str, minas: app_commands.Range[int, 1, MINES_TILES - 1] = 3):
        if not 1 <= minas < MINES_TILES:
            return await ctx.send(f"{Emojis.no} Pon entre 1 y {MINES_TILES - 1} minas.", ephemeral=True)
        Started = await self.Begin(ctx, "mines", cantidad, exclusive=True)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        View = MinesView(self.client, ctx.author, MinesGame(Bet, minas, Edge, Eco().casino.rng, cap=Config["casino"]["mines"]["max_multiplier"]), Config, Luck)
        View.message = await ctx.send(embed=View.Embed(), view=View)

    @casino.command(name="mayormenor", description="¿La siguiente carta será mayor o menor? Cada acierto multiplica")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)")
    @ModuleIsEnabled(MODULE)
    async def mayormenor(self, ctx: commands.Context, cantidad: str):
        Started = await self.Begin(ctx, "hilo", cantidad, exclusive=True)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        View = HiLoView(self.client, ctx.author, HiLoGame(Bet, Edge, Eco().casino.rng, cap=Config["casino"]["hilo"]["max_multiplier"]), Config, Luck)
        View.message = await ctx.send(embed=View.Embed(), view=View)

    @casino.command(name="carrera", description="Apuesta a un caballo: el favorito paga poco, el tapado paga mucho")
    @app_commands.describe(cantidad="Cuánto apuestas (500, 1.5k, todo, mitad)", caballo="Tu caballo")
    @app_commands.choices(caballo=[app_commands.Choice(name=f"{i + 1}. {Name} ({Chance:.0%})", value=i + 1) for i, (Name, Chance) in enumerate(HORSES)])
    @ModuleIsEnabled(MODULE)
    async def carrera(self, ctx: commands.Context, cantidad: str, caballo: int):
        if not 1 <= caballo <= len(HORSES):
            Config = await EcoConfig().Get(ctx.guild.id)
            return await ctx.send(f"Elige un caballo del 1 al {len(HORSES)}:\n{HorseChoices(Config['casino']['race']['edge'])}", ephemeral=True)
        Started = await self.Begin(ctx, "race", cantidad)
        if not Started:
            return
        Config, Bet, Edge, Luck = Started
        Picked = caballo - 1
        Winner = RaceWinner(Eco().casino.rng)
        Multiplier = RaceMultiplier(Picked, Edge)
        Payout = Winnings(Bet, Multiplier) if Winner == Picked else 0
        await Eco().casino.Pay(ctx.author, "race", Payout)
        self.Played(ctx)
        Frames = RaceFrames(Winner, Eco().casino.rng)
        Length = max(max(F) for F in Frames)
        Header = f"Apostaste {Bet:,} a **{HORSES[Picked][0]}** (paga x{Multiplier:.2f})".replace(",", ".")
        embed = discord.Embed(title="🏇 ¡Arrancan!", description=f"{Header}\n\n{RaceTrack([0] * len(HORSES), Length, Picked)}", color=discord.Color.dark_orange())
        Message = await ctx.send(embed=embed)
        for Positions in Frames:
            await asyncio.sleep(1.2)
            embed.description = f"{Header}\n\n{RaceTrack(Positions, Length, Picked)}"
            await Message.edit(embed=embed)
        Won = Winner == Picked
        embed = discord.Embed(
            title=f"🏆 ¡Ganó {HORSES[Winner][0]}!",
            description=f"{Header}\n\n{RaceTrack(Frames[-1], Length, Picked, Winner)}\n\n"
            + (f"✅ ¡Tu caballo ganó! Cobras {Money(Payout, Config)}" if Won else f"❌ Perdiste {Money(Bet, Config)}"),
            color=discord.Color.green() if Won else discord.Color.red(),
        )
        embed.set_footer(text=EdgeNote(Edge, Luck))
        await Message.edit(embed=embed)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyCasino(client))
