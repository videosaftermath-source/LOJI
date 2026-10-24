import discord
from discord import app_commands
from discord.ext import commands

from core.bot.Module import ModuleIsEnabled
from core.bot.emojis import Emojis
from core.economy.config import EcoConfig
from core.economy.constants import BOOSTS, CONSUMABLE, ITEM_TYPES, MAX_BUY_AT_ONCE, MODULE, ROLE
from core.economy.registry import Eco
from core.economy.rewards import Aware, FormatAmount
from core.economy.service import EconomyError, InsufficientFunds
from core.economy.shop import DemandBump, Price

VIEW_TIMEOUT = 600


def Duration(seconds: int) -> str:
    Minutes = seconds // 60
    if Minutes < 60:
        return f"{Minutes} min"
    Hours, Rest = divmod(Minutes, 60)
    return f"{Hours} h" + (f" {Rest} min" if Rest else "")


def Perk(item: dict) -> str:
    """What the item does, in one line."""
    if item["type"] == ROLE:
        return f"Te da el rol <@&{item.get('role_id')}>"
    if item["type"] == CONSUMABLE:
        E = item["effect"]
        return f"+{E['value']:.0%} en {BOOSTS[E['kind']].split(' ', 1)[1].lower()} durante {Duration(E['seconds'])}"
    return "Coleccionable: para presumir 😎"


def ItemLine(item: dict, config: dict, multiplier: float = 1.0) -> str:
    Stock = "" if item.get("stock") is None else f" · 📦 {item['stock']} en stock" if item["stock"] > 0 else " · ❌ agotado"
    return f"{item.get('emoji') or '📦'} **{item['name']}** — {FormatAmount(Price(item, config, multiplier=multiplier), config)}{Stock}{Trend(item, config)}\n-# {Perk(item)}"


def Trend(item: dict, config: dict) -> str:
    """📈 when recent purchases pushed the price up."""
    Bump = DemandBump(item, config)
    return f" · 📈 +{Bump:.0%} por demanda" if Bump >= 0.01 else ""


def ItemCard(item: dict, config: dict, multiplier: float | None = None) -> discord.Embed:
    """Item details. With `multiplier` it shows the live price; without, the base price (admin view)."""
    embed = discord.Embed(
        title=f"{item.get('emoji') or '📦'} {item['name']}",
        description=item.get("description") or "*Sin descripción.*",
        color=discord.Color.blurple(),
    )
    if multiplier is None:
        embed.add_field(name="Precio base", value=FormatAmount(int(item["price"]), config) + Trend(item, config))
    else:
        embed.add_field(name="Precio", value=FormatAmount(Price(item, config, multiplier=multiplier), config) + Trend(item, config))
    embed.add_field(name="Tipo", value=ITEM_TYPES[item["type"]])
    embed.add_field(name="Qué hace", value=Perk(item), inline=False)
    Extra = []
    if item.get("stock") is not None:
        Extra.append(f"📦 Stock: {item['stock']}")
    if item.get("per_user_limit"):
        Extra.append(f"👤 Máximo {item['per_user_limit']} por persona")
    if Extra:
        embed.set_footer(text=" · ".join(Extra))
    return embed


async def DoBuy(interaction: discord.Interaction, item_id: str, qty: int):
    Config = await EcoConfig().Get(interaction.guild.id)
    try:
        Item, Total, Account = await Eco().shop.Buy(interaction.user, item_id, qty, Config)
    except InsufficientFunds as e:
        return await interaction.response.send_message(
            f"{Emojis.no} No te alcanza 💀 Tienes {FormatAmount(e.balance, Config)}.", ephemeral=True
        )
    except EconomyError as e:
        return await interaction.response.send_message(f"{Emojis.no} {e}", ephemeral=True)
    interaction.client.dispatch("economy_progress", interaction.guild.id, interaction.user.id, "spend", Total)
    interaction.client.dispatch("economy_progress", interaction.guild.id, interaction.user.id, "buy", qty)
    Tip = "\n-# Úsalo con `/usar`." if Item["type"] == CONSUMABLE else ""
    await interaction.response.send_message(
        f"🛍️ Compraste **{qty}x {Item['name']}** por {FormatAmount(Total, Config)}. Te quedan {FormatAmount(Account['balance'], Config)}.{Tip}",
        ephemeral=True,
    )


class Quantity(discord.ui.Modal, title="¿Cuántos quieres?"):
    qty = discord.ui.TextInput(label=f"Cantidad (1-{MAX_BUY_AT_ONCE})", max_length=3, default="2")

    def __init__(self, item_id: str):
        super().__init__()
        self.item_id = item_id

    async def on_submit(self, interaction: discord.Interaction):
        if not self.qty.value.isdigit():
            return await interaction.response.send_message(f"{Emojis.no} Pon un número.", ephemeral=True)
        await DoBuy(interaction, self.item_id, int(self.qty.value))


class ItemView(discord.ui.View):
    def __init__(self, item: dict):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.item_id = item["item_id"]
        if item["type"] == ROLE:
            self.remove_item(self.BuyMany)

    @discord.ui.button(label="Comprar", emoji="🛒", style=discord.ButtonStyle.green)
    async def BuyOne(self, interaction: discord.Interaction, _):
        await DoBuy(interaction, self.item_id, 1)

    @discord.ui.button(label="Comprar varios", style=discord.ButtonStyle.grey)
    async def BuyMany(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(Quantity(self.item_id))


class ShopSelect(discord.ui.Select):
    def __init__(self, items: list[dict]):
        super().__init__(
            placeholder="Elige un item para verlo o comprarlo",
            options=[
                discord.SelectOption(label=I["name"][:100], value=I["item_id"], emoji=I.get("emoji") or "📦")
                for I in items
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        Item = await Eco().shop.Get(interaction.guild.id, self.values[0])
        if not Item or not Item.get("enabled"):
            return await interaction.response.send_message("Ese item ya no está a la venta.", ephemeral=True)
        Config = await EcoConfig().Get(interaction.guild.id)
        Multiplier = await Eco().shop.Multiplier(interaction.guild.id, Config)
        await interaction.response.send_message(embed=ItemCard(Item, Config, Multiplier), view=ItemView(Item), ephemeral=True)


class UseSelect(discord.ui.Select):
    def __init__(self, author_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Usar un consumible", options=options)
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Ese no es tu inventario 👀", ephemeral=True)
        await DoUse(interaction, self.values[0])


async def DoUse(interaction: discord.Interaction, item_id: str):
    try:
        Item = await Eco().shop.Use(interaction.user, item_id)
    except EconomyError as e:
        return await interaction.response.send_message(f"{Emojis.no} {e}", ephemeral=True)
    await interaction.response.send_message(
        f"🧪 Usaste **{Item['name']}**: {Perk(Item)}. ¡A darle!", ephemeral=True
    )


class EconomyShop(commands.Cog):
    """Tienda, inventario y consumibles."""

    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.hybrid_command(name="tienda", description="Mira la tienda y compra cositas")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def tienda(self, ctx: commands.Context):
        Config = await EcoConfig().Get(ctx.guild.id)
        Items = await Eco().shop.List(ctx.guild.id, only_enabled=True)
        embed = discord.Embed(title=f"🛒 Tienda de {ctx.guild.name}", color=discord.Color.blurple())
        if not Items:
            embed.description = "La tienda está vacía... los admins andan de vacaciones 🏖️"
            return await ctx.send(embed=embed)
        Multiplier = await Eco().shop.Multiplier(ctx.guild.id, Config)
        embed.description = "\n".join(ItemLine(I, Config, Multiplier) for I in Items)[:4096]
        Balance = await Eco().economy.Balance(ctx.guild.id, ctx.author.id)
        Discount = await Eco().shop.Discount(ctx.guild.id, ctx.author.id, Config)
        Footer = f"Tu saldo: {Balance:,}".replace(",", ".")
        if Discount:
            Footer += f" · 🐾 Tu mascota te da {Discount:.1%} de descuento al pagar"
        if Multiplier != 1:
            Footer += f" · 📈 Inflación x{Multiplier:.2f}"
        embed.set_footer(text=Footer)
        View = discord.ui.View(timeout=VIEW_TIMEOUT)
        View.add_item(ShopSelect(Items))
        await ctx.send(embed=embed, view=View)

    @commands.hybrid_command(name="inventario", description="Mira lo que tienes (o lo que tiene alguien)")
    @app_commands.describe(usuario="De quién")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def inventario(self, ctx: commands.Context, usuario: discord.Member = None):
        Member = usuario or ctx.author
        Items = {I["item_id"]: I for I in await Eco().shop.List(ctx.guild.id)}
        Owned = [O for O in await Eco().shop.Inventory(ctx.guild.id, Member.id) if O["item_id"] in Items]
        embed = discord.Embed(color=discord.Color.blurple())
        embed.set_author(name=f"Inventario de {Member.display_name}", icon_url=Member.display_avatar)
        if not Owned:
            embed.description = "Vacío. Más vacío que la nevera a fin de mes 🕸️"
        else:
            embed.description = "\n".join(
                f"{Items[O['item_id']].get('emoji') or '📦'} **{Items[O['item_id']]['name']}** × {O['qty']}" for O in Owned
            )
        Active = await Eco().bonuses.Active(ctx.guild.id, Member.id)
        if Active:
            embed.add_field(
                name="⚡ Boosts activos",
                value="\n".join(
                    f"> +{E['value']:.0%} {BOOSTS[E['kind']]} · termina {discord.utils.format_dt(Aware(E['expires_at']), 'R')}"
                    for E in Active
                ),
                inline=False,
            )
        View = None
        if Member == ctx.author:
            Usable = [
                discord.SelectOption(label=f"{Items[O['item_id']]['name']} (×{O['qty']})"[:100], value=O["item_id"], emoji=Items[O["item_id"]].get("emoji") or "🧪")
                for O in Owned
                if Items[O["item_id"]]["type"] == CONSUMABLE
            ]
            if Usable:
                View = discord.ui.View(timeout=VIEW_TIMEOUT)
                View.add_item(UseSelect(ctx.author.id, Usable[:25]))
        await ctx.send(embed=embed, view=View)

    @commands.hybrid_command(name="usar", description="Usa un consumible de tu inventario")
    @app_commands.describe(item="Qué quieres usar")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def usar(self, ctx: commands.Context, item: str):
        if ctx.interaction:
            return await DoUse(ctx.interaction, item)
        # Prefix version: find by name.
        Items = await Eco().shop.List(ctx.guild.id)
        Match = next((I for I in Items if I["name"].lower() == item.lower() or I["item_id"] == item.upper()), None)
        if not Match:
            return await ctx.send(f"{Emojis.no} No encuentro ese item.")
        try:
            Used = await Eco().shop.Use(ctx.author, Match["item_id"])
        except EconomyError as e:
            return await ctx.send(f"{Emojis.no} {e}")
        await ctx.send(f"🧪 Usaste **{Used['name']}**: {Perk(Used)}. ¡A darle!")

    @usar.autocomplete("item")
    async def UseAutocomplete(self, interaction: discord.Interaction, current: str):
        Items = {I["item_id"]: I for I in await Eco().shop.List(interaction.guild.id)}
        Owned = await Eco().shop.Inventory(interaction.guild.id, interaction.user.id)
        return [
            app_commands.Choice(name=f"{Items[O['item_id']]['name']} (×{O['qty']})"[:100], value=O["item_id"])
            for O in Owned
            if O["item_id"] in Items
            and Items[O["item_id"]]["type"] == CONSUMABLE
            and current.lower() in Items[O["item_id"]]["name"].lower()
        ][:25]


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyShop(client))
