"""Buttons and menus for La Larga Marcha (/casino marcha)."""

import asyncio
import io

import discord

from core.economy import marcha as M
from core.economy.marchacards import Table
from core.economy.registry import Eco
from core.economy.rewards import FormatAmount

GAME_TIMEOUT = 15 * 60  # the game stays saved after this: /casino marcha picks it up again
SORTS = {"rank": "🔢 Ordenar por palo", "suit": "🔢 Ordenar por número"}


def SortHand(game: dict):
    if game.get("sort") == "suit":
        game["hand"].sort(key=lambda C: (M.SUITS.index(C[1]), -M.Rank(C)))
    else:
        game["hand"].sort(key=M.Rank, reverse=True)


class CardSelect(discord.ui.Select):
    def __init__(self, view: "MarchaView"):
        Picked = set(view.selected)
        super().__init__(
            placeholder=f"Elige de 1 a {M.MAX_PLAY} cartas",
            min_values=1,
            max_values=M.MAX_PLAY,
            options=[discord.SelectOption(label=M.Label(C), value=C, default=C in Picked) for C in view.game["hand"]],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        View: MarchaView = self.view
        View.selected = list(self.values)
        await View.Update(interaction)


class MarchaView(discord.ui.View):
    def __init__(self, member: discord.Member, game: dict, config: dict, note: str = ""):
        super().__init__(timeout=GAME_TIMEOUT)
        self.member = member
        self.game = game
        self.config = config
        self.note = note
        self.selected: list[str] = []
        self.paid = 0
        self.busy = False
        self.message: discord.Message | None = None
        SortHand(game)
        self.Build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Esa marcha no es tuya 👀", ephemeral=True)
            return False
        if self.busy:
            await interaction.response.defer()
            return False
        return True

    def Build(self, state: str | None = None):
        """Menu and buttons for the current state (none once the game is over)."""
        self.clear_items()
        State = state or self.game["state"]
        if State == "playing":
            self.add_item(CardSelect(self))
            self.add_item(Button("Jugar mano", "▶️", discord.ButtonStyle.red, self.Play, disabled=not self.selected))
            self.add_item(Button(
                f"Descartar ({self.game['discards']})", "🗑️", discord.ButtonStyle.grey, self.Discard,
                disabled=not self.selected or not self.game["discards"],
            ))
            self.add_item(Button(SORTS[self.game.get("sort", "rank")], None, discord.ButtonStyle.grey, self.Sort))
        elif State == "cleared":
            Next = self.game["cleared"]
            self.add_item(Button(f"Cobrar {M.Prize(self.game):,}".replace(",", "."), "💰", discord.ButtonStyle.green, self.CashOut))
            self.add_item(Button(
                f"Seguir a la etapa {Next + 1} (x{M.LADDER[Next]:g})", "⚔️", discord.ButtonStyle.red, self.Continue
            ))

    def Embed(self, state: str | None = None) -> discord.Embed:
        G = self.game
        State = state or G["state"]
        Money = lambda A: FormatAmount(A, self.config)  # noqa: E731
        if State == "playing":
            Text = (
                f"Llega a **{M.TARGETS[G['stage']]:,}** de señal con tus manos.\n".replace(",", ".")
                + f"-# Elige hasta {M.MAX_PLAY} cartas en el menú: la imagen te muestra qué jugada harías."
            )
            Color = discord.Color.from_rgb(150, 12, 18)
        elif State == "cleared":
            Text = (
                f"✅ **Etapa {G['cleared']} superada.** Puedes cobrar {Money(M.Prize(G))} ahora o seguir marchando.\n"
                f"-# Si sigues y no superas la siguiente etapa, lo pierdes todo."
            )
            Color = discord.Color.green()
        elif State in ("won", "cashed"):
            Text = f"💰 Cobraste {Money(self.paid)}."
            if State == "won":
                Text = f"🏆 **¡Completaste la Larga Marcha!** {Text}"
            Color = discord.Color.gold()
        else:
            Text = f"💀 No llegaste a la señal. Pierdes {Money(G['bet'])}.\n-# *\"If I take a thousand steps backwards, when will I arrive?\"*"
            Color = discord.Color.dark_red()
        embed = discord.Embed(title="🃏 La Larga Marcha", description=(self.note + "\n" if self.note else "") + Text, color=Color)
        embed.set_author(name=f"{self.member.display_name} apostó {G['bet']:,}".replace(",", "."), icon_url=self.member.display_avatar)
        embed.set_image(url="attachment://marcha.png")
        embed.set_footer(text="Pareja 10×2 · Doble 20×2 · Trío 30×3 · Escalera 30×4 · Color 35×4 · Full 40×4 · Póker 60×7")
        return embed

    async def Render(self, state: str | None = None) -> tuple[discord.Embed, discord.File]:
        Png = await asyncio.to_thread(Table, self.game, self.selected, state)
        return self.Embed(state), discord.File(io.BytesIO(Png), "marcha.png")

    async def Update(self, interaction: discord.Interaction, state: str | None = None):
        await interaction.response.defer()
        self.Build(state)
        embed, File = await self.Render(state)
        await interaction.edit_original_response(embed=embed, attachments=[File], view=self if self.children else None)

    async def Act(self, interaction: discord.Interaction, action):
        self.busy = True
        try:
            try:
                action()
            except ValueError as e:
                return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            self.selected = []
            self.note = ""
            SortHand(self.game)
            State = self.game["state"]
            if State in ("won", "failed"):
                self.paid = await Eco().marcha.Finish(self.member, self.game, cash_out=State == "won")
                self.stop()
            else:
                await Eco().marcha.Save(self.member.guild.id, self.member.id, self.game)
            await self.Update(interaction)
        finally:
            self.busy = False

    async def Play(self, interaction: discord.Interaction):
        await self.Act(interaction, lambda: M.Play(self.game, self.selected))

    async def Discard(self, interaction: discord.Interaction):
        await self.Act(interaction, lambda: M.Discard(self.game, self.selected))

    async def Sort(self, interaction: discord.Interaction):
        self.game["sort"] = "suit" if self.game.get("sort", "rank") == "rank" else "rank"
        await self.Act(interaction, lambda: None)

    async def Continue(self, interaction: discord.Interaction):
        await self.Act(interaction, lambda: M.NextStage(self.game, Eco().marcha.rng))

    async def CashOut(self, interaction: discord.Interaction):
        self.busy = True
        try:
            self.paid = await Eco().marcha.Finish(self.member, self.game, cash_out=True)
            self.note = ""
            self.stop()
            await self.Update(interaction, "cashed")
        finally:
            self.busy = False


class Button(discord.ui.Button):
    def __init__(self, label: str, emoji, style, handler, disabled: bool = False):
        super().__init__(label=label, emoji=emoji, style=style, disabled=disabled, row=1)
        self.handler = handler

    async def callback(self, interaction: discord.Interaction):
        await self.handler(interaction)
