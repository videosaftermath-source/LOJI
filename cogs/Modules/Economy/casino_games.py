"""Buttons and embeds for the interactive casino games (mines, higher/lower) and the horse race."""

import discord

from core.economy.casino import HORSES, MINES_TILES, HiLoChance, HiLoGame, HiLoName, MinesGame, RaceMultiplier, Winnings
from core.economy.registry import Eco
from core.economy.rewards import FormatAmount

GAME_TIMEOUT = 180
TILES_PER_ROW = 5


def EdgeNote(edge: float, luck: float) -> str:
    Note = f"Ventaja de la casa: {edge:.2%}"
    return Note + (f" (🍀 tu suerte la baja un {luck:.0%})" if luck else "")


async def Settle(client: discord.Client, member: discord.Member, game_name: str, payout: int):
    """Pays (once) and frees the player to start another game."""
    try:
        await Eco().casino.Pay(member, game_name, payout)
    finally:
        Eco().casino.Finish(member, game_name)
    client.dispatch("economy_progress", member.guild.id, member.id, "play", 1)


class GameView(discord.ui.View):
    """Shared plumbing: owner-only, ignores clicks while busy or after the end, settles on timeout."""

    game_name = ""

    def __init__(self, client: discord.Client, member: discord.Member, game, config: dict, luck: float):
        super().__init__(timeout=GAME_TIMEOUT)
        self.client = client
        self.member = member
        self.game = game
        self.config = config
        self.luck = luck
        self.message: discord.Message | None = None
        self.busy = False
        self.settled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Esa partida no es tuya 👀", ephemeral=True)
            return False
        if self.busy or self.game.finished:
            await interaction.response.defer()
            return False
        return True

    async def Act(self, interaction: discord.Interaction, action):
        self.busy = True
        await interaction.response.defer()
        try:
            action()
            await self.AfterAction(interaction)
        finally:
            self.busy = False

    async def AfterAction(self, interaction: discord.Interaction | None):
        if self.game.finished and not self.settled:
            self.settled = True
            await Settle(self.client, self.member, self.game_name, self.game.payout)
            self.stop()
        self.Refresh()
        Kwargs = {"embed": self.Embed(), "view": self}
        if interaction is not None:
            await interaction.edit_original_response(**Kwargs)
        elif self.message:
            await self.message.edit(**Kwargs)

    async def on_timeout(self):
        if self.game.finished:
            return
        self.game.CashOut()
        try:
            await self.AfterAction(None)
        except discord.HTTPException:
            pass

    def Refresh(self):
        pass

    def Embed(self) -> discord.Embed:
        raise NotImplementedError


# ---------------- mines ----------------


class Tile(discord.ui.Button):
    def __init__(self, index: int):
        super().__init__(label="​", emoji="❔", style=discord.ButtonStyle.grey, row=index // TILES_PER_ROW)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        View: MinesView = self.view
        await View.Act(interaction, lambda: View.game.Reveal(self.index))


class MinesView(GameView):
    game_name = "mines"

    def __init__(self, *args):
        super().__init__(*args)
        self.tiles = [Tile(i) for i in range(MINES_TILES)]
        for T in self.tiles:
            self.add_item(T)
        self.cash = discord.ui.Button(emoji="💰", style=discord.ButtonStyle.green, row=MINES_TILES // TILES_PER_ROW)

        async def Cash(interaction: discord.Interaction):
            await self.Act(interaction, self.game.CashOut)

        self.cash.callback = Cash
        self.add_item(self.cash)
        self.Refresh()

    def Refresh(self):
        Game: MinesGame = self.game
        for T in self.tiles:
            if T.index in Game.revealed:
                T.emoji, T.style, T.disabled = "💎", discord.ButtonStyle.green, True
            elif Game.finished and T.index == Game.exploded:
                T.emoji, T.style, T.disabled = "💥", discord.ButtonStyle.red, True
            elif Game.finished and T.index in Game.bombs:
                T.emoji, T.style, T.disabled = "💣", discord.ButtonStyle.red, True
            elif Game.finished:
                T.emoji, T.disabled = "▫️", True
        if Game.finished:
            self.cash.disabled = True
            self.cash.label = "Fin"
        else:
            Value = Winnings(Game.bet, Game.Multiplier()) if Game.revealed else Game.bet
            self.cash.label = f"Retirarse ({Value:,})".replace(",", ".")

    def Embed(self) -> discord.Embed:
        Game: MinesGame = self.game
        Safe = MINES_TILES - Game.mines
        if Game.finished and Game.exploded is not None:
            Title, Color = "💥 ¡BOOM! Pisaste una mina", discord.Color.red()
            Body = f"Perdiste {FormatAmount(Game.bet, self.config)}"
        elif Game.finished:
            Title, Color = "💰 ¡Te retiraste!", discord.Color.green()
            Body = f"Cobraste {FormatAmount(Game.payout, self.config)}"
        else:
            Title, Color = "💣 Mines", discord.Color.dark_teal()
            Next = Game.Multiplier(len(Game.revealed) + 1)
            Body = (
                f"Multiplicador: **x{Game.Multiplier():.2f}**" if Game.revealed else "¡Abre una casilla!"
            ) + f"\n-# Siguiente diamante: x{Next:.2f}"
        embed = discord.Embed(title=Title, description=f"{Body}\n💎 {len(Game.revealed)}/{Safe} · 💣 {Game.mines} minas", color=Color)
        embed.set_author(name=f"{self.member.display_name} apostó {Game.bet:,}".replace(",", "."), icon_url=self.member.display_avatar)
        embed.set_footer(text=EdgeNote(Game.edge, self.luck) + " · Si te vas sin abrir nada, recuperas lo apostado")
        return embed


# ---------------- higher / lower ----------------


class HiLoView(GameView):
    game_name = "hilo"

    def __init__(self, *args):
        super().__init__(*args)
        self.Refresh()

    def Refresh(self):
        Game: HiLoGame = self.game
        for Button, Higher in ((self.Higher, True), (self.Lower, False)):
            Next = Game.Next(Higher)
            Button.disabled = Game.finished or not Next
            Chance = HiLoChance(Game.card[0], Higher)
            Button.label = f"{'Mayor' if Higher else 'Menor'} (x{Next:.2f} · {Chance:.0%})" if Next else ("Mayor" if Higher else "Menor")
        Value = Winnings(Game.bet, Game.Multiplier()) if Game.streak else Game.bet
        self.Cash.label = f"Retirarse ({Value:,})".replace(",", ".")
        self.Cash.disabled = Game.finished

    def Embed(self) -> discord.Embed:
        Game: HiLoGame = self.game
        Shown = f"`{HiLoName(Game.previous)}` → " if Game.previous else ""
        if Game.lost:
            Title, Color = "❌ ¡Fallaste!", discord.Color.red()
            Body = f"Perdiste {FormatAmount(Game.bet, self.config)}"
        elif Game.finished:
            Title, Color = "💰 ¡Te retiraste!", discord.Color.green()
            Body = f"Cobraste {FormatAmount(Game.payout, self.config)}"
        else:
            Title, Color = "🔼 Mayor o menor", discord.Color.blurple()
            Body = f"Racha: **{Game.streak}** · Multiplicador: **x{Game.Multiplier():.2f}**\n-# ¿La siguiente carta será mayor o menor? (si es igual, pierdes)"
        embed = discord.Embed(title=Title, description=f"# {Shown}`{HiLoName(Game.card)}`\n{Body}", color=Color)
        embed.set_author(name=f"{self.member.display_name} apostó {Game.bet:,}".replace(",", "."), icon_url=self.member.display_avatar)
        embed.set_footer(text=EdgeNote(Game.edge, self.luck) + " · A es la más baja, K la más alta")
        return embed

    @discord.ui.button(label="Mayor", emoji="⬆️", style=discord.ButtonStyle.blurple, row=0)
    async def Higher(self, interaction: discord.Interaction, _):
        await self.Act(interaction, lambda: self.game.Guess(True))

    @discord.ui.button(label="Menor", emoji="⬇️", style=discord.ButtonStyle.blurple, row=0)
    async def Lower(self, interaction: discord.Interaction, _):
        await self.Act(interaction, lambda: self.game.Guess(False))

    @discord.ui.button(label="Retirarse", emoji="💰", style=discord.ButtonStyle.green, row=1)
    async def Cash(self, interaction: discord.Interaction, _):
        await self.Act(interaction, self.game.CashOut)


# ---------------- horse race ----------------


def RaceTrack(positions: list[int], length: int, picked: int, winner: int | None = None) -> str:
    Lines = []
    for H, (Name, _) in enumerate(HORSES):
        Position = positions[H]
        Lane = "·" * Position + "🏇" + "·" * (length - Position) + "🏁"
        Mark = "👉" if H == picked else "  "
        Crown = " 🏆" if winner == H else ""
        Lines.append(f"{Mark}`{H + 1}` `{Lane}` {Name}{Crown}")
    return "\n".join(Lines)


def HorseChoices(edge: float) -> str:
    return "\n".join(f"`{i + 1}` {Name} · {Chance:.0%} de ganar · paga x{RaceMultiplier(i, edge):.2f}" for i, (Name, Chance) in enumerate(HORSES))
