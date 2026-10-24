import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.Module import ModuleIsEnabled
from core.bot.emojis import Emojis
from core.economy.cards import AnimationSeconds
from core.economy.config import EcoConfig
from core.economy.constants import ARCHETYPES, MODULE, RARITIES
from core.economy.petcards import AlbumCard, EvolutionGif, PetCard
from core.economy.pets import CurrentCare, Now, PetView
from core.economy.registry import Eco
from core.economy.rewards import FormatAmount
from core.economy.service import EconomyError, InsufficientFunds

logger = logging.getLogger(__name__)
ALBUM_MAX = 25  # pets drawn in the album image (5 rows of 5)

VIEW_TIMEOUT = 600
BAR_LENGTH = 10
# Which economy events give the active pet XP, and the config key with how much.
XP_EVENTS = {"work": "xp_work", "daily": "xp_daily", "messages": "xp_message", "play": "xp_game"}


def Bar(value: float, maximum: float = 100) -> str:
    Filled = round(BAR_LENGTH * value / maximum) if maximum else BAR_LENGTH
    return "▰" * Filled + "▱" * (BAR_LENGTH - Filled)


def Mood(hunger: float, happiness: float) -> str:
    Low = min(hunger, happiness)
    if Low >= 70:
        return "😄 Feliz y bien comida"
    if Low >= 40:
        return "🙂 Bien, pero no la descuides"
    if Low >= 15:
        return "😟 Te extraña..."
    return "😭 ¡Abandonada! Su perk casi no funciona"


def PetName(view: PetView) -> str:
    return view.pet.get("nickname") or view.species["name"]


def Plain(label: str) -> str:
    return label.split(" ", 1)[1] if " " in label else label


def CardData(view: PetView, owner: discord.abc.User, costs: dict) -> dict:
    S, Archetype = view.species, ARCHETYPES[view.species["archetype"]]
    Footer = (
        f"Evoluciona al nivel {S['evolve_level']} · {costs['evolve_price']:,}".replace(",", ".")
        if S.get("evolves_to") and S.get("evolve_level")
        else "Exclusiva · no evoluciona" if S.get("exclusive") else "Forma final"
    )
    return {
        "name": PetName(view),
        "species": S["name"],
        "emoji": S.get("emoji"),
        "art": S.get("art"),
        "rarity": S["rarity"],
        "rarity_label": RARITIES[S["rarity"]]["label"],
        "archetype": Plain(Archetype["label"]),
        "level": view.level,
        "xp": view.xp,
        "xp_next": view.xp_next,
        "hunger": view.hunger,
        "happiness": view.happiness,
        "care": view.care,
        "perk": f"+{view.perk:.1%} {Archetype['perk']}",
        "perk_note": f"Funciona al {view.care:.0%} porque no está bien cuidada" if view.care < 1 else "",
        "owner": owner.display_name,
        "footer": Footer,
    }


async def PetCardMessage(view: PetView, owner: discord.abc.User, config: dict, costs: dict | None = None) -> tuple[discord.Embed, discord.File]:
    """The pet card image, plus a short text summary for people with images turned off."""
    Costs = costs or await PetCosts(owner.guild.id, config)
    Png = await asyncio.to_thread(PetCard, CardData(view, owner, Costs))
    S, Archetype = view.species, ARCHETYPES[view.species["archetype"]]
    embed = discord.Embed(
        title=f"{S.get('emoji') or '🐾'} {PetName(view)}",
        description=(
            f"*{S.get('description') or ''}*\n"
            f"-# Nivel {view.level} · 🍖 {view.hunger:.0f}% · 🎾 {view.happiness:.0f}% · {Mood(view.hunger, view.happiness)} · "
            f"+{view.perk:.1%} {Archetype['perk']}"
        ),
        color=RARITIES[S["rarity"]]["color"],
    )
    embed.set_image(url="attachment://mascota.png")
    if S.get("image"):
        embed.set_thumbnail(url=S["image"])
    return embed, discord.File(io.BytesIO(Png), "mascota.png")


class Rename(discord.ui.Modal, title="Ponle nombre"):
    name = discord.ui.TextInput(label="Nombre (vacío = el de su especie)", max_length=24, required=False)

    def __init__(self, panel: "PetPanel"):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await Eco().pets.Rename(interaction.guild.id, interaction.user.id, self.name.value)
        except EconomyError as e:
            return await interaction.followup.send(f"{Emojis.no} {e}", ephemeral=True)
        await self.panel.Refresh(interaction)


class SwitchSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Cambiar de mascota activa", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await Eco().pets.SetActive(interaction.guild.id, interaction.user.id, self.values[0])
        except EconomyError as e:
            return await interaction.followup.send(f"{Emojis.no} {e}", ephemeral=True)
        await self.view.Refresh(interaction)


class PetPanel(discord.ui.View):
    def __init__(self, owner: discord.Member, view: PetView, others: list[discord.SelectOption], config: dict, costs: dict | None = None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.owner = owner
        Costs = costs or config["pets"]
        self.Feed.label = f"Alimentar ({Costs['food_price']:,})".replace(",", ".")
        self.Play.label = f"Jugar ({Costs['play_price']:,})".replace(",", ".")
        S = view.species
        CanEvolve = S.get("evolves_to") and S.get("evolve_level") and view.level >= S["evolve_level"]
        if not CanEvolve:
            self.remove_item(self.Evolve)
        if len(others) > 1:
            self.add_item(SwitchSelect(others[:25]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("Esa no es tu mascota 👀", ephemeral=True)
            return False
        return True

    async def Refresh(self, interaction: discord.Interaction, note: str | None = None):
        """Redraws the card. The interaction must already be deferred (drawing takes a moment)."""
        embed, view, File = await PetMessage(self.owner)
        await interaction.edit_original_response(content=note, embed=embed, attachments=[File] if File else [], view=view)

    async def DoCare(self, interaction: discord.Interaction, kind: str):
        await interaction.response.defer()
        Config = await EcoConfig().Get(interaction.guild.id)
        try:
            View, Old, New = await Eco().pets.Care(interaction.guild.id, interaction.user.id, kind, Config)
        except InsufficientFunds as e:
            return await interaction.followup.send(f"{Emojis.no} No te alcanza 😢 Tienes {FormatAmount(e.balance, Config)}.", ephemeral=True)
        except EconomyError as e:
            return await interaction.followup.send(f"{Emojis.no} {e}", ephemeral=True)
        Note = ("🍖 ¡Ñam ñam!" if kind == "food" else "🎾 ¡Qué divertido!") + (f" +{View.gained} XP" if View.gained else "")
        if New > Old:
            Note += f"\n🎉 **¡{PetName(View)} subió al nivel {New}!**"
        await self.Refresh(interaction, Note)

    @discord.ui.button(label="Alimentar", emoji="🍖", style=discord.ButtonStyle.green, row=0)
    async def Feed(self, interaction: discord.Interaction, _):
        await self.DoCare(interaction, "food")

    @discord.ui.button(label="Jugar", emoji="🎾", style=discord.ButtonStyle.blurple, row=0)
    async def Play(self, interaction: discord.Interaction, _):
        await self.DoCare(interaction, "play")

    @discord.ui.button(label="Nombre", emoji="✏️", style=discord.ButtonStyle.grey, row=0)
    async def Name(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(Rename(self))

    @discord.ui.button(label="Evolucionar", emoji="✨", style=discord.ButtonStyle.red, row=0)
    async def Evolve(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        Config = await EcoConfig().Get(interaction.guild.id)
        try:
            Old, New = await Eco().pets.Evolve(interaction.guild.id, interaction.user.id, Config)
        except InsufficientFunds as e:
            Cost = await Eco().pets.Cost(interaction.guild.id, Config["pets"]["evolve_price"], Config)
            return await interaction.followup.send(
                f"{Emojis.no} Evolucionar cuesta {FormatAmount(Cost, Config)} y tienes {FormatAmount(e.balance, Config)}.", ephemeral=True
            )
        except EconomyError as e:
            return await interaction.followup.send(f"{Emojis.no} {e}", ephemeral=True)
        # Evolution animation, then the new card.
        try:
            Gif = await asyncio.to_thread(EvolutionGif, Old, New)
            Show = discord.Embed(description=f"✨ ¿Qué le pasa a **{Old['name']}**...?", color=RARITIES[New["rarity"]]["color"])
            Show.set_image(url="attachment://evolucion.gif")
            await interaction.edit_original_response(content=None, embed=Show, attachments=[discord.File(io.BytesIO(Gif), "evolucion.gif")], view=None)
            await asyncio.sleep(AnimationSeconds(Gif))
        except discord.HTTPException as e:
            logger.warning(f"[Economy] Evolution animation failed: {e}")
        await self.Refresh(interaction, f"✨ ¡{Old.get('emoji', '')} {Old['name']} evolucionó en {New.get('emoji', '')} **{New['name']}**!")


async def PetMessage(owner: discord.Member) -> tuple[discord.Embed, discord.ui.View | None, discord.File | None]:
    """The card of someone's active pet (with buttons if it's theirs)."""
    Config = await EcoConfig().Get(owner.guild.id)
    Pet = await Eco().pets.Active(owner.guild.id, owner.id)
    if not Pet:
        return discord.Embed(description="No tiene mascota todavía 🥺 Se consiguen en el gacha.", color=discord.Color.light_grey()), None, None
    View = await Eco().pets.View(Pet, Config)
    if not View:
        return discord.Embed(description="La especie de esta mascota ya no existe.", color=discord.Color.light_grey()), None, None
    Others = await PetOptions(owner, Pet["pet_id"])
    Costs = await PetCosts(owner.guild.id, Config)
    embed, File = await PetCardMessage(View, owner, Config, Costs)
    return embed, PetPanel(owner, View, Others, Config, Costs), File


async def PetCosts(guild_id: int, config: dict) -> dict:
    """Care and evolution prices after inflation."""
    return {K: await Eco().pets.Cost(guild_id, config["pets"][K], config) for K in ("food_price", "play_price", "evolve_price")}


async def PetOptions(owner: discord.Member, active_id: str | None) -> list[discord.SelectOption]:
    Options = []
    for Pet in await Eco().pets.List(owner.guild.id, owner.id):
        Species = await Eco().pets.GetSpecies(owner.guild.id, Pet["species_id"])
        if not Species:
            continue
        Options.append(
            discord.SelectOption(
                label=f"{Pet.get('nickname') or Species['name']} · Nv. {Pet.get('level', 1)}"[:100],
                description=f"{RARITIES[Species['rarity']]['label']} · {ARCHETYPES[Species['archetype']]['label']}"[:100],
                emoji=Species.get("emoji") or "🐾",
                value=Pet["pet_id"],
                default=Pet["pet_id"] == active_id,
            )
        )
    return Options


class EconomyPets(commands.Cog):
    """Mascotas: verlas, cuidarlas, cambiarlas y evolucionarlas."""

    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.Cog.listener()
    async def on_economy_progress(self, guild_id: int, user_id: int, objective: str, amount: int):
        """Your active pet learns while you play (only if it isn't starving)."""
        Key = XP_EVENTS.get(objective)
        if not Key:
            return
        try:
            Config = await EcoConfig().Get(guild_id)
            Xp = Config["pets"][Key] * (1 if objective != "play" else max(1, amount))
            Pet = await Eco().pets.Active(guild_id, user_id)
            if not Pet or not Xp:
                return
            Hunger, _ = CurrentCare(Pet, Now(), Config)
            if Hunger <= 0:
                return
            await Eco().pets.GainXp(Pet, Xp, Config)
        except Exception as e:
            logger.error(f"[Economy] Pet XP failed: {e}")

    @commands.hybrid_group(name="mascota", description="Tu mascota")
    @commands.guild_only()
    async def mascota(self, ctx: commands.Context):
        pass

    @mascota.command(name="ver", description="Mira tu mascota (o la de alguien) y cuídala")
    @app_commands.describe(usuario="De quién")
    @ModuleIsEnabled(MODULE)
    async def ver(self, ctx: commands.Context, usuario: discord.Member = None):
        await ctx.defer()
        Owner = usuario or ctx.author
        embed, view, File = await PetMessage(Owner)
        await ctx.send(embed=embed, file=File, view=view if Owner == ctx.author else None) if File else await ctx.send(embed=embed)

    @mascota.command(name="lista", description="Todas tus mascotas")
    @app_commands.describe(usuario="De quién")
    @ModuleIsEnabled(MODULE)
    async def lista(self, ctx: commands.Context, usuario: discord.Member = None):
        await ctx.defer()
        Owner = usuario or ctx.author
        Config = await EcoConfig().Get(ctx.guild.id)
        ActiveId = await Eco().pets.ActiveId(ctx.guild.id, Owner.id)
        Options = await PetOptions(Owner, ActiveId)
        Album, Costs = [], await PetCosts(ctx.guild.id, Config)
        for Pet in await Eco().pets.List(ctx.guild.id, Owner.id):
            View_ = await Eco().pets.View(Pet, Config)
            if View_:
                Data = CardData(View_, Owner, Costs)
                Data["active"] = Pet["pet_id"] == ActiveId
                Album.append(Data)
        embed = discord.Embed(title=f"🐾 Mascotas de {Owner.display_name}", color=discord.Color.teal())
        embed.description = "\n".join(
            f"{O.emoji} **{O.label}** · {O.description}" + (" · ✅ activa" if O.value == ActiveId else "") for O in Options
        ) or "Ninguna todavía 🥺 Se consiguen en el gacha."
        View = None
        if Owner == ctx.author and len(Options) > 1:
            View = discord.ui.View(timeout=VIEW_TIMEOUT)
            Select = discord.ui.Select(placeholder="Elegir mascota activa", options=Options[:25])

            async def Pick(interaction: discord.Interaction):
                if interaction.user.id != Owner.id:
                    return await interaction.response.send_message("Esas no son tus mascotas 👀", ephemeral=True)
                await Eco().pets.SetActive(interaction.guild.id, Owner.id, Select.values[0])
                Chosen = next((O.label for O in Options if O.value == Select.values[0]), "tu mascota")
                await interaction.response.send_message(f"✅ Ahora te acompaña **{Chosen}**. Mírala con `/mascota ver`.", ephemeral=True)

            Select.callback = Pick
            View.add_item(Select)
        if not Album:
            return await ctx.send(embed=embed)
        if len(Album) > ALBUM_MAX:
            embed.set_footer(text=f"La imagen muestra las {ALBUM_MAX} con más XP de {len(Album)}.")
        Png = await asyncio.to_thread(AlbumCard, Album[:ALBUM_MAX], Owner.display_name)
        embed.set_image(url="attachment://album.png")
        await ctx.send(embed=embed, file=discord.File(io.BytesIO(Png), "album.png"), view=View)

    async def Care(self, ctx: commands.Context, kind: str):
        Config = await EcoConfig().Get(ctx.guild.id)
        try:
            View, Old, New = await Eco().pets.Care(ctx.guild.id, ctx.author.id, kind, Config)
        except InsufficientFunds as e:
            return await ctx.send(f"{Emojis.no} No te alcanza 😢 Tienes {FormatAmount(e.balance, Config)}.", ephemeral=True)
        except EconomyError as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        Note = ("🍖 ¡Ñam ñam!" if kind == "food" else "🎾 ¡Qué divertido!") + (f" +{View.gained} XP" if View.gained else "")
        if New > Old:
            Note += f"\n🎉 **¡{PetName(View)} subió al nivel {New}!**"
        embed, File = await PetCardMessage(View, ctx.author, Config)
        await ctx.send(Note, embed=embed, file=File)

    @mascota.command(name="alimentar", description="Dale de comer a tu mascota (cuesta créditos)")
    @ModuleIsEnabled(MODULE)
    async def alimentar(self, ctx: commands.Context):
        await self.Care(ctx, "food")

    @mascota.command(name="jugar", description="Juega con tu mascota (cuesta créditos)")
    @ModuleIsEnabled(MODULE)
    async def jugar(self, ctx: commands.Context):
        await self.Care(ctx, "play")

    @mascota.command(name="renombrar", description="Cambia el nombre de tu mascota activa")
    @app_commands.describe(nombre="El nombre nuevo")
    @ModuleIsEnabled(MODULE)
    async def renombrar(self, ctx: commands.Context, *, nombre: str):
        try:
            Pet = await Eco().pets.Rename(ctx.guild.id, ctx.author.id, nombre)
        except EconomyError as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        await ctx.send(f"✏️ Ahora se llama **{Pet['nickname'] or 'como su especie'}**.", ephemeral=True)

    @mascota.command(name="activar", description="Elige qué mascota te acompaña")
    @app_commands.describe(mascota="Cuál")
    @ModuleIsEnabled(MODULE)
    async def activar(self, ctx: commands.Context, mascota: str):
        try:
            await Eco().pets.SetActive(ctx.guild.id, ctx.author.id, mascota)
        except EconomyError as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        embed, view, File = await PetMessage(ctx.author)
        await ctx.send("✅ ¡Mascota activa cambiada!", embed=embed, view=view, file=File)

    @activar.autocomplete("mascota")
    async def ActivarAutocomplete(self, interaction: discord.Interaction, current: str):
        Options = await PetOptions(interaction.user, None)
        return [app_commands.Choice(name=O.label, value=O.value) for O in Options if current.lower() in O.label.lower()][:25]


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyPets(client))
