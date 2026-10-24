"""Admin panels (buttons, selects and forms) for the shop, codes and quests."""

import re
from datetime import datetime, timedelta, timezone

import discord

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis
from core.economy.config import EcoConfig
from core.economy.constants import (
    BOOSTS,
    COLLECTIBLE,
    CONSUMABLE,
    ITEM_TYPES,
    MAX_CODES,
    MAX_ITEMS,
    MAX_QUESTS,
    OBJECTIVES,
    QUEST_PERIODS,
    ROLE,
)
from core.economy.registry import Eco
from core.economy.rewards import Aware, FormatAmount
from core.economy.service import EconomyError
from core.economy.shop import CanGiveRole
from cogs.Modules.Economy.shop import ItemCard, ItemLine

PANEL_TIMEOUT = 900
LEADING_EMOJI = re.compile(r"^(<a?:\w+:\d+>|[^\w\s]{1,8})\s+(.+)$")
MAX_PERCENT = 1000
MAX_MINUTES = 30 * 24 * 60


class InputError(ValueError):
    pass


def Number(raw: str, label: str, minimum: int = 0, optional: bool = False) -> int | None:
    raw = raw.strip().replace(".", "").replace(",", "")
    if not raw:
        if optional:
            return None
        raise InputError(f"Falta **{label}**.")
    if not raw.isdigit() or int(raw) < minimum:
        raise InputError(f"**{label}** tiene que ser un número de {minimum} o más.")
    return int(raw)


def SplitEmoji(name: str) -> tuple[str | None, str]:
    """'🍕 Pizza' -> ('🍕', 'Pizza')."""
    Match = LEADING_EMOJI.match(name.strip())
    return (Match.group(1), Match.group(2)) if Match else (None, name.strip())


class Panel(discord.ui.View):
    """Base: only the admin who opened it can use it."""

    def __init__(self, author: discord.Member):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True


async def Fail(interaction: discord.Interaction, error: Exception):
    await interaction.response.send_message(f"{Emojis.no} {error}", ephemeral=True)


# ======================= SHOP =======================


async def ShopEmbed(guild: discord.Guild) -> discord.Embed:
    Config = await EcoConfig().Get(guild.id)
    Items = await Eco().shop.List(guild.id)
    embed = discord.Embed(title="🛒 Tienda · administración", color=discord.Color.blurple())
    embed.description = (
        "\n".join(("" if I.get("enabled") else "⏸️ ") + ItemLine(I, Config) for I in Items)
        or "No hay items. ¡Crea el primero!"
    )[:4096]
    embed.set_footer(text=f"{len(Items)}/{MAX_ITEMS} items · ⏸️ = pausado (no se vende)")
    return embed


class ShopPanel(Panel):
    def __init__(self, author: discord.Member, items: list[dict]):
        super().__init__(author)
        if items:
            Select = discord.ui.Select(
                placeholder="Gestionar un item",
                options=[discord.SelectOption(label=I["name"][:100], value=I["item_id"], emoji=I.get("emoji") or "📦") for I in items],
            )
            Select.callback = self.Manage
            self.add_item(Select)
        self.Create.disabled = len(items) >= MAX_ITEMS

    @classmethod
    async def Open(cls, interaction: discord.Interaction, author: discord.Member):
        Items = await Eco().shop.List(interaction.guild.id)
        await interaction.response.edit_message(content=None, embed=await ShopEmbed(interaction.guild), view=cls(author, Items))

    async def Manage(self, interaction: discord.Interaction):
        Item = await Eco().shop.Get(interaction.guild.id, interaction.data["values"][0])
        if not Item:
            return await ShopPanel.Open(interaction, self.author)
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.edit_message(embed=ItemCard(Item, Config), view=ItemPanel(self.author, Item))

    @discord.ui.button(label="Crear item", emoji="➕", style=discord.ButtonStyle.green, row=1)
    async def Create(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(ItemInfo(self.author))


class ItemInfo(discord.ui.Modal):
    """Name, description, price, stock and limit. Used to create and to edit."""

    def __init__(self, author: discord.Member, item: dict | None = None):
        super().__init__(title="Editar item" if item else "Nuevo item")
        self.author = author
        self.item = item
        I = item or {}
        Name = f"{I['emoji']} {I['name']}" if I.get("emoji") else I.get("name")
        self.name = discord.ui.TextInput(label="Nombre (puede empezar con un emoji)", default=Name, max_length=60, placeholder="🍕 Pizza mágica")
        self.description = discord.ui.TextInput(label="Descripción", default=I.get("description"), max_length=300, required=False, style=discord.TextStyle.paragraph)
        self.price = discord.ui.TextInput(label="Precio", default=str(I["price"]) if I else None, max_length=12)
        self.stock = discord.ui.TextInput(label="Stock (vacío = infinito)", default=str(I["stock"]) if I.get("stock") is not None else None, max_length=9, required=False)
        self.limit = discord.ui.TextInput(label="Máximo por persona (vacío = sin límite)", default=str(I["per_user_limit"]) if I.get("per_user_limit") else None, max_length=6, required=False)
        for Input in (self.name, self.description, self.price, self.stock, self.limit):
            self.add_item(Input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Emoji, Name = SplitEmoji(self.name.value)
            Data = {
                "name": Name,
                "emoji": Emoji,
                "description": self.description.value.strip(),
                "price": Number(self.price.value, "Precio", 1),
                "stock": Number(self.stock.value, "Stock", 0, optional=True),
                "per_user_limit": Number(self.limit.value, "Máximo por persona", 1, optional=True),
            }
        except InputError as e:
            return await Fail(interaction, e)
        if self.item:
            Item = await Eco().shop.Update(interaction.guild.id, self.item["item_id"], Data)
            Config = await EcoConfig().Get(interaction.guild.id)
            return await interaction.response.edit_message(embed=ItemCard(Item, Config), view=ItemPanel(self.author, Item))
        embed = discord.Embed(
            title=f"{Emoji or '📦'} {Name}",
            description="¿Qué tipo de item es?",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=ItemType(self.author, Data))


class ItemType(Panel):
    def __init__(self, author: discord.Member, draft: dict):
        super().__init__(author)
        self.draft = draft
        Select = discord.ui.Select(
            placeholder="Tipo de item",
            options=[discord.SelectOption(label=L, value=K) for K, L in ITEM_TYPES.items()],
        )
        Select.callback = self.Chosen
        self.add_item(Select)

    async def Chosen(self, interaction: discord.Interaction):
        Kind = interaction.data["values"][0]
        self.draft["type"] = Kind
        if Kind == COLLECTIBLE:
            return await SaveItem(interaction, self.author, self.draft)
        View = Panel(self.author)
        if Kind == ROLE:
            Picker = discord.ui.RoleSelect(placeholder="¿Qué rol da?")

            async def PickRole(i: discord.Interaction):
                Role = Picker.values[0]
                Problem = CanGiveRole(i.guild, Role)
                if Problem:
                    return await Fail(i, Problem)
                self.draft["role_id"] = Role.id
                await SaveItem(i, self.author, self.draft)

            Picker.callback = PickRole
            View.add_item(Picker)
        else:
            Picker = discord.ui.Select(
                placeholder="¿Qué mejora?",
                options=[discord.SelectOption(label=L, value=K) for K, L in BOOSTS.items()],
            )

            async def PickBoost(i: discord.Interaction):
                await i.response.send_modal(EffectInfo(self.author, self.draft, Picker.values[0]))

            Picker.callback = PickBoost
            View.add_item(Picker)
        await interaction.response.edit_message(view=View)


class EffectInfo(discord.ui.Modal, title="Efecto del consumible"):
    percent = discord.ui.TextInput(label="Porcentaje extra (ej. 25 = +25%)", max_length=4, default="25")
    minutes = discord.ui.TextInput(label="Duración en minutos", max_length=6, default="60")

    def __init__(self, author: discord.Member, draft: dict, kind: str, item: dict | None = None):
        super().__init__()
        self.author = author
        self.draft = draft
        self.kind = kind
        self.item = item
        if item:
            self.percent.default = str(round(item["effect"]["value"] * 100))
            self.minutes.default = str(item["effect"]["seconds"] // 60)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Percent = Number(self.percent.value, "Porcentaje", 1)
            Minutes = Number(self.minutes.value, "Duración", 1)
            if Percent > MAX_PERCENT or Minutes > MAX_MINUTES:
                raise InputError(f"Máximo {MAX_PERCENT}% y {MAX_MINUTES // 1440} días.")
        except InputError as e:
            return await Fail(interaction, e)
        Effect = {"kind": self.kind, "value": Percent / 100, "seconds": Minutes * 60}
        if self.item:
            Item = await Eco().shop.Update(interaction.guild.id, self.item["item_id"], {"effect": Effect})
            Config = await EcoConfig().Get(interaction.guild.id)
            return await interaction.response.edit_message(embed=ItemCard(Item, Config), view=ItemPanel(self.author, Item))
        self.draft["effect"] = Effect
        await SaveItem(interaction, self.author, self.draft)


async def SaveItem(interaction: discord.Interaction, author: discord.Member, draft: dict):
    try:
        Item = await Eco().shop.Create(interaction.guild.id, draft)
    except EconomyError as e:
        return await Fail(interaction, e)
    Config = await EcoConfig().Get(interaction.guild.id)
    await interaction.response.edit_message(
        content=f"{Emojis.tick} Item creado.", embed=ItemCard(Item, Config), view=ItemPanel(author, Item)
    )


class ItemPanel(Panel):
    def __init__(self, author: discord.Member, item: dict):
        super().__init__(author)
        self.item = item
        self.Toggle.label = "Pausar" if item.get("enabled") else "Activar"
        self.Toggle.style = discord.ButtonStyle.grey if item.get("enabled") else discord.ButtonStyle.green
        if item["type"] != CONSUMABLE:
            self.remove_item(self.Effect)
        self.confirming = False

    @discord.ui.button(label="Editar", emoji="✏️", style=discord.ButtonStyle.blurple)
    async def Edit(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(ItemInfo(self.author, self.item))

    @discord.ui.button(label="Efecto", emoji="🧪", style=discord.ButtonStyle.blurple)
    async def Effect(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(EffectInfo(self.author, {}, self.item["effect"]["kind"], self.item))

    @discord.ui.button(label="Pausar")
    async def Toggle(self, interaction: discord.Interaction, _):
        Item = await Eco().shop.Update(interaction.guild.id, self.item["item_id"], {"enabled": not self.item.get("enabled")})
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.edit_message(embed=ItemCard(Item, Config), view=ItemPanel(self.author, Item))

    @discord.ui.button(label="Borrar", emoji="🗑️", style=discord.ButtonStyle.red)
    async def Remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.confirming:
            self.confirming = True
            button.label = "¿Seguro? Pulsa otra vez"
            return await interaction.response.edit_message(view=self)
        await Eco().shop.Delete(interaction.guild.id, self.item["item_id"])
        await ShopPanel.Open(interaction, self.author)

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey)
    async def Back(self, interaction: discord.Interaction, _):
        await ShopPanel.Open(interaction, self.author)


# ======================= CODES =======================


def CodeLine(code: dict, items: dict, config: dict) -> str:
    Prizes = [FormatAmount(code["credits"], config)] if code.get("credits") else []
    Prizes += [f"{R['qty']}x {items[R['item_id']]['name']}" for R in code.get("items", []) if R["item_id"] in items]
    Uses = f"{code['uses']}/{code['max_uses']}" if code.get("max_uses") else f"{code['uses']}/∞"
    Expires = discord.utils.format_dt(Aware(code["expires_at"]), "R") if code.get("expires_at") else "nunca"
    return f"`{code['code']}` · {' + '.join(Prizes)}\n-# Usos: {Uses} · Caduca: {Expires}"


async def CodesEmbed(guild: discord.Guild) -> discord.Embed:
    Config = await EcoConfig().Get(guild.id)
    Items = {I["item_id"]: I for I in await Eco().shop.List(guild.id)}
    Codes = await Eco().codes.List(guild.id)
    embed = discord.Embed(title="🎟️ Códigos de canje", color=discord.Color.green())
    embed.description = ("\n".join(CodeLine(C, Items, Config) for C in Codes) or "No hay códigos.")[:4096]
    embed.set_footer(text=f"{len(Codes)}/{MAX_CODES} · Se canjean con /canjear")
    return embed


class CodesPanel(Panel):
    def __init__(self, author: discord.Member, codes: list[dict]):
        super().__init__(author)
        if codes:
            Select = discord.ui.Select(
                placeholder="Borrar un código",
                options=[discord.SelectOption(label=C["code"], value=C["code"]) for C in codes],
            )
            Select.callback = self.Delete
            self.add_item(Select)
        self.Create.disabled = len(codes) >= MAX_CODES

    @classmethod
    async def Open(cls, interaction: discord.Interaction, author: discord.Member, content: str | None = None):
        Codes = await Eco().codes.List(interaction.guild.id)
        await interaction.response.edit_message(content=content, embed=await CodesEmbed(interaction.guild), view=cls(author, Codes))

    async def Delete(self, interaction: discord.Interaction):
        Code = interaction.data["values"][0]
        await Eco().codes.Delete(interaction.guild.id, Code)
        await CodesPanel.Open(interaction, self.author, f"🗑️ Borré `{Code}`.")

    @discord.ui.button(label="Crear código", emoji="➕", style=discord.ButtonStyle.green, row=1)
    async def Create(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(CodeInfo(self.author))


class CodeInfo(discord.ui.Modal, title="Nuevo código"):
    code = discord.ui.TextInput(label="Código (vacío = aleatorio)", max_length=32, required=False, placeholder="HALLOWEEN2026")
    credits = discord.ui.TextInput(label="Créditos que da (0 si solo da un item)", max_length=12, default="500")
    uses = discord.ui.TextInput(label="Usos máximos en total (vacío = infinito)", max_length=7, required=False)
    days = discord.ui.TextInput(label="Caduca en X días (vacío = nunca)", max_length=4, required=False)

    def __init__(self, author: discord.Member):
        super().__init__()
        self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Draft = {
                "code": self.code.value.strip() or None,
                "credits": Number(self.credits.value, "Créditos", 0),
                "max_uses": Number(self.uses.value, "Usos máximos", 1, optional=True),
                "days": Number(self.days.value, "Días", 1, optional=True),
            }
        except InputError as e:
            return await Fail(interaction, e)
        Items = await Eco().shop.List(interaction.guild.id)
        if not Items:
            return await SaveCode(interaction, self.author, Draft, None)
        await interaction.response.edit_message(
            content="¿Quieres que el código también dé un item?", embed=None, view=CodeItem(self.author, Draft, Items)
        )


class CodeItem(Panel):
    def __init__(self, author: discord.Member, draft: dict, items: list[dict]):
        super().__init__(author)
        self.draft = draft
        Select = discord.ui.Select(
            placeholder="Item de premio (1 unidad)",
            options=[discord.SelectOption(label=I["name"][:100], value=I["item_id"], emoji=I.get("emoji") or "📦") for I in items],
        )
        Select.callback = self.Chosen
        self.add_item(Select)

    async def Chosen(self, interaction: discord.Interaction):
        await SaveCode(interaction, self.author, self.draft, interaction.data["values"][0])

    @discord.ui.button(label="Sin item", style=discord.ButtonStyle.grey, row=1)
    async def NoItem(self, interaction: discord.Interaction, _):
        await SaveCode(interaction, self.author, self.draft, None)


async def SaveCode(interaction: discord.Interaction, author: discord.Member, draft: dict, item_id: str | None):
    Expires = datetime.now(timezone.utc) + timedelta(days=draft["days"]) if draft["days"] else None
    try:
        Code = await Eco().codes.Create(
            interaction.guild.id,
            draft["code"],
            draft["credits"],
            [{"item_id": item_id, "qty": 1}] if item_id else [],
            draft["max_uses"],
            Expires,
            interaction.user.id,
        )
    except EconomyError as e:
        return await Fail(interaction, e)
    await CodesPanel.Open(interaction, author, f"{Emojis.tick} Código `{Code['code']}` creado.")


# ======================= QUESTS =======================


async def QuestsEmbed(guild: discord.Guild) -> discord.Embed:
    Config = await EcoConfig().Get(guild.id)
    Items = {I["item_id"]: I for I in await Eco().shop.List(guild.id)}
    Quests = await Eco().quests.List(guild.id)
    Lines = []
    for Q in Quests:
        Reward = [FormatAmount(int(Q["reward"]), Config)] if Q.get("reward") else []
        if Q.get("reward_item") in Items:
            Reward.append(Items[Q["reward_item"]]["name"])
        Lines.append(
            f"{'' if Q.get('enabled') else '⏸️ '}**{Q['name']}** · {QUEST_PERIODS[Q['period']]}\n"
            f"-# {OBJECTIVES[Q['objective']]}: {Q['target']} · Premio: {' + '.join(Reward)}"
        )
    embed = discord.Embed(title="📜 Misiones · administración", color=discord.Color.teal())
    embed.description = ("\n".join(Lines) or "No hay misiones.")[:4096]
    embed.set_footer(text=f"{len(Quests)}/{MAX_QUESTS} · ⏸️ = pausada")
    return embed


class QuestsPanel(Panel):
    def __init__(self, author: discord.Member, quests: list[dict]):
        super().__init__(author)
        if quests:
            Select = discord.ui.Select(
                placeholder="Gestionar una misión",
                options=[discord.SelectOption(label=Q["name"][:100], value=Q["quest_id"]) for Q in quests],
            )
            Select.callback = self.Manage
            self.add_item(Select)
        self.Create.disabled = len(quests) >= MAX_QUESTS

    @classmethod
    async def Open(cls, interaction: discord.Interaction, author: discord.Member, content: str | None = None):
        Quests = await Eco().quests.List(interaction.guild.id)
        await interaction.response.edit_message(content=content, embed=await QuestsEmbed(interaction.guild), view=cls(author, Quests))

    async def Manage(self, interaction: discord.Interaction):
        Quest = next((Q for Q in await Eco().quests.List(interaction.guild.id) if Q["quest_id"] == interaction.data["values"][0]), None)
        if not Quest:
            return await QuestsPanel.Open(interaction, self.author)
        await interaction.response.edit_message(content=f"Misión **{Quest['name']}**", view=QuestPanel(self.author, Quest))

    @discord.ui.button(label="Crear misión", emoji="➕", style=discord.ButtonStyle.green, row=1)
    async def Create(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(QuestInfo(self.author))


class QuestPanel(Panel):
    def __init__(self, author: discord.Member, quest: dict):
        super().__init__(author)
        self.quest = quest
        self.Toggle.label = "Pausar" if quest.get("enabled") else "Activar"
        self.confirming = False

    @discord.ui.button(label="Pausar", style=discord.ButtonStyle.grey)
    async def Toggle(self, interaction: discord.Interaction, _):
        await Eco().quests.Update(interaction.guild.id, self.quest["quest_id"], {"enabled": not self.quest.get("enabled")})
        await QuestsPanel.Open(interaction, self.author)

    @discord.ui.button(label="Borrar", emoji="🗑️", style=discord.ButtonStyle.red)
    async def Remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.confirming:
            self.confirming = True
            button.label = "¿Seguro? Pulsa otra vez"
            return await interaction.response.edit_message(view=self)
        await Eco().quests.Delete(interaction.guild.id, self.quest["quest_id"])
        await QuestsPanel.Open(interaction, self.author, "🗑️ Misión borrada.")

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey)
    async def Back(self, interaction: discord.Interaction, _):
        await QuestsPanel.Open(interaction, self.author)


class QuestInfo(discord.ui.Modal, title="Nueva misión"):
    name = discord.ui.TextInput(label="Nombre", max_length=60, placeholder="Charlatán del día")
    target = discord.ui.TextInput(label="Cantidad objetivo", max_length=9, default="20")
    reward = discord.ui.TextInput(label="Créditos de premio", max_length=12, default="300")

    def __init__(self, author: discord.Member):
        super().__init__()
        self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Draft = {
                "name": self.name.value.strip(),
                "target": Number(self.target.value, "Cantidad objetivo", 1),
                "reward": Number(self.reward.value, "Créditos de premio", 0),
            }
        except InputError as e:
            return await Fail(interaction, e)
        Items = await Eco().shop.List(interaction.guild.id)
        await interaction.response.edit_message(
            content=f"Misión **{Draft['name']}**: elige el tipo, el objetivo y (si quieres) un item de premio.",
            embed=None,
            view=QuestKind(self.author, Draft, Items),
        )


class QuestKind(Panel):
    def __init__(self, author: discord.Member, draft: dict, items: list[dict]):
        super().__init__(author)
        self.draft = {**draft, "period": "daily", "objective": "messages", "reward_item": None}
        self.period = discord.ui.Select(
            options=[discord.SelectOption(label=L, value=K, default=K == "daily") for K, L in QUEST_PERIODS.items()], row=0
        )
        self.objective = discord.ui.Select(
            options=[discord.SelectOption(label=L, value=K, default=K == "messages") for K, L in OBJECTIVES.items()], row=1
        )
        self.period.callback = self.Pick
        self.objective.callback = self.Pick
        self.add_item(self.period)
        self.add_item(self.objective)
        if items:
            self.item = discord.ui.Select(
                placeholder="Item de premio (opcional)",
                min_values=0,
                options=[discord.SelectOption(label=I["name"][:100], value=I["item_id"], emoji=I.get("emoji") or "📦") for I in items],
                row=2,
            )
            self.item.callback = self.Pick
            self.add_item(self.item)

    async def Pick(self, interaction: discord.Interaction):
        # Selects keep their own values; just acknowledge.
        await interaction.response.defer()

    @discord.ui.button(label="Guardar", emoji="💾", style=discord.ButtonStyle.green, row=3)
    async def Save(self, interaction: discord.Interaction, _):
        self.draft["period"] = (self.period.values or ["daily"])[0]
        self.draft["objective"] = (self.objective.values or ["messages"])[0]
        Item = getattr(self, "item", None)
        self.draft["reward_item"] = Item.values[0] if Item and Item.values else None
        try:
            await Eco().quests.Create(interaction.guild.id, self.draft)
        except EconomyError as e:
            return await Fail(interaction, e)
        await QuestsPanel.Open(interaction, self.author, f"{Emojis.tick} Misión creada.")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.grey, row=3)
    async def Cancel(self, interaction: discord.Interaction, _):
        await QuestsPanel.Open(interaction, self.author)
