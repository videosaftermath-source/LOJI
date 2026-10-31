"""Buttons and menus for La Larga Marcha (/casino marcha)."""

import asyncio
import io
import os

import discord

from core.economy import marcha as M
from core.economy.marchacards import ShopPicture, Table
from core.economy.registry import Eco
from core.economy.rewards import FormatAmount

GAME_TIMEOUT = 15 * 60  # the game stays saved after this: /casino marcha picks it up again
SORTS = {"rank": "🔢 Ordenar por palo", "suit": "🔢 Ordenar por número"}
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
BOSS_ART = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "assets", "marcha", "bosses")
HAND_TABLE = "Pareja 10×2 · Doble 20×2 · Trío 30×3 · Escalera 30×4 · Color 35×4 · Full 40×4 · Póker 60×7"


def SortHand(game: dict):
    if game.get("sort") == "suit":
        game["hand"].sort(key=lambda C: (M.SUITS.index(C[1]), -M.Rank(C)))
    else:
        game["hand"].sort(key=M.Rank, reverse=True)


def JokerList(game: dict) -> str:
    return "\n".join(f"{M.JokerInfo(J)['emoji']} **{M.JokerInfo(J)['name']}**: {M.JokerInfo(J)['text']}" for J in game["jokers"]) or "Ninguno todavía."


def OfferText(offer: dict | None) -> str:
    if offer is None:
        return "~~Vendido~~"
    if offer["type"] == "joker":
        Info = M.JokerInfo(offer["id"])
        return f"{Info['emoji']} **{Info['name']}** ({M.JOKER_RARITY_LABELS[Info['rarity']]}): {Info['text']} · **◈{offer['price']}**"
    Label = M.HANDS_TABLE[offer["hand"]][0]
    return f"🛰️ **Actualización: {Label}**: sube un nivel esa jugada · **◈{offer['price']}**"


def BossLine(game: dict, ante: int | None = None) -> str:
    Name, Text, _ = M.BOSSES[M.BossOf(game, ante)]
    return f"**{Name}**: {Text}"


def ShownBoss(game: dict, state: str) -> str | None:
    """Which boss portrait goes in the corner: the one you're fighting or the one coming next."""
    if "bosses" not in game:
        return None
    Last = len(M.BLINDS) - 1
    if state == "playing" and game["blind"] == Last:
        return M.BossOf(game)
    if state == "shop" and game["blind"] == Last - 1:
        return M.BossOf(game)
    return None


def BossFile(boss: str) -> discord.File | None:
    for Ext in ("gif", "png"):
        Path = os.path.join(BOSS_ART, f"{boss}.{Ext}")
        if os.path.exists(Path):
            return discord.File(Path, f"jefe.{Ext}")
    return None


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


class SellSelect(discord.ui.Select):
    def __init__(self, view: "MarchaView"):
        super().__init__(
            placeholder="Vender un comodín",
            options=[
                discord.SelectOption(label=f"Vender {M.JokerInfo(J)['name']} (+◈{M.SellValue(J)})", value=str(i), emoji=M.JokerInfo(J)["emoji"])
                for i, J in enumerate(view.game["jokers"])
            ],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        View: MarchaView = self.view
        Index = int(self.values[0])
        await View.Act(interaction, lambda: M.Sell(View.game, Index))


class Button(discord.ui.Button):
    def __init__(self, label: str, emoji, style, handler, disabled: bool = False, row: int = 1):
        super().__init__(label=label, emoji=emoji, style=style, disabled=disabled, row=row)
        self.handler = handler

    async def callback(self, interaction: discord.Interaction):
        await self.handler(interaction)


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

    # ---- components ----

    def Build(self, state: str | None = None):
        """Menus and buttons for the current state (none once the game is over)."""
        self.clear_items()
        G = self.game
        State = state or G["state"]
        if State == "playing":
            self.add_item(CardSelect(self))
            self.add_item(Button("Jugar mano", "▶️", discord.ButtonStyle.red, self.Play, disabled=not self.selected))
            self.add_item(Button(
                f"Descartar ({G['discards']})", "🗑️", discord.ButtonStyle.grey, self.Discard,
                disabled=not self.selected or not G["discards"],
            ))
            self.add_item(Button(SORTS[G.get("sort", "rank")], None, discord.ButtonStyle.grey, self.Sort))
        elif State == "shop":
            for i, Offer in enumerate(G["shop"]):
                Can = Offer is not None and G["money"] >= Offer["price"]
                Label = f"Comprar {i + 1}" + (f" · ◈{Offer['price']}" if Offer else "")
                self.add_item(Button(Label, "🛒", discord.ButtonStyle.green, self.Buyer(i), disabled=not Can, row=0))
            self.add_item(Button(f"Renovar · ◈{G['reroll']}", "🔄", discord.ButtonStyle.grey, self.Reroll,
                                 disabled=G["money"] < G["reroll"], row=0))
            Ante, Blind = (G["ante"] + 1, 0) if G["blind"] == len(M.BLINDS) - 1 else (G["ante"], G["blind"] + 1)
            Name = M.BOSSES[M.BossOf(G, Ante)][0] if "bosses" in G and Blind == len(M.BLINDS) - 1 else M.BLINDS[Blind][0]
            Next = f"{Name} ({M.Target(Ante, Blind):,})".replace(",", ".")
            self.add_item(Button(f"Siguiente: {Next}", "⚔️", discord.ButtonStyle.red, self.Next, row=0))
            if G["jokers"]:
                self.add_item(SellSelect(self))
        elif State == "ante_cleared":
            self.add_item(Button(f"Cobrar {M.Prize(G):,}".replace(",", "."), "💰", discord.ButtonStyle.green, self.CashOut))
            Next = G["cleared"]
            self.add_item(Button(f"Seguir marchando (jefe del ante {Next + 1}: x{M.LADDER[Next]:g})", "⚔️",
                                 discord.ButtonStyle.red, self.Continue))

    def Embed(self, state: str | None = None) -> discord.Embed:
        G = self.game
        State = state or G["state"]
        Money = lambda A: FormatAmount(A, self.config)  # noqa: E731
        Fields = []
        if State == "playing":
            Boss = "bosses" in G and G["blind"] == len(M.BLINDS) - 1
            Blind = "👹 Jefe" if Boss else M.BLINDS[G["blind"]][0]
            Text = f"**Ante {G['ante'] + 1}/{M.ANTES} · {Blind}**: llega a **{M.Target(G['ante'], G['blind']):,}** de señal.\n".replace(",", ".")
            if Boss:
                Text += f"⚠️ {BossLine(G)}\n"
                if (G.get("last") or {}).get("robbed"):
                    Text += "💸 **Heisenberg se llevó todos tus ◈.**\n"
            elif "bosses" in G:
                Text += f"-# Jefe de este ante: {BossLine(G)}\n"
            Text += "-# Elige cartas en el menú: la imagen te muestra la jugada y se iluminan los comodines que se activan."
            Color = LOJI_RED
            Fields.append(("🃏 Tus comodines", JokerList(G)))
        elif State == "shop":
            Text = "🛒 **Intercambio de datos.** Compra comodines o actualizaciones con tus ◈ y sigue la marcha.\n" + "\n".join(
                f"**[{i + 1}]** {OfferText(O)}" for i, O in enumerate(G["shop"])
            )
            if ShownBoss(G, "shop"):
                Text += f"\n\n👹 **Se acerca el jefe** {BossLine(G)}"
            Color = discord.Color.dark_gold()
            Fields.append(("🃏 Tus comodines", JokerList(G)))
        elif State == "ante_cleared":
            Text = (
                f"✅ **¡Derrotaste al jefe del ante {G['cleared']}!** Puedes cobrar {Money(M.Prize(G))} "
                f"(x{M.LADDER[G['cleared'] - 1]:g}) o seguir marchando.\n"
                f"-# Si sigues y caes, lo pierdes todo. El próximo jefe paga x{M.LADDER[G['cleared']]:g}."
            )
            Color = discord.Color.green()
        elif State in ("won", "cashed"):
            Text = f"💰 Cobraste {Money(self.paid)}."
            if State == "won":
                Text = f"🏆 **¡Completaste la Larga Marcha!** {Text}"
            Color = discord.Color.gold()
        else:
            Text = (
                f"💀 Caíste en el ante {G['ante'] + 1}. Pierdes {Money(G['bet'])}.\n"
                "-# *\"If I take a thousand steps backwards, when will I arrive?\"*"
            )
            Color = discord.Color.dark_red()
        embed = discord.Embed(title="🃏 La Larga Marcha", description=(self.note + "\n" if self.note else "") + Text, color=Color)
        for Name, Value in Fields:
            embed.add_field(name=Name, value=Value[:1024], inline=False)
        embed.set_author(name=f"{self.member.display_name} apostó {G['bet']:,}".replace(",", "."), icon_url=self.member.display_avatar)
        embed.set_image(url="attachment://marcha.png")
        embed.set_footer(text=HAND_TABLE)
        return embed

    async def Render(self, state: str | None = None) -> tuple[discord.Embed, list[discord.File]]:
        State = state or self.game["state"]
        if State == "shop":
            Png = await asyncio.to_thread(ShopPicture, self.game)
        else:
            Png = await asyncio.to_thread(Table, self.game, self.selected, state)
        embed = self.Embed(state)
        Files = [discord.File(io.BytesIO(Png), "marcha.png")]
        Boss = ShownBoss(self.game, State)
        Portrait = BossFile(Boss) if Boss else None
        if Portrait:
            embed.set_thumbnail(url=f"attachment://{Portrait.filename}")
            Files.append(Portrait)
        return embed, Files

    async def Update(self, interaction: discord.Interaction, state: str | None = None):
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.Build(state)
        embed, Files = await self.Render(state)
        await interaction.edit_original_response(embed=embed, attachments=Files, view=self if self.children else None)

    # ---- actions ----

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
        await self.Act(interaction, lambda: M.Play(self.game, self.selected, Eco().marcha.rng))

    async def Discard(self, interaction: discord.Interaction):
        await self.Act(interaction, lambda: M.Discard(self.game, self.selected))

    async def Sort(self, interaction: discord.Interaction):
        self.game["sort"] = "suit" if self.game.get("sort", "rank") == "rank" else "rank"
        await self.Act(interaction, lambda: None)

    def Buyer(self, slot: int):
        async def Handler(interaction: discord.Interaction):
            await self.Act(interaction, lambda: M.Buy(self.game, slot))
        return Handler

    async def Reroll(self, interaction: discord.Interaction):
        await self.Act(interaction, lambda: M.Reroll(self.game, Eco().marcha.rng))

    async def Next(self, interaction: discord.Interaction):
        await self.Act(interaction, lambda: M.NextBlind(self.game, Eco().marcha.rng))

    async def Continue(self, interaction: discord.Interaction):
        await self.Act(interaction, lambda: M.EnterShop(self.game))

    async def CashOut(self, interaction: discord.Interaction):
        self.busy = True
        try:
            self.paid = await Eco().marcha.Finish(self.member, self.game, cash_out=True)
            self.note = ""
            self.stop()
            await self.Update(interaction, "cashed")
        finally:
            self.busy = False
