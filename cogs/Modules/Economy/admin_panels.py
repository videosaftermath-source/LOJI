"""Admin panels (buttons, selects and forms) for the shop, codes and quests."""

import re
from datetime import datetime, timedelta, timezone

import discord

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis
from core.economy.config import EcoConfig
from core.economy.constants import (
    ARCHETYPES,
    BOOSTS,
    COLLECTIBLE,
    CONSUMABLE,
    ITEM_TYPES,
    MAX_CODES,
    MAX_ITEMS,
    MAX_POOL,
    MAX_QUESTS,
    MAX_SPECIES,
    MAX_SPECIES_PER_RARITY,
    OBJECTIVES,
    QUEST_PERIODS,
    RARITIES,
    ROLE,
)
from core.economy.gacha import ORDER, Problems, Status, Now as GachaNow
from core.economy.pets import PerkValue
from core.economy.pet_catalog import StarterDocs
from core.economy.registry import Eco
from core.economy.rewards import Aware, FormatAmount
from core.economy.service import EconomyError
from core.economy.shop import CanGiveRole
from cogs.Modules.Economy.shop import ItemCard, ItemLine
from cogs.Modules.Economy.gacha import PrizeNames

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
    Multiplier = await Eco().shop.Multiplier(guild.id, Config)
    embed = discord.Embed(title="🛒 Tienda · administración", color=discord.Color.blurple())
    embed.description = (
        "\n".join(("" if I.get("enabled") else "⏸️ ") + ItemLine(I, Config, Multiplier) for I in Items)
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

    @discord.ui.button(label="Demanda", emoji="📈", style=discord.ButtonStyle.blurple)
    async def Demand(self, interaction: discord.Interaction, _):
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.send_modal(DemandInfo(self.author, self.item, Config))

    @discord.ui.button(label="Pausar")
    async def Toggle(self, interaction: discord.Interaction, _):
        Item = await Eco().shop.Update(interaction.guild.id, self.item["item_id"], {"enabled": not self.item.get("enabled")})
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.edit_message(embed=ItemCard(Item, Config), view=ItemPanel(self.author, Item))

    @discord.ui.button(label="Hacer exclusiva", emoji="🔒", style=discord.ButtonStyle.grey)
    async def Exclusive(self, interaction: discord.Interaction, _):
        """Exclusive: never evolves and no other species evolves into it (gacha or gift only)."""
        Id, GuildId = self.species_doc["species_id"], interaction.guild.id
        Making = not self.species_doc.get("exclusive")
        Data = {"exclusive": Making}
        if Making:
            Data |= {"evolves_to": None, "evolve_level": None}
            await Eco().pets.species.update_many({"guild_id": GuildId, "evolves_to": Id}, {"$set": {"evolves_to": None, "evolve_level": None}})
        Species = await Eco().pets.UpdateSpecies(GuildId, Id, Data)
        await interaction.response.edit_message(embed=await SpeciesCard(interaction.guild, Species), view=SpeciesItem(self.author, Species))

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


class DemandInfo(discord.ui.Modal, title="Precio por demanda"):
    def __init__(self, author: discord.Member, item: dict, config: dict):
        super().__init__()
        self.author = author
        self.item = item
        Own = item.get("demand") or {}
        Shop_ = config["shop"]
        self.step = discord.ui.TextInput(
            label=f"Subida por compra en % (vacío = {Shop_['demand_step'] * 100:g})",
            default=f"{Own['step'] * 100:g}" if "step" in Own else None, max_length=6, required=False,
        )
        self.half = discord.ui.TextInput(
            label=f"Horas para bajar a la mitad (vacío = {Shop_['demand_half_life']})",
            default=str(Own["half_life"]) if "half_life" in Own else None, max_length=4, required=False,
        )
        self.add_item(self.step)
        self.add_item(self.half)

    async def on_submit(self, interaction: discord.Interaction):
        Set, Unset = {}, {}
        try:
            if self.step.value.strip():
                Step = float(self.step.value.strip().replace(",", ".").rstrip("%"))
                if not 0 <= Step <= 100:
                    raise InputError("La subida tiene que estar entre 0 y 100%.")
                Set["demand.step"] = Step / 100
            else:
                Unset["demand.step"] = ""
            if self.half.value.strip():
                Set["demand.half_life"] = Number(self.half.value, "Horas", 1)
            else:
                Unset["demand.half_life"] = ""
        except (InputError, ValueError) as e:
            return await Fail(interaction, e if isinstance(e, InputError) else "Pon números válidos.")
        Update = {}
        if Set:
            Update["$set"] = Set
        if Unset:
            Update["$unset"] = Unset
        await Eco().shop.items.update_one({"guild_id": interaction.guild.id, "item_id": self.item["item_id"]}, Update)
        Item = await Eco().shop.Get(interaction.guild.id, self.item["item_id"])
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.edit_message(embed=ItemCard(Item, Config), view=ItemPanel(self.author, Item))


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


# ======================= PETS =======================


def SpeciesLine(species: dict, by_id: dict) -> str:
    Evolves = by_id.get(species.get("evolves_to") or "")
    Evo = f" → {Evolves.get('emoji') or ''} {Evolves['name']} (nv. {species['evolve_level']})" if Evolves else ""
    Paused = ("" if species.get("enabled") else "⏸️ ") + ("🔒 " if species.get("exclusive") else "")
    return (
        f"{Paused}{species.get('emoji') or '🐾'} **{species['name']}** · {RARITIES[species['rarity']]['stars']} · "
        f"{ARCHETYPES[species['archetype']]['label']}{Evo}"
    )


def RaritySelects(species: list[dict], verb: str, multiple: bool = False) -> list[discord.ui.Select]:
    """One select per rarity (Discord shows 25 options per menu, and each rarity holds up to 25)."""
    Selects = []
    for Row, (Rarity, Info) in enumerate(RARITIES.items()):
        Options = [
            discord.SelectOption(label=S["name"][:100], value=S["species_id"], emoji=S.get("emoji") or "🐾")
            for S in species if S["rarity"] == Rarity
        ][:MAX_SPECIES_PER_RARITY]
        if Options:
            Selects.append(discord.ui.Select(
                placeholder=f"{verb}: {Info['stars']} {Info['label']}", options=Options, row=Row,
                min_values=1, max_values=len(Options) if multiple else 1,
            ))
    return Selects


def MissingStarters(species: list[dict]) -> int:
    Have = {S["species_id"] for S in species}
    return sum(1 for D in StarterDocs(0) if D["species_id"] not in Have)


async def SpeciesEmbed(guild: discord.Guild) -> discord.Embed:
    All = await Eco().pets.AllSpecies(guild.id)
    ById = {S["species_id"]: S for S in All}
    embed = discord.Embed(title="🐾 Especies de mascotas", color=discord.Color.teal())
    if not All:
        embed.description = "No hay especies. Carga el catálogo de ejemplo o crea una."
    for Rarity, Info in RARITIES.items():
        Lines = [SpeciesLine(S, ById) for S in All if S["rarity"] == Rarity]
        if Lines:
            Text = ""
            for i, Line in enumerate(Lines):
                More = f"\n… y {len(Lines) - i} más"
                if len(Text) + len(Line) + 1 + len(More) > 1024:
                    Text += More
                    break
                Text += ("\n" if Text else "") + Line
            embed.add_field(name=f"{Info['stars']} {Info['label']} ({len(Lines)}/{MAX_SPECIES_PER_RARITY})", value=Text, inline=False)
    embed.set_footer(text=f"{len(All)}/{MAX_SPECIES} · 🔒 = exclusiva · ⏸️ = pausada (no sale en el gacha) · Regala con /eco-admin regalar-mascota")
    return embed


class SpeciesPanel(Panel):
    def __init__(self, author: discord.Member, species: list[dict]):
        super().__init__(author)
        for Select in RaritySelects(species, "Gestionar"):
            Select.callback = self.Manage
            self.add_item(Select)
        self.Create.disabled = len(species) >= MAX_SPECIES
        Missing = MissingStarters(species)
        if Missing:
            self.Seed.label = f"Cargar catálogo de ejemplo ({Missing})" if species else self.Seed.label
        else:
            self.remove_item(self.Seed)

    @classmethod
    async def Open(cls, interaction: discord.Interaction, author: discord.Member, content: str | None = None):
        All = await Eco().pets.AllSpecies(interaction.guild.id)
        await interaction.response.edit_message(content=content, embed=await SpeciesEmbed(interaction.guild), view=cls(author, All))

    async def Manage(self, interaction: discord.Interaction):
        Species = await Eco().pets.GetSpecies(interaction.guild.id, interaction.data["values"][0])
        if not Species:
            return await SpeciesPanel.Open(interaction, self.author)
        await interaction.response.edit_message(content=None, embed=await SpeciesCard(interaction.guild, Species), view=SpeciesItem(self.author, Species))

    @discord.ui.button(label="Crear especie", emoji="➕", style=discord.ButtonStyle.green, row=4)
    async def Create(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(SpeciesInfo(self.author))

    @discord.ui.button(label="Cargar catálogo de ejemplo", emoji="📦", style=discord.ButtonStyle.blurple, row=4)
    async def Seed(self, interaction: discord.Interaction, _):
        try:
            Added = await Eco().pets.SeedStarter(interaction.guild.id)
        except EconomyError as e:
            return await Fail(interaction, e)
        await SpeciesPanel.Open(interaction, self.author, f"{Emojis.tick} Añadí {Added} especies.")


async def SpeciesCard(guild: discord.Guild, species: dict) -> discord.Embed:
    Config = await EcoConfig().Get(guild.id)
    Rarity, Archetype = RARITIES[species["rarity"]], ARCHETYPES[species["archetype"]]
    MaxLevel = Config["pets"]["max_level"]
    embed = discord.Embed(
        title=f"{species.get('emoji') or '🐾'} {species['name']}",
        description=species.get("description") or "*Sin descripción.*",
        color=Rarity["color"],
    )
    embed.add_field(name="Rareza", value=f"{Rarity['stars']} {Rarity['label']}")
    embed.add_field(name="Arquetipo", value=Archetype["label"])
    embed.add_field(
        name="Perk",
        value=f"Nivel 1: +{PerkValue(species, 1):.1%} · Nivel {MaxLevel}: +{PerkValue(species, MaxLevel):.1%}\n-# {Archetype['perk']} (antes de topes)",
        inline=False,
    )
    Target = await Eco().pets.GetSpecies(guild.id, species.get("evolves_to") or "")
    embed.add_field(
        name="Evolución",
        value=(
            "🔒 **Exclusiva**: no evoluciona y ninguna otra evoluciona en ella. Solo sale en el gacha (o regalándola)."
            if species.get("exclusive")
            else f"→ {Target.get('emoji') or ''} {Target['name']} al nivel {species['evolve_level']}" if Target else "No evoluciona"
        ),
        inline=False,
    )
    if species.get("image"):
        embed.set_thumbnail(url=species["image"])
    embed.set_footer(text=f"ID: {species['species_id']} · {'Activa' if species.get('enabled') else 'Pausada'}")
    return embed


class SpeciesInfo(discord.ui.Modal):
    def __init__(self, author: discord.Member, species: dict | None = None):
        super().__init__(title="Editar especie" if species else "Nueva especie")
        self.author = author
        self.species_doc = species
        S = species or {}
        Name = f"{S['emoji']} {S['name']}" if S.get("emoji") else S.get("name")
        self.name = discord.ui.TextInput(label="Nombre (puede empezar con un emoji)", default=Name, max_length=50, placeholder="🐹 Hámster Currante")
        self.description = discord.ui.TextInput(label="Descripción", default=S.get("description"), max_length=200, required=False, style=discord.TextStyle.paragraph)
        self.image = discord.ui.TextInput(label="Imagen (URL, opcional)", default=S.get("image"), max_length=300, required=False)
        for Input in (self.name, self.description, self.image):
            self.add_item(Input)

    async def on_submit(self, interaction: discord.Interaction):
        Emoji, Name = SplitEmoji(self.name.value)
        Image = self.image.value.strip() or None
        if Image and not Image.startswith(("http://", "https://")):
            return await Fail(interaction, "La imagen tiene que ser un enlace (https://...).")
        Data = {"name": Name, "emoji": Emoji, "description": self.description.value.strip(), "image": Image}
        if self.species_doc:
            Species = await Eco().pets.UpdateSpecies(interaction.guild.id, self.species_doc["species_id"], Data)
            return await interaction.response.edit_message(embed=await SpeciesCard(interaction.guild, Species), view=SpeciesItem(self.author, Species))
        await interaction.response.edit_message(
            content=f"**{Emoji or '🐾'} {Name}**: elige rareza y arquetipo.", embed=None, view=SpeciesKind(self.author, Data)
        )


class SpeciesKind(Panel):
    def __init__(self, author: discord.Member, draft: dict):
        super().__init__(author)
        self.draft = draft
        self.rarity = discord.ui.Select(placeholder="Rareza", options=[discord.SelectOption(label=f"{R['stars']} {R['label']}", value=K) for K, R in RARITIES.items()], row=0)
        self.archetype = discord.ui.Select(placeholder="Arquetipo", options=[discord.SelectOption(label=A["label"], value=K, description=A["perk"][:100]) for K, A in ARCHETYPES.items()], row=1)
        for Select in (self.rarity, self.archetype):
            Select.callback = self.Pick
            self.add_item(Select)

    async def Pick(self, interaction: discord.Interaction):
        await interaction.response.defer()

    @discord.ui.button(label="Guardar", emoji="💾", style=discord.ButtonStyle.green, row=2)
    async def Save(self, interaction: discord.Interaction, _):
        if not self.rarity.values or not self.archetype.values:
            return await Fail(interaction, "Elige la rareza y el arquetipo.")
        try:
            Species = await Eco().pets.CreateSpecies(
                interaction.guild.id, {**self.draft, "rarity": self.rarity.values[0], "archetype": self.archetype.values[0]}
            )
        except EconomyError as e:
            return await Fail(interaction, e)
        await interaction.response.edit_message(
            content=f"{Emojis.tick} Especie creada.", embed=await SpeciesCard(interaction.guild, Species), view=SpeciesItem(self.author, Species)
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.grey, row=2)
    async def Cancel(self, interaction: discord.Interaction, _):
        await SpeciesPanel.Open(interaction, self.author)


class SpeciesItem(Panel):
    def __init__(self, author: discord.Member, species: dict):
        super().__init__(author)
        self.species_doc = species
        self.Toggle.label = "Pausar" if species.get("enabled") else "Activar"
        self.Exclusive.label = "Quitar exclusiva" if species.get("exclusive") else "Hacer exclusiva"
        self.Evolution.disabled = bool(species.get("exclusive"))
        self.confirming = False

    @discord.ui.button(label="Editar", emoji="✏️", style=discord.ButtonStyle.blurple)
    async def Edit(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(SpeciesInfo(self.author, self.species_doc))

    @discord.ui.button(label="Evolución", emoji="✨", style=discord.ButtonStyle.blurple)
    async def Evolution(self, interaction: discord.Interaction, _):
        Others = [
            S for S in await Eco().pets.AllSpecies(interaction.guild.id)
            if S["species_id"] != self.species_doc["species_id"] and not S.get("exclusive")
        ]
        await interaction.response.edit_message(view=EvolutionPicker(self.author, self.species_doc, Others))

    @discord.ui.button(label="Pausar", style=discord.ButtonStyle.grey)
    async def Toggle(self, interaction: discord.Interaction, _):
        Species = await Eco().pets.UpdateSpecies(interaction.guild.id, self.species_doc["species_id"], {"enabled": not self.species_doc.get("enabled")})
        await interaction.response.edit_message(embed=await SpeciesCard(interaction.guild, Species), view=SpeciesItem(self.author, Species))

    @discord.ui.button(label="Borrar", emoji="🗑️", style=discord.ButtonStyle.red)
    async def Remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.confirming:
            self.confirming = True
            button.label = "¿Seguro? Pulsa otra vez"
            return await interaction.response.edit_message(view=self)
        try:
            await Eco().pets.DeleteSpecies(interaction.guild.id, self.species_doc["species_id"])
        except EconomyError as e:
            return await Fail(interaction, e)
        await SpeciesPanel.Open(interaction, self.author, "🗑️ Especie borrada.")

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey)
    async def Back(self, interaction: discord.Interaction, _):
        await SpeciesPanel.Open(interaction, self.author)


class EvolutionPicker(Panel):
    def __init__(self, author: discord.Member, species: dict, others: list[dict]):
        super().__init__(author)
        self.species_doc = species
        for Select in RaritySelects(others, "Evoluciona en"):
            Select.callback = self.Pick
            self.add_item(Select)
        NoEvolution = discord.ui.Button(label="Sin evolución", emoji="🚫", style=discord.ButtonStyle.grey, row=4)
        NoEvolution.callback = self.Clear
        self.add_item(NoEvolution)

    async def Clear(self, interaction: discord.Interaction):
        Species = await Eco().pets.UpdateSpecies(interaction.guild.id, self.species_doc["species_id"], {"evolves_to": None, "evolve_level": None})
        await interaction.response.edit_message(embed=await SpeciesCard(interaction.guild, Species), view=SpeciesItem(self.author, Species))

    async def Pick(self, interaction: discord.Interaction):
        Target = interaction.data["values"][0]
        await interaction.response.send_modal(EvolutionLevel(self.author, self.species_doc, Target))


class EvolutionLevel(discord.ui.Modal, title="Nivel de evolución"):
    level = discord.ui.TextInput(label="¿A qué nivel evoluciona?", max_length=3, default="10")

    def __init__(self, author: discord.Member, species: dict, target: str):
        super().__init__()
        self.author = author
        self.species_doc = species
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        Config = await EcoConfig().Get(interaction.guild.id)
        try:
            Level = Number(self.level.value, "Nivel", 2)
            if Level > Config["pets"]["max_level"]:
                raise InputError(f"El nivel máximo es {Config['pets']['max_level']}.")
        except InputError as e:
            return await Fail(interaction, e)
        Species = await Eco().pets.UpdateSpecies(interaction.guild.id, self.species_doc["species_id"], {"evolves_to": self.target, "evolve_level": Level})
        await interaction.response.edit_message(embed=await SpeciesCard(interaction.guild, Species), view=SpeciesItem(self.author, Species))


# ======================= GACHA =======================

STATUS_LABEL = {"active": "🟢 Activo", "scheduled": "🕓 Programado", "ended": "⚫ Terminado", "paused": "⏸️ Pausado"}
RARITY_OPTIONS = [discord.SelectOption(label=f"{R['stars']} {R['label']}", value=K) for K, R in RARITIES.items()]


async def BannersEmbed(guild: discord.Guild) -> discord.Embed:
    Banners = await Eco().gacha.List(guild.id)
    Now_ = GachaNow()
    embed = discord.Embed(title="🎰 Banners del gacha", color=discord.Color.gold())
    embed.description = "\n".join(
        f"{STATUS_LABEL[Status(B, Now_)]} **{B['name']}** · {len(B['pool'])} premios · "
        f"{discord.utils.format_dt(Aware(B['start']), 'd')} → {discord.utils.format_dt(Aware(B['end']), 'd')}"
        for B in Banners
    ) or "No hay banners. ¡Crea uno!"
    embed.set_footer(text="Un banner nuevo empieza pausado: añade premios de las 4 rarezas y actívalo.")
    return embed


class BannersPanel(Panel):
    def __init__(self, author: discord.Member, banners: list[dict]):
        super().__init__(author)
        if banners:
            Select = discord.ui.Select(
                placeholder="Gestionar un banner",
                options=[discord.SelectOption(label=B["name"][:100], value=B["banner_id"]) for B in banners],
            )
            Select.callback = self.Manage
            self.add_item(Select)

    @classmethod
    async def Open(cls, interaction: discord.Interaction, author: discord.Member, content: str | None = None):
        Banners = await Eco().gacha.List(interaction.guild.id)
        await interaction.response.edit_message(content=content, embed=await BannersEmbed(interaction.guild), view=cls(author, Banners))

    async def Manage(self, interaction: discord.Interaction):
        await ShowBanner(interaction, self.author, interaction.data["values"][0])

    @discord.ui.button(label="Crear banner", emoji="➕", style=discord.ButtonStyle.green, row=1)
    async def Create(self, interaction: discord.Interaction, _):
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.send_modal(BannerInfo(self.author, None, Config["gacha"]["cost"]))


async def BannerCard(guild: discord.Guild, banner: dict) -> discord.Embed:
    Config = await EcoConfig().Get(guild.id)
    Names = await PrizeNames(guild.id, banner["pool"], Config)
    embed = discord.Embed(title=f"🎰 {banner['name']}", description=banner.get("description") or None, color=discord.Color.gold())
    embed.add_field(name="Estado", value=STATUS_LABEL[Status(banner, GachaNow())])
    embed.add_field(name="Precio", value=FormatAmount(banner["cost"], Config))
    embed.add_field(
        name="Fechas",
        value=f"{discord.utils.format_dt(Aware(banner['start']), 'f')}\n→ {discord.utils.format_dt(Aware(banner['end']), 'f')}",
    )
    for Rarity in reversed(ORDER):
        Lines = [("🌟 " if P.get("featured") else "") + Names[P["key"]] for P in banner["pool"] if P["rarity"] == Rarity]
        embed.add_field(
            name=f"{RARITIES[Rarity]['stars']} {RARITIES[Rarity]['label']} ({len(Lines)})",
            value="\n".join(Lines)[:1024] or "*vacío*",
            inline=False,
        )
    Issues = Problems(banner)
    if Issues:
        embed.add_field(name="⚠️ Para activarlo", value="\n".join(Issues), inline=False)
    embed.set_footer(text=f"{len(banner['pool'])}/{MAX_POOL} premios · 🌟 = destacado (50/50)")
    return embed


async def ShowBanner(interaction: discord.Interaction, author: discord.Member, banner_id: str, content: str | None = None):
    Banner = await Eco().gacha.Get(interaction.guild.id, banner_id)
    if not Banner:
        return await BannersPanel.Open(interaction, author)
    await interaction.response.edit_message(content=content, embed=await BannerCard(interaction.guild, Banner), view=BannerPanel(author, Banner))


class BannerInfo(discord.ui.Modal):
    def __init__(self, author: discord.Member, banner: dict | None, default_cost: int):
        super().__init__(title="Editar banner" if banner else "Nuevo banner")
        self.author = author
        self.banner = banner
        B = banner or {}
        self.name = discord.ui.TextInput(label="Nombre", default=B.get("name"), max_length=50, placeholder="Banner del Dragón")
        self.description = discord.ui.TextInput(label="Descripción", default=B.get("description"), max_length=300, required=False, style=discord.TextStyle.paragraph)
        self.cost = discord.ui.TextInput(label="Precio por tirada", default=str(B.get("cost", default_cost)), max_length=10)
        self.add_item(self.name)
        self.add_item(self.description)
        self.add_item(self.cost)
        if not banner:
            self.start = discord.ui.TextInput(label="Empieza dentro de X días (0 = ya)", default="0", max_length=3)
            self.add_item(self.start)
        Left = None
        if banner:
            Left = max(1, round((Aware(banner["end"]) - datetime.now(timezone.utc)).total_seconds() / 86400))
        self.days = discord.ui.TextInput(label="Dura X días" if not banner else "Termina dentro de X días", default=str(Left or 14), max_length=4)
        self.add_item(self.days)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Cost = Number(self.cost.value, "Precio", 1)
            Days = Number(self.days.value, "Días", 1)
            Start = Number(self.start.value, "Empieza", 0) if not self.banner else None
        except InputError as e:
            return await Fail(interaction, e)
        Now_ = datetime.now(timezone.utc)
        Data = {"name": self.name.value.strip(), "description": self.description.value.strip(), "cost": Cost}
        if self.banner:
            Data["end"] = Now_ + timedelta(days=Days)
            await Eco().gacha.Update(interaction.guild.id, self.banner["banner_id"], Data)
            return await ShowBanner(interaction, self.author, self.banner["banner_id"])
        Begin = Now_ + timedelta(days=Start)
        try:
            Banner = await Eco().gacha.Create(interaction.guild.id, {**Data, "start": Begin, "end": Begin + timedelta(days=Days)})
        except EconomyError as e:
            return await Fail(interaction, e)
        await ShowBanner(interaction, self.author, Banner["banner_id"], f"{Emojis.tick} Banner creado. Añádele premios.")


class BannerPanel(Panel):
    def __init__(self, author: discord.Member, banner: dict):
        super().__init__(author)
        self.banner = banner
        self.Toggle.label = "Pausar" if banner.get("enabled") else "Activar"
        self.Toggle.style = discord.ButtonStyle.grey if banner.get("enabled") else discord.ButtonStyle.green
        HasPool = bool(banner["pool"])
        self.Featured.disabled = not any(P["rarity"] in ("epic", "legendary") for P in banner["pool"])
        self.RemovePrize.disabled = not HasPool
        self.confirming = False

    async def Reload(self, interaction: discord.Interaction, content: str | None = None):
        await ShowBanner(interaction, self.author, self.banner["banner_id"], content)

    async def Sub(self, interaction: discord.Interaction, view: "Panel", content: str):
        await interaction.response.edit_message(content=content, view=view)

    @discord.ui.button(label="Editar", emoji="✏️", style=discord.ButtonStyle.blurple, row=0)
    async def Edit(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(BannerInfo(self.author, self.banner, self.banner["cost"]))

    @discord.ui.button(label="Mascotas", emoji="🐾", style=discord.ButtonStyle.blurple, row=0)
    async def AddPets(self, interaction: discord.Interaction, _):
        Species = [S for S in await Eco().pets.AllSpecies(interaction.guild.id) if S.get("enabled")]
        if not Species:
            return await Fail(interaction, "No hay especies activas. Créalas en `/eco-admin mascotas`.")
        View = Panel(self.author)
        ById = {S["species_id"]: S for S in Species}
        for Select in RaritySelects(Species, "Añadir", multiple=True):

            async def Pick(i: discord.Interaction, Select=Select):
                await self.Add(i, [{"type": "pet", "ref": V, "rarity": ById[V]["rarity"]} for V in Select.values])

            Select.callback = Pick
            View.add_item(Select)
        await self.Sub(interaction, View, "¿Qué mascotas entran en el banner?")

    @discord.ui.button(label="Item", emoji="📦", style=discord.ButtonStyle.blurple, row=0)
    async def AddItem(self, interaction: discord.Interaction, _):
        Items = [I for I in await Eco().shop.List(interaction.guild.id) if I["type"] != ROLE]
        if not Items:
            return await Fail(interaction, "No hay items (que no sean roles). Créalos en `/eco-admin tienda`.")
        View = Panel(self.author)
        ItemSelect = discord.ui.Select(placeholder="Item", options=[discord.SelectOption(label=I["name"][:100], value=I["item_id"], emoji=I.get("emoji") or "📦") for I in Items[:25]], row=0)
        RaritySelect = discord.ui.Select(placeholder="Rareza en el banner", options=RARITY_OPTIONS, row=1)

        async def Ack(i: discord.Interaction):
            await i.response.defer()

        ItemSelect.callback = Ack
        RaritySelect.callback = Ack
        Save = discord.ui.Button(label="Añadir", emoji="💾", style=discord.ButtonStyle.green, row=2)

        async def DoSave(i: discord.Interaction):
            if not ItemSelect.values or not RaritySelect.values:
                return await Fail(i, "Elige el item y la rareza.")
            await self.Add(i, [{"type": "item", "ref": ItemSelect.values[0], "rarity": RaritySelect.values[0]}])

        Save.callback = DoSave
        for Item in (ItemSelect, RaritySelect, Save):
            View.add_item(Item)
        await self.Sub(interaction, View, "Elige el item y con qué rareza sale.")

    @discord.ui.button(label="Créditos", emoji="🪙", style=discord.ButtonStyle.blurple, row=0)
    async def AddCredits(self, interaction: discord.Interaction, _):
        View = Panel(self.author)
        Select = discord.ui.Select(placeholder="Rareza del premio", options=RARITY_OPTIONS)

        async def Pick(i: discord.Interaction):
            await i.response.send_modal(CreditsPrize(self, Select.values[0]))

        Select.callback = Pick
        View.add_item(Select)
        await self.Sub(interaction, View, "¿Con qué rareza sale este premio de créditos?")

    @discord.ui.button(label="Autocompletar", emoji="🪄", style=discord.ButtonStyle.grey, row=0)
    async def Fill(self, interaction: discord.Interaction, _):
        Before = len(self.banner["pool"])
        try:
            Banner = await Eco().gacha.FillMissing(interaction.guild.id, self.banner["banner_id"])
        except EconomyError as e:
            return await Fail(interaction, e)
        Added = len(Banner["pool"]) - Before
        await self.Reload(interaction, f"🪄 Añadí {Added} premio(s) de créditos a las rarezas vacías." if Added else "Todas las rarezas ya tienen premios 👌")

    @discord.ui.button(label="Destacados", emoji="🌟", style=discord.ButtonStyle.blurple, row=1)
    async def Featured(self, interaction: discord.Interaction, _):
        Config = await EcoConfig().Get(interaction.guild.id)
        Names = await PrizeNames(interaction.guild.id, self.banner["pool"], Config)
        Options = [
            discord.SelectOption(label=Names[P["key"]][:100], value=P["key"], description=RARITIES[P["rarity"]]["label"], default=bool(P.get("featured")))
            for P in self.banner["pool"]
            if P["rarity"] in ("epic", "legendary")
        ]
        View = Panel(self.author)
        Select = discord.ui.Select(placeholder="Premios destacados (50/50)", min_values=0, max_values=len(Options), options=Options)

        async def Pick(i: discord.Interaction):
            await Eco().gacha.SetFeatured(i.guild.id, self.banner["banner_id"], Select.values)
            await ShowBanner(i, self.author, self.banner["banner_id"], "🌟 Destacados guardados.")

        Select.callback = Pick
        View.add_item(Select)
        await self.Sub(interaction, View, "Marca los destacados. Al sacar una épica o legendaria hay un 50/50 de que sea destacada; si no lo es, la siguiente lo será seguro.")

    @discord.ui.button(label="Quitar premio", emoji="➖", style=discord.ButtonStyle.grey, row=1)
    async def RemovePrize(self, interaction: discord.Interaction, _):
        Config = await EcoConfig().Get(interaction.guild.id)
        Names = await PrizeNames(interaction.guild.id, self.banner["pool"], Config)
        View = Panel(self.author)
        Select = discord.ui.Select(
            placeholder="¿Cuál quitas?",
            options=[discord.SelectOption(label=Names[P["key"]][:100], value=P["key"], description=RARITIES[P["rarity"]]["label"]) for P in self.banner["pool"]],
        )

        async def Pick(i: discord.Interaction):
            await Eco().gacha.RemovePrize(i.guild.id, self.banner["banner_id"], Select.values[0])
            await ShowBanner(i, self.author, self.banner["banner_id"], "➖ Premio quitado.")

        Select.callback = Pick
        View.add_item(Select)
        await self.Sub(interaction, View, "Elige el premio a quitar.")

    @discord.ui.button(label="Activar", row=1)
    async def Toggle(self, interaction: discord.Interaction, _):
        try:
            await Eco().gacha.SetEnabled(interaction.guild.id, self.banner["banner_id"], not self.banner.get("enabled"))
        except EconomyError as e:
            return await Fail(interaction, e)
        await self.Reload(interaction)

    @discord.ui.button(label="Borrar", emoji="🗑️", style=discord.ButtonStyle.red, row=1)
    async def Remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.confirming:
            self.confirming = True
            button.label = "¿Seguro? Pulsa otra vez"
            return await interaction.response.edit_message(view=self)
        await Eco().gacha.Delete(interaction.guild.id, self.banner["banner_id"])
        await BannersPanel.Open(interaction, self.author, "🗑️ Banner borrado.")

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=1)
    async def Back(self, interaction: discord.Interaction, _):
        await BannersPanel.Open(interaction, self.author)

    async def Add(self, interaction: discord.Interaction, prizes: list[dict]):
        try:
            await Eco().gacha.AddPrizes(interaction.guild.id, self.banner["banner_id"], prizes)
        except EconomyError as e:
            return await Fail(interaction, e)
        await self.Reload(interaction, f"{Emojis.tick} Premio(s) añadido(s).")


class CreditsPrize(discord.ui.Modal, title="Premio de créditos"):
    amount = discord.ui.TextInput(label="¿Cuántos créditos?", max_length=10, default="500")

    def __init__(self, panel: BannerPanel, rarity: str):
        super().__init__()
        self.panel = panel
        self.rarity = rarity

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Amount = Number(self.amount.value, "Créditos", 1)
        except InputError as e:
            return await Fail(interaction, e)
        await self.panel.Add(interaction, [{"type": "credits", "amount": Amount, "rarity": self.rarity}])
