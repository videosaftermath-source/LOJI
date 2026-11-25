"""
Booster icons and booster tracking.

- Icon panels: Components V2 messages with up to 5 icon roles and one neutral button per icon. Only boosters
  can use them, one icon at a time across every panel; clicking the one you wear takes it off.
- Boosters: LOJI remembers who boosts. When someone stops (seen live, or by the hourly check after an outage)
  they get a DM, lose their icon, and the economy perks stop on their own (they read the boost live).
  Boosts missed while offline get their card and economy reward on the next check.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

import discord
from discord import ui
from discord.ext import commands, tasks

from core.community import BOOSTERS, ICON_PANELS, MAX_ICONS, PANEL_DEFAULTS, BoostChanges, Color, Fill, IconSwap, Store

logger = logging.getLogger(__name__)
CHECK_MINUTES = 60
LOST_DM = (
    "💔 Has dejado de boostear **{server}**, así que has perdido tus beneficios de booster "
    "(icono, color degradado, ventajas en la economía…).\n¡Gracias por el apoyo que nos diste! Si vuelves a boostear, los recuperas al momento."
)


def Db():
    from core.db import db

    return db


def IsBooster(member) -> bool:
    """Discord's own booster role (an integration role Discord gives and takes away) or the boost date."""
    Role = getattr(member.guild, "premium_subscriber_role", None)
    return getattr(member, "premium_since", None) is not None or bool(Role and Role in getattr(member, "roles", []))


def BoosterMention(guild: discord.Guild) -> str:
    Role = guild.premium_subscriber_role
    return Role.mention if Role else "quien boostea"


def CheckEmoji(client, text: str):
    """(emoji, problem). Custom emojis must be ones LOJI can use (from a server it's in, or its own)."""
    Text = (text or "").strip()
    if not Text:
        return None, "falta el emoji"
    try:
        Emoji = discord.PartialEmoji.from_str(Text)
    except Exception:
        return None, f"`{Text[:40]}` no es un emoji"
    if Emoji.id:
        if not client.get_emoji(Emoji.id):
            return None, f"{Text[:60]} es de un servidor donde LOJI no está"
        return Emoji, None
    if re.search(r"[A-Za-z0-9]", Emoji.name) and "⃣" not in Emoji.name:
        return None, f"`{Text[:40]}` no es un emoji"
    return Emoji, None


# ---------------- panels ----------------


async def Panels(guild_id: int) -> list[dict]:
    return await Db()[ICON_PANELS].find({"guild_id": guild_id}).sort("created_at", 1).to_list(length=None)


async def Panel(guild_id: int, panel_id: str) -> dict | None:
    return await Db()[ICON_PANELS].find_one({"guild_id": guild_id, "panel_id": panel_id})


async def SavePanel(guild_id: int, panel_id: str, changes: dict):
    await Db()[ICON_PANELS].update_one({"guild_id": guild_id, "panel_id": panel_id}, {"$set": changes})


async def IconRoles(guild_id: int) -> set[int]:
    return {I["role"] for P in await Panels(guild_id) for I in P.get("items", [])}


async def BoosterRoles(guild_id: int) -> set[int]:
    """Everything only boosters keep: icons and gradient colors (taken away together when the boost ends)."""
    Colors = (await Store().Get(guild_id)).get("colors", {}).get("roles") or []
    return await IconRoles(guild_id) | set(Colors)


def PanelView(guild: discord.Guild, panel: dict, number: int, total: int, heading: str) -> ui.LayoutView:
    Settings = {**PANEL_DEFAULTS, **{K: V for K, V in panel.items() if V not in (None,)}}
    Values = {"booster": BoosterMention(guild), "server": guild.name, "n": str(number), "total": str(total)}
    View = ui.LayoutView(timeout=None)
    Box = ui.Container(accent_colour=Color(Settings["color"], 0xC9C9D1))
    if Settings["banner"]:
        Box.add_item(ui.MediaGallery(discord.MediaGalleryItem(Settings["banner"])))
    if Settings["text"]:
        Box.add_item(ui.TextDisplay(Fill(Settings["text"], Values)))
    Items = panel.get("items") or []
    Lines = [f"{I['emoji']} <@&{I['role']}>" for I in Items]
    Box.add_item(ui.TextDisplay((Fill(heading, Values) + "\n" + "\n".join(Lines)).strip() or "‎"))
    if Settings["footer"] or Items:
        Box.add_item(ui.Separator())
    if Settings["footer"]:
        Box.add_item(ui.TextDisplay(Fill(Settings["footer"], Values)))
    if Items:
        Box.add_item(ui.ActionRow(*(IconButton(I["role"], I["emoji"]) for I in Items[:MAX_ICONS])))
    View.add_item(Box)
    return View


async def Publish(guild: discord.Guild, panel: dict, channel=None) -> str:
    """Posts the panel (or edits it where it already is). Returns a message for the admin."""
    All = await Panels(guild.id)
    Heading = (await Store().Get(guild.id))["icons"]["heading"]
    Number = next((I for I, P in enumerate(All, 1) if P["panel_id"] == panel["panel_id"]), len(All))
    View = PanelView(guild, panel, Number, len(All), Heading)
    Channel = channel or guild.get_channel(panel.get("channel") or 0)
    if not Channel:
        return "❌ Elige primero el canal."
    if not panel.get("items"):
        return "❌ El panel necesita al menos 1 icono (rol + emoji)."
    if panel.get("message_id") and panel.get("channel") == Channel.id:
        try:
            await Channel.get_partial_message(panel["message_id"]).edit(view=View)
            return f"✅ Actualizado en {Channel.mention}."
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            return f"❌ No pude editarlo: {e.text or e}"
    elif panel.get("message_id"):  # moved to another channel: the old message goes
        Old = guild.get_channel(panel.get("channel") or 0)
        if Old:
            try:
                await Old.get_partial_message(panel["message_id"]).delete()
            except discord.HTTPException:
                pass
    try:
        Message = await Channel.send(view=View, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        return f"❌ No pude publicar en {Channel.mention}: {e.text or e}"
    await SavePanel(guild.id, panel["panel_id"], {"channel": Channel.id, "message_id": Message.id})
    return f"✅ Publicado en {Channel.mention}."


async def RefreshAll(guild: discord.Guild) -> list[str]:
    """Re-renders every published panel (the 1/4, 2/4 numbering changes when panels come and go)."""
    Problems = []
    for P in await Panels(guild.id):
        if P.get("message_id"):
            Result = await Publish(guild, P)
            if not Result.startswith("✅"):
                Problems.append(f"{P['name']}: {Result}")
    return Problems


class IconButton(ui.DynamicItem[ui.Button], template=r"bicon:(?P<role>\d{15,21})"):
    def __init__(self, role_id: int, emoji: str | None = None):
        Emoji = None
        try:
            Emoji = discord.PartialEmoji.from_str(emoji) if emoji else None
        except Exception:
            pass
        super().__init__(ui.Button(emoji=Emoji or "⭐", style=discord.ButtonStyle.grey, custom_id=f"bicon:{role_id}"))
        self.role_id = int(role_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["role"]))

    async def callback(self, interaction: discord.Interaction):
        Member, Guild = interaction.user, interaction.guild
        if not IsBooster(Member):
            return await interaction.response.send_message(
                f"💎 Los iconos son solo para {BoosterMention(Guild)}. ¡Boostea el servidor para elegir uno!",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
        Icons = await IconRoles(Guild.id)
        Role = Guild.get_role(self.role_id)
        if self.role_id not in Icons or not Role:
            return await interaction.response.send_message("❌ Ese icono ya no existe.", ephemeral=True)
        Cog = interaction.client.get_cog("BoosterIcons")
        async with (Cog.Lock(Member.id) if Cog else asyncio.Lock()):
            Member = Guild.get_member(Member.id) or Member
            Add, Remove, What = IconSwap({R.id for R in Member.roles}, Icons, self.role_id)
            Roles = [R for R in Member.roles if R.id not in Remove and not R.is_default()] + [Guild.get_role(I) for I in Add]
            try:
                await Member.edit(roles=[R for R in Roles if R], reason="Icono de booster")
            except discord.HTTPException as e:
                return await interaction.response.send_message(f"❌ No pude cambiar tu icono: {e.text or e}", ephemeral=True)
        Old = ", ".join(f"<@&{R}>" for R in Remove)
        Text = {
            "added": f"✅ Ahora llevas {Role.mention}.",
            "swapped": f"🔄 Cambiaste {Old} → {Role.mention}.",
            "removed": f"🗑️ Te quitaste {Role.mention}.",
        }[What]
        await interaction.response.send_message(Text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        if Cog:
            await Cog.Log(Guild, f"{Member.mention} · {Text}")


# ---------------- cog ----------------


class BoosterIcons(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.locks: dict[int, asyncio.Lock] = {}
        self.Check.start()

    async def cog_load(self):
        self.client.add_dynamic_items(IconButton)

    def cog_unload(self):
        self.Check.cancel()

    def Lock(self, user_id: int) -> asyncio.Lock:
        return self.locks.setdefault(user_id, asyncio.Lock())

    async def Log(self, guild: discord.Guild, text: str):
        Channel = guild.get_channel((await Store().Get(guild.id))["icons"]["log"] or 0)
        if Channel:
            try:
                await Channel.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    async def Remember(self, guild_id: int, user_id: int):
        await Db()[BOOSTERS].update_one(
            {"_id": f"{guild_id}:{user_id}"},
            {"$set": {"guild_id": guild_id, "user_id": user_id, "since": datetime.now(timezone.utc)}}, upsert=True,
        )

    async def Lost(self, guild: discord.Guild, user_id: int):
        """Someone stopped boosting: only once (the live event and the hourly check can both see it)."""
        Gone = await Db()[BOOSTERS].delete_one({"_id": f"{guild.id}:{user_id}"})
        if not Gone.deleted_count:
            return
        Member = guild.get_member(user_id)
        Removed = await self.StripIcons(Member) if Member else []
        if Member:
            try:
                await Member.send(LOST_DM.replace("{server}", guild.name))
            except discord.HTTPException:
                pass
        await self.Log(guild, f"💔 <@{user_id}> dejó de boostear" + (f" · se le quitó {', '.join(R.mention for R in Removed)}" if Removed else ""))

    async def StripIcons(self, member: discord.Member) -> list:
        Icons = await BoosterRoles(member.guild.id)
        Wearing = [R for R in member.roles if R.id in Icons]
        if Wearing:
            try:
                await member.remove_roles(*Wearing, reason="Ya no boostea: se retiran el icono y el color de booster")
            except discord.HTTPException as e:
                logger.warning(f"[Icons] Couldn't remove icons from {member.id}: {e}")
                return []
        return Wearing

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        Was, Is = IsBooster(before), IsBooster(after)
        if Was == Is:
            return
        try:
            if Is:
                await self.Remember(after.guild.id, after.id)
            else:
                await self.Lost(after.guild, after.id)
        except Exception as e:
            logger.warning(f"[Icons] Boost change for {after.id} failed: {e!r}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Leaving ends the boost: forget them quietly (no DM to someone who left).
        await Db()[BOOSTERS].delete_one({"_id": f"{member.guild.id}:{member.id}"})

    @tasks.loop(minutes=CHECK_MINUTES)
    async def Check(self):
        for Guild in self.client.guilds:
            try:
                await self.CheckGuild(Guild)
            except Exception as e:
                logger.exception(f"[Icons] Booster check failed in {Guild.id}: {e!r}")

    @Check.before_loop
    async def BeforeCheck(self):
        await self.client.wait_until_ready()

    async def CheckGuild(self, guild: discord.Guild):
        """Catches what Discord didn't tell us (outages, restarts): lost boosts, missed boosts, stray icons."""
        if not guild.chunked:
            await guild.chunk()
        Current = {M.id for M in guild.members if not M.bot and IsBooster(M)}
        Settings = (await Store().Get(guild.id))["icons"]
        if not Settings.get("ready"):  # first time: just learn who boosts, without DMs or cards
            for Id in Current:
                await self.Remember(guild.id, Id)
            await Store().Set(guild.id, "icons", {"ready": True})
        else:
            Known = {D["user_id"] for D in await Db()[BOOSTERS].find({"guild_id": guild.id}).to_list(length=None)}
            New, Lost = BoostChanges(Known, Current)
            for Id in Lost:
                await self.Lost(guild, Id)
            for Id in New:
                await self.Remember(guild.id, Id)
                await self.Missed(guild.get_member(Id))
        # Anyone wearing an icon or a gradient without boosting (given by hand, or missed events) loses it.
        Icons = await BoosterRoles(guild.id)
        for RoleId in Icons:
            Role = guild.get_role(RoleId)
            for Member in list(Role.members) if Role else []:
                if not IsBooster(Member):
                    await self.StripIcons(Member)

    async def Missed(self, member: discord.Member | None):
        """A boost that happened while LOJI was offline: its card and economy reward (both only once per boost)."""
        if not member or not member.premium_since:
            return
        from cogs.Modules.Community.community import AnnounceBoost

        try:
            await AnnounceBoost(member)
        except Exception as e:
            logger.warning(f"[Icons] Missed boost card for {member.id}: {e!r}")
        try:
            from core.bot.Module import ModuleCheck
            from core.economy.boost import RewardBoost
            from core.economy.config import EcoConfig
            from core.economy.constants import MODULE
            from core.economy.registry import Eco

            if await ModuleCheck(member.guild.id, MODULE):
                await RewardBoost(Eco().economy, member, await EcoConfig().Get(member.guild.id))
        except Exception as e:
            logger.warning(f"[Icons] Missed boost reward for {member.id}: {e!r}")


async def setup(client: commands.Bot) -> None:
    await client.add_cog(BoosterIcons(client))
