import asyncio
import io
import logging
import time

import aiohttp
import discord
from discord.ext import commands
from PIL import Image

from core.bot.Module import ModuleIsEnabled
from core.bot.emojis import Emojis
from core.economy import cards
from core.economy.config import EcoConfig
from core.economy.constants import ARCHETYPES, ITEM_TYPES, MODULE, RARITIES
from core.economy.boost import GachaSettings, IsBooster
from core.economy.gacha import ORDER, LegendaryRate
from core.economy.registry import Eco
from core.economy.rewards import Aware, FormatAmount
from core.economy.service import EconomyError, InsufficientFunds

logger = logging.getLogger(__name__)

VIEW_TIMEOUT = 1800
CUSTOM_EMOJI_URL = "https://cdn.discordapp.com/emojis/{}.png?size=128"
DOWNLOAD_TIMEOUT = 5
HISTORY_SIZE = 20


def Plain(label: str) -> str:
    """'🌾 Farmeador' -> 'Farmeador' (the card font can't draw emoji in text)."""
    return label.split(" ", 1)[1] if " " in label else label


def Percent(value: float) -> str:
    return f"{value * 100:.3g}%"


class EmojiCache:
    """Downloads custom Discord emojis for the cards (kept in memory)."""

    def __init__(self):
        self.images: dict[str, Image.Image | None] = {}

    async def Fetch(self, ids: set[str]) -> dict:
        Missing = [i for i in ids if i not in self.images]
        if Missing:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)) as Session:
                    for EmojiId in Missing:
                        try:
                            async with Session.get(CUSTOM_EMOJI_URL.format(EmojiId)) as Response:
                                Data = await Response.read() if Response.status == 200 else None
                            self.images[EmojiId] = Image.open(io.BytesIO(Data)).convert("RGBA") if Data else None
                        except Exception:
                            self.images[EmojiId] = None
            except Exception as e:
                logger.warning(f"[Gacha] Couldn't download emojis: {e}")
        return {i: self.images.get(i) for i in ids}


async def BannerEmbed(banner: dict, member: discord.Member, config: dict) -> discord.Embed:
    Settings = GachaSettings(member, config)
    Names = await PrizeNames(member.guild.id, banner["pool"], config)
    Best = max((P["rarity"] for P in banner["pool"]), key=ORDER.index, default="common")
    Cost = await Eco().gacha.PullCost(member.guild.id, banner, config)
    embed = discord.Embed(title=f"🎰 {banner['name']}", description=banner.get("description") or None, color=RARITIES[Best]["color"])
    embed.add_field(
        name="💰 Precio",
        value=f"x1: {FormatAmount(Cost, config)}\nx10: {FormatAmount(Cost * 10, config)}",
    )
    embed.add_field(name="⏳ Termina", value=discord.utils.format_dt(Aware(banner["end"]), "R"))
    Featured = [f"{RARITIES[P['rarity']]['stars']} {Names[P['key']]}" for P in banner["pool"] if P.get("featured")]
    if Featured:
        embed.add_field(name="🌟 Destacados", value="\n".join(Featured)[:1024], inline=False)
    Common = 1 - Settings["rate_legendary"] - Settings["rate_epic"] - Settings["rate_rare"]
    embed.add_field(
        name="📊 Probabilidades",
        value=(
            f"⭐⭐⭐⭐ {Percent(Settings['rate_legendary'])} · ⭐⭐⭐ {Percent(Settings['rate_epic'])} · "
            f"⭐⭐ {Percent(Settings['rate_rare'])} · ⭐ {Percent(Common)}\n"
            f"-# Legendaria segura a la tirada {Settings['hard_pity']} (sube desde la {Settings['soft_pity']}) · "
            f"épica o mejor cada {Settings['epic_pity']}"
            + (f"\n💎 **{member.display_name}** es booster: +{config['booster']['gacha_luck']:.0%} de prob. en legendaria y épica"
               if config["booster"]["enabled"] and IsBooster(member) and config["booster"]["gacha_luck"] > 0 else "")
        ),
        inline=False,
    )
    Pity = await Eco().gacha.UserPity(member.guild.id, member.id, banner["banner_id"])
    Chance = LegendaryRate(Pity.since_legendary + 1, Settings)
    embed.add_field(
        name=f"🎯 Pity de {member.display_name}",
        value=(
            f"Legendaria: **{Pity.since_legendary}/{Settings['hard_pity']}** (próxima: {Percent(Chance)})"
            + (" · 🌟 destacada garantizada" if Pity.legendary_guaranteed else "")
            + f"\nÉpica: **{Pity.since_epic}/{Settings['epic_pity']}**"
            + (" · 🌟 destacada garantizada" if Pity.epic_guaranteed else "")
        ),
        inline=False,
    )
    embed.set_footer(text="Cada uno tira con su propio dinero y su propio pity. ¡Suerte!")
    return embed


async def PrizeNames(guild_id: int, pool: list[dict], config: dict) -> dict[str, str]:
    Names = {}
    for P in pool:
        if P["type"] == "pet":
            S = await Eco().pets.GetSpecies(guild_id, P["ref"])
            Names[P["key"]] = f"{S.get('emoji') or '🐾'} {S['name']}" if S else "🐾 (especie borrada)"
        elif P["type"] == "item":
            I = await Eco().shop.Get(guild_id, P["ref"])
            Names[P["key"]] = f"{I.get('emoji') or '📦'} {I['name']}" if I else "📦 (item borrado)"
        else:
            Names[P["key"]] = f"{config['currency']['emoji']} {int(P['amount']):,} {config['currency']['name']}".replace(",", ".")
    return Names


def CardData(result, config: dict) -> dict:
    Prize = result.prize
    if Prize["type"] == "pet":
        Subtitle = "Mascota"
    elif Prize["type"] == "item":
        Subtitle = "Item"
    else:
        Subtitle = config["currency"]["name"]
    return {
        "name": result.name,
        "emoji": result.emoji,
        "rarity": result.rarity,
        "rarity_label": RARITIES[result.rarity]["label"],
        "subtitle": Subtitle,
        "featured": result.featured,
        "new": result.new,
        "detail": result.detail if not result.new else "",
    }


async def Subtitles(guild_id: int, results, data: list[dict]):
    """Adds the archetype / item type to the card subtitles."""
    for Result, Data in zip(results, data):
        if Result.prize["type"] == "pet":
            S = await Eco().pets.GetSpecies(guild_id, Result.prize["ref"])
            if S:
                Data["subtitle"] = f"Mascota · {Plain(ARCHETYPES[S['archetype']]['label'])}"
        elif Result.prize["type"] == "item":
            I = await Eco().shop.Get(guild_id, Result.prize["ref"])
            if I:
                Data["subtitle"] = f"Item · {Plain(ITEM_TYPES[I['type']])}"


class GachaView(discord.ui.View):
    def __init__(self, cog: "EconomyGacha", banners: list[dict], current: str, config: dict, cost: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.banner_id = current
        self.One.label = f"Tirar x1 ({cost:,})".replace(",", ".")
        self.Ten.label = f"Tirar x10 ({cost * 10:,})".replace(",", ".")
        if len(banners) > 1:
            Select = discord.ui.Select(
                placeholder="Cambiar de banner",
                options=[discord.SelectOption(label=B["name"][:100], value=B["banner_id"], default=B["banner_id"] == current) for B in banners],
                row=2,
            )
            Select.callback = self.Switch
            self.add_item(Select)

    async def Switch(self, interaction: discord.Interaction):
        Config = await EcoConfig().Get(interaction.guild.id)
        Banners = await Eco().gacha.Active(interaction.guild.id)
        Chosen = interaction.data["values"][0]
        Banner = next((B for B in Banners if B["banner_id"] == Chosen), None)
        if not Banner:
            return await interaction.response.send_message("Ese banner ya terminó.", ephemeral=True)
        Cost = await Eco().gacha.PullCost(interaction.guild.id, Banner, Config)
        await interaction.response.edit_message(
            embed=await BannerEmbed(Banner, interaction.user, Config), view=GachaView(self.cog, Banners, Chosen, Config, Cost)
        )

    @discord.ui.button(label="Tirar x1", emoji="✨", style=discord.ButtonStyle.blurple, row=0)
    async def One(self, interaction: discord.Interaction, _):
        await self.cog.DoPull(interaction, self.banner_id, 1)

    @discord.ui.button(label="Tirar x10", emoji="🌟", style=discord.ButtonStyle.green, row=0)
    async def Ten(self, interaction: discord.Interaction, _):
        await self.cog.DoPull(interaction, self.banner_id, 10)

    @discord.ui.button(label="Mi pity", emoji="🎯", style=discord.ButtonStyle.grey, row=1)
    async def MyPity(self, interaction: discord.Interaction, _):
        Banner = await Eco().gacha.Get(interaction.guild.id, self.banner_id)
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.send_message(embed=await BannerEmbed(Banner, interaction.user, Config), ephemeral=True)

    @discord.ui.button(label="Premios", emoji="📜", style=discord.ButtonStyle.grey, row=1)
    async def Prizes(self, interaction: discord.Interaction, _):
        Banner = await Eco().gacha.Get(interaction.guild.id, self.banner_id)
        Config = await EcoConfig().Get(interaction.guild.id)
        Names = await PrizeNames(interaction.guild.id, Banner["pool"], Config)
        embed = discord.Embed(title=f"📜 Premios de {Banner['name']}", color=discord.Color.blurple())
        for Rarity in reversed(ORDER):
            Lines = [("🌟 " if P.get("featured") else "") + Names[P["key"]] for P in Banner["pool"] if P["rarity"] == Rarity]
            if Lines:
                embed.add_field(name=f"{RARITIES[Rarity]['stars']} {RARITIES[Rarity]['label']}", value="\n".join(Lines)[:1024], inline=False)
        embed.set_footer(text="🌟 = destacado (50/50: si no sale, el siguiente de esa rareza lo es seguro)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Historial", emoji="🕓", style=discord.ButtonStyle.grey, row=1)
    async def History(self, interaction: discord.Interaction, _):
        Pulls = await Eco().gacha.History(interaction.guild.id, interaction.user.id, HISTORY_SIZE)
        embed = discord.Embed(title="🕓 Tus últimas tiradas", color=discord.Color.dark_embed())
        embed.description = "\n".join(
            f"{RARITIES[P['rarity']]['stars']} {'🌟 ' if P.get('featured') else ''}{P['name']} · {discord.utils.format_dt(Aware(P['ts']), 'R')}"
            for P in Pulls
        ) or "Todavía no has tirado. ¡Anímate! 🎰"
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EconomyGacha(commands.Cog):
    """Gacha con banners, pity y animaciones."""

    def __init__(self, client: commands.Bot):
        self.client = client
        self.cooldowns: dict[tuple[int, int], float] = {}
        self.emojis = EmojiCache()

    async def cog_load(self):
        # Build the three animations in the background so the first pull isn't slow.
        async def Warm():
            for Tier in cards.TIERS:
                await asyncio.to_thread(cards.Animation, Tier)
            logger.info("[Gacha] Animations ready")

        asyncio.get_running_loop().create_task(Warm())

    @commands.hybrid_command(name="gacha", description="Tira en el gacha y consigue mascotas, items y créditos")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def gacha(self, ctx: commands.Context):
        Config = await EcoConfig().Get(ctx.guild.id)
        Banners = await Eco().gacha.Active(ctx.guild.id)
        if not Banners:
            return await ctx.send("🎰 No hay ningún banner activo ahora mismo. ¡Vuelve pronto!")
        Cost = await Eco().gacha.PullCost(ctx.guild.id, Banners[0], Config)
        await ctx.send(embed=await BannerEmbed(Banners[0], ctx.author, Config), view=GachaView(self, Banners, Banners[0]["banner_id"], Config, Cost))

    async def DoPull(self, interaction: discord.Interaction, banner_id: str, count: int):
        # Discord only waits 3 seconds for a reply to a button, and a x10 pull takes longer
        # (many database writes). So acknowledge right away and do everything after.
        await interaction.response.defer()
        Config = await EcoConfig().Get(interaction.guild.id)
        Key = (interaction.guild.id, interaction.user.id)
        Wait = self.cooldowns.get(Key, 0) - time.monotonic()
        if Wait > 0:
            return await interaction.followup.send(f"⏳ Espera {Wait:.0f}s antes de volver a tirar.", ephemeral=True)
        self.cooldowns[Key] = time.monotonic() + Config["gacha"]["cooldown"]
        try:
            Outcome = await Eco().gacha.DoPull(interaction.user, banner_id, count, Config)
        except InsufficientFunds as e:
            self.cooldowns.pop(Key, None)
            Banner = await Eco().gacha.Get(interaction.guild.id, banner_id)
            Cost = await Eco().gacha.PullCost(interaction.guild.id, Banner, Config) * count if Banner else 0
            return await interaction.followup.send(
                f"{Emojis.no} Te faltan créditos: cuesta {FormatAmount(Cost, Config)} y tienes {FormatAmount(e.balance, Config)} 😭",
                ephemeral=True,
            )
        except EconomyError as e:
            self.cooldowns.pop(Key, None)
            return await interaction.followup.send(f"{Emojis.no} {e}", ephemeral=True)

        self.client.dispatch("economy_progress", interaction.guild.id, interaction.user.id, "gacha", count)
        # The pull is done and paid: from here on, whatever fails, the player must see their prizes.
        embed = self.ResultEmbed(interaction.user, Outcome, Config)
        try:
            Tier = cards.BestTier([R.rarity for R in Outcome.results])
            Gif = await asyncio.to_thread(cards.Animation, Tier)
            Card = asyncio.get_running_loop().create_task(self.RenderCard(interaction, Outcome, Config))
            Intro = discord.Embed(
                description=f"✨ **{interaction.user.display_name}** tira **x{count}** en **{Outcome.banner['name']}**...",
                color=discord.Color.dark_embed(),
            )
            Intro.set_image(url="attachment://tirada.gif")
            Message = await interaction.followup.send(embed=Intro, file=discord.File(io.BytesIO(Gif), "tirada.gif"), wait=True)
            await asyncio.sleep(cards.AnimationSeconds(Gif))
            try:
                Png = await Card
            except Exception as e:
                logger.error(f"[Gacha] Card failed: {e}")
                Png = None
            Files = []
            if Png:
                embed.set_image(url="attachment://resultado.png")
                Files = [discord.File(io.BytesIO(Png), "resultado.png")]
            await Message.edit(embed=embed, attachments=Files)
        except Exception as e:
            logger.error(f"[Gacha] Couldn't show the pull animation/card: {e}")
            embed.set_image(url=None)
            try:
                await interaction.followup.send(embed=embed)
            except discord.HTTPException:
                await interaction.channel.send(content=interaction.user.mention, embed=embed)

    async def RenderCard(self, interaction: discord.Interaction, outcome, config: dict) -> bytes:
        Data = [CardData(R, config) for R in outcome.results]
        await Subtitles(interaction.guild.id, outcome.results, Data)
        Custom = await self.emojis.Fetch(cards.CustomEmojiIds(D["emoji"] for D in Data))
        Settings = config["gacha"]
        Pity = outcome.pity
        Info = {
            "banner": outcome.banner["name"],
            "user": interaction.user.display_name,
            "pity": f"Pity legendario {Pity.since_legendary}/{Settings['hard_pity']}" + (" · destacada garantizada" if Pity.legendary_guaranteed else ""),
        }
        if len(Data) == 1:
            return await asyncio.to_thread(cards.SingleCard, Data[0], Info, Custom)
        Counts = {R: sum(1 for D in Data if D["rarity"] == R) for R in ("legendary", "epic", "rare")}
        Info["summary"] = " · ".join(f"{N} {RARITIES[R]['label'].lower()}{'s' if N != 1 else ''}" for R, N in Counts.items() if N) or "Sin suerte esta vez"
        return await asyncio.to_thread(cards.GridCard, Data, Info, Custom)

    def ResultEmbed(self, member: discord.Member, outcome, config: dict) -> discord.Embed:
        Best = max((R.rarity for R in outcome.results), key=ORDER.index)
        Ordered = sorted(outcome.results, key=lambda R: ORDER.index(R.rarity), reverse=True)
        Lines = []
        for R in Ordered:
            Extra = " · ¡NUEVA!" if R.new else (f" · {R.detail}" if R.detail and R.prize["type"] != "credits" else "")
            Lines.append(f"{RARITIES[R.rarity]['stars']} {'🌟 ' if R.featured else ''}{R.emoji or ''} **{R.name}**{Extra}")
        Titles = {"legendary": "🌟 ¡¡LEGENDARIA!! 🌟", "epic": "💜 ¡Épica!", "rare": "💙 Nada mal", "common": "🙂 Algo es algo"}
        embed = discord.Embed(title=Titles[Best], description="\n".join(Lines)[:4096], color=RARITIES[Best]["color"])
        embed.set_author(name=f"Tirada de {member.display_name}", icon_url=member.display_avatar)
        Settings = config["gacha"]
        embed.set_footer(
            text=f"Pagaste {outcome.paid:,} · Te quedan {outcome.balance:,} · Pity {outcome.pity.since_legendary}/{Settings['hard_pity']}".replace(",", ".")
        )
        return embed


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyGacha(client))
