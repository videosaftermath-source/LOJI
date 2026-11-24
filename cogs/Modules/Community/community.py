"""Comunidad: the missions board and the overflow ("General 2") chat, plus the supporter card (set up in Vanity y tag)."""

import asyncio
import logging
import time

import discord
from discord import ui
from discord.ext import commands, tasks

from core.community import (
    MAX_BOARD_QUESTS, ButtonUrl, CloseStep, Variant, Color, DropLinesWithEmpty, Fill, ParseButtons, Store, Title, Traffic,
)

logger = logging.getLogger(__name__)
CHECK_SECONDS = 20
PERIOD_LABEL = {"daily": "Cada día", "weekly": "Cada semana", "once": "Solo una vez"}
BAR = 8


# ======================= supporter welcome =======================


def WelcomeValues(member: discord.Member, roles: list, vanity: bool, tag: bool, vanity_text: str, board: dict) -> dict:
    from core.supporters import Slug

    Thing = "nuestro **TAG**" if tag else "nuestra **vanity**"  # one card per reason; both counts as the TAG
    BoardChannel = member.guild.get_channel(board.get("channel") or 0)
    return {
        "user": member.mention, "nombre": member.display_name, "server": member.guild.name, "cosa": Thing,
        "rol": " ".join(R.mention for R in roles), "vanity": f"`.gg/{Slug(vanity_text)}`",
        "tareas": BoardChannel.mention if BoardChannel else "",
        "tareas_link": BoardChannel.jump_url if BoardChannel else "",
    }


def Thumb(member: discord.Member, setting: str) -> str | None:
    Setting = (setting or "avatar").strip()
    if Setting == "ninguna":
        return None
    if Setting == "servidor":
        return member.guild.icon.url if member.guild.icon else None
    if Setting.startswith("http"):
        return Setting
    return member.display_avatar.url


def LinkButtons(text: str, values: dict, guild_id: int) -> list[ui.Button]:
    Buttons = []
    for B in ParseButtons(text):
        Url = ButtonUrl(Fill(B["target"], values), guild_id)
        if Url:
            Buttons.append(ui.Button(label=B["label"], emoji=B["emoji"] or None, url=Url))
    return Buttons


def WelcomeView(member: discord.Member, settings: dict, values: dict, heading: str | None = None) -> ui.LayoutView:
    def Text(key: str) -> str:
        return Fill(DropLinesWithEmpty(settings.get(key) or "", values), values).strip()

    View = ui.LayoutView(timeout=None)
    if heading:  # previews say which card it is
        View.add_item(ui.TextDisplay(heading))
    Box = ui.Container(accent_colour=Color(settings["color"]))
    Head = "\n".join(T for T in (Text("title"), Text("intro")) if T) or "‎"
    Image = Thumb(member, settings["thumbnail"])
    Box.add_item(ui.Section(ui.TextDisplay(Head), accessory=ui.Thumbnail(Image)) if Image else ui.TextDisplay(Head))
    Body = "\n".join(T for T in (Text("benefits"), Text("note")) if T)
    if Body:
        Box.add_item(ui.TextDisplay(Body))
    Footer = Text("footer")
    Buttons = LinkButtons(settings["buttons"], values, member.guild.id)
    if Footer or Buttons:
        Box.add_item(ui.Separator())
    if Footer:
        Box.add_item(ui.TextDisplay(Footer))
    if Buttons:
        Box.add_item(ui.ActionRow(*Buttons))
    View.add_item(Box)
    return View


async def SendWelcome(member: discord.Member, channel, supporter_config: dict, vanity: bool, tag: bool):
    """The supporter announcement card: the TAG version if they wear the tag, otherwise the vanity one."""
    Config = await Store().Get(member.guild.id)
    Settings = Variant(Config["welcome"], tag)
    Roles = [R for R in (member.guild.get_role(supporter_config.get(K) or 0) for K, On in (("tag_role", tag), ("vanity_role", vanity)) if On) if R]
    Roles = list(dict.fromkeys(Roles))  # the same role for both shows once
    Values = WelcomeValues(member, Roles, vanity, tag, supporter_config.get("vanity") or "", Config["board"])
    await channel.send(view=WelcomeView(member, Settings, Values), allowed_mentions=discord.AllowedMentions(users=[member], roles=False))


# ======================= boost card =======================


def BoostValues(member: discord.Member, eco: dict, board: dict) -> dict:
    """Variables for the boost card. The economy ones are empty when the booster perks are off (their lines hide)."""
    from core.economy.rewards import FormatAmount

    Booster = eco["booster"]
    On = Booster["enabled"]
    Since = member.premium_since or discord.utils.utcnow()
    BoardChannel = member.guild.get_channel(board.get("channel") or 0)
    Extra = round((float(Booster["multiplier"]) - 1) * 100)
    return {
        "user": member.mention, "nombre": member.display_name, "server": member.guild.name,
        "fecha": discord.utils.format_dt(Since, "D"), "boosts": str(member.guild.premium_subscription_count or 0),
        "multiplicador": f"+{Extra} %" if On and Extra > 0 else "",
        "suerte": f"+{round(float(Booster['gacha_luck']) * 100)} %" if On and Booster["gacha_luck"] > 0 else "",
        "premio": FormatAmount(int(Booster["reward"]), eco) if On and Booster["reward"] > 0 else "",
        "tareas": BoardChannel.mention if BoardChannel else "",
        "tareas_link": BoardChannel.jump_url if BoardChannel else "",
    }


async def AnnounceBoost(member: discord.Member) -> bool:
    """Posts the card once per boost. True if it was posted."""
    from core.db import db
    from core.community import BOOST_SEEN

    Settings = (await Store().Get(member.guild.id))["boost"]
    Channel = member.guild.get_channel(Settings["channel"] or 0)
    if not Settings["enabled"] or not Channel or not member.premium_since:
        return False
    Since = int(member.premium_since.timestamp())
    Key = f"{member.guild.id}:{member.id}"
    Done = await db[BOOST_SEEN].update_one({"_id": Key, "since": {"$ne": Since}}, {"$set": {"since": Since}}, upsert=False)
    if not Done.matched_count:
        try:
            await db[BOOST_SEEN].insert_one({"_id": Key, "since": Since})
        except Exception:
            return False  # this boost was already announced
    await PostCard("boost", member, Channel)
    return True


async def SendJson(http, channel_id: int, components: list[dict], users: list[int] = (), ephemeral_token: tuple | None = None):
    """Sends raw Components V2 (flag 32768). With ephemeral_token=(application_id, interaction_token) it's a
    private follow-up to an interaction instead (for previews)."""
    from discord.http import Route

    Payload = {"flags": 1 << 15, "components": components, "allowed_mentions": {"parse": [], "users": [str(U) for U in users]}}
    if ephemeral_token:
        Payload["flags"] |= 1 << 6
        App, Token = ephemeral_token
        return await http.request(Route("POST", "/webhooks/{webhook_id}/{webhook_token}", webhook_id=App, webhook_token=Token), json=Payload)
    return await http.request(Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id), json=Payload)


# ======================= welcome (new members) =======================


def JoinValues(member: discord.Member, board: dict) -> dict:
    BoardChannel = member.guild.get_channel(board.get("channel") or 0)
    Count = member.guild.member_count or len(member.guild.members)
    Joined = getattr(member, "joined_at", None) or discord.utils.utcnow()
    return {
        "user": member.mention, "nombre": member.display_name, "server": member.guild.name,
        "numero": f"{Count:,}".replace(",", "."), "miembros": f"{Count:,}".replace(",", "."),
        "creada": discord.utils.format_dt(member.created_at, "D"), "fecha": discord.utils.format_dt(Joined, "D"),
        "tareas": BoardChannel.mention if BoardChannel else "",
        "tareas_link": BoardChannel.jump_url if BoardChannel else "",
    }


async def CardValues(section: str, member: discord.Member) -> dict:
    """The {variables} of a card ("boost" or "join") for this member."""
    Config = await Store().Get(member.guild.id)
    if section == "boost":
        from core.economy.config import EcoConfig

        return BoostValues(member, await EcoConfig().Get(member.guild.id), Config["board"])
    return JoinValues(member, Config["board"])


async def CardView(section: str, member: discord.Member, heading: str | None = None) -> ui.LayoutView:
    Config = await Store().Get(member.guild.id)
    return WelcomeView(member, Config[section], await CardValues(section, member), heading)


async def CardJson(section: str, member: discord.Member) -> list[dict]:
    from core.community import FillJson, ParseCardJson

    Config = await Store().Get(member.guild.id)
    return FillJson(ParseCardJson(Config[section]["json"]), await CardValues(section, member))


async def PostCard(section: str, member: discord.Member, channel):
    """Posts a card in its simple design or as its uploaded JSON."""
    Settings = (await Store().Get(member.guild.id))[section]
    if Settings.get("json"):
        await SendJson(channel._state.http, channel.id, await CardJson(section, member), users=[member.id])
    else:
        await channel.send(view=await CardView(section, member), allowed_mentions=discord.AllowedMentions(users=[member], roles=False))


async def AnnounceJoin(member: discord.Member) -> bool:
    """The welcome card for a new member (not again for a day if they leave and come back)."""
    from datetime import datetime, timedelta, timezone

    from core.community import JOIN_COOLDOWN_HOURS, JOIN_SEEN
    from core.db import db

    Settings = (await Store().Get(member.guild.id))["join"]
    Channel = member.guild.get_channel(Settings["channel"] or 0)
    if member.bot or not Settings["enabled"] or not Channel:
        return False
    try:  # back in quarantine after leaving: no welcome
        from cogs.Modules.roleban import Store as Rolebans

        if await Rolebans().Active(member.guild.id, member.id):
            return False
    except Exception:
        pass
    Now = datetime.now(timezone.utc)
    Key = f"{member.guild.id}:{member.id}"
    Recent = await db[JOIN_SEEN].find_one({"_id": Key})
    At = (Recent or {}).get("at")
    if At and (At if At.tzinfo else At.replace(tzinfo=timezone.utc)) > Now - timedelta(hours=JOIN_COOLDOWN_HOURS):
        return False
    await db[JOIN_SEEN].update_one({"_id": Key}, {"$set": {"at": Now}}, upsert=True)
    await PostCard("join", member, Channel)
    return True


# ======================= missions board =======================


async def BoardQuests(guild_id: int) -> list[dict]:
    from core.economy.registry import Eco

    Order = {"daily": 0, "weekly": 1, "once": 2}
    Quests = await Eco().quests.List(guild_id, only_enabled=True)
    return sorted(Quests, key=lambda Q: Order.get(Q["period"], 9))[:MAX_BOARD_QUESTS]


def Prize(quest: dict, board: dict, items: dict) -> str:
    """'<coin> **250**' (+ the item, if the mission gives one)."""
    Parts = []
    if quest.get("reward"):
        Parts.append(f"{board.get('coin') or '🪙'} **{int(quest['reward']):,}**".replace(",", "."))
    Item = items.get(quest.get("reward_item"))
    if Item:
        Parts.append(f"{Item.get('emoji') or '📦'} {Item['name']}")
    return " + ".join(Parts) or "—"


def Emoji(text: str):
    """A custom emoji like <:name:id> or a normal one; None if it's empty or broken."""
    try:
        return discord.PartialEmoji.from_str(text.strip()) if text and text.strip() else None
    except Exception:
        return None


def Bar(progress: int, target: int) -> str:
    Filled = min(BAR, int(BAR * progress / target)) if target else BAR
    return "▰" * Filled + "▱" * (BAR - Filled)


async def BoardView(guild: discord.Guild, member: discord.Member | None = None) -> ui.LayoutView:
    """The public board, or (with member) the same board with that person's progress."""
    from core.economy.config import EcoConfig
    from core.economy.quests import Conditions
    from core.economy.registry import Eco

    Settings = (await Store().Get(guild.id))["board"]
    Eco_ = await EcoConfig().Get(guild.id)
    Items = {I["item_id"]: I for I in await Eco().shop.List(guild.id)}
    Quests = await BoardQuests(guild.id)
    Status = {}
    if member:
        for Quest, Progress, Claimed in await Eco().quests.Status(guild.id, member.id, Eco_, Conditions(member)):
            Status[Quest["quest_id"]] = (Progress, Claimed)
    Values = {"server": guild.name}
    View = ui.LayoutView(timeout=None if not member else 600)
    Box = ui.Container(accent_colour=Color(Settings["color"], 0x57F287))
    if Settings["banner"]:
        Box.add_item(ui.MediaGallery(discord.MediaGalleryItem(Settings["banner"])))
    Head = "\n".join(T for T in (Fill(Settings["title"], Values), Fill(Settings["description"], Values)) if T.strip())
    if member:
        Head += f"\n-# Progreso de {member.mention}"
    Box.add_item(ui.TextDisplay(Head or "‎"))
    if not Quests:
        Box.add_item(ui.TextDisplay("*Todavía no hay misiones. Se crean en `/config` → Economía → Misiones.*"))
    for Index, Quest in enumerate(Quests):
        Line = f"**{Quest['name']}**\n{Prize(Quest, Settings, Items)} · {PERIOD_LABEL.get(Quest['period'], '')}"
        Button = ClaimButton(Quest["quest_id"], personal=bool(member))
        Button.item.label, Button.item.emoji = Settings["claim_label"] or "Cobrar", Emoji(Settings["coin"])
        if member:
            Progress, Claimed = Status.get(Quest["quest_id"], (0, False))
            Target = int(Quest["target"])
            if Claimed:
                Line += " · ✅ Cobrada"
                Button.item.disabled, Button.item.label, Button.item.style = True, "Cobrada", discord.ButtonStyle.grey
            elif Progress >= Target:
                Line += " · 🎉 ¡Lista!"
            elif Quest["objective"] in ("supporter", "boost"):
                Line += " · " + ("aún no llevas el tag" if Quest["objective"] == "supporter" else "aún no boosteas")
            else:
                Line += f" · {Bar(Progress, Target)} {min(Progress, Target)}/{Target}"
                Button.item.disabled, Button.item.style = True, discord.ButtonStyle.grey
        Box.add_item(ui.Section(ui.TextDisplay(Line), accessory=Button))
        if Index < len(Quests) - 1:
            Box.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
    if Settings["footer"]:
        Box.add_item(ui.TextDisplay(Fill(Settings["footer"], Values)))
    if not member:
        Progress = ProgressButton()
        Progress.item.label = Settings["progress_label"] or "Mi progreso"
        Box.add_item(ui.ActionRow(Progress))
    View.add_item(Box)
    return View


class ClaimButton(ui.DynamicItem[ui.Button], template=r"qc:(?P<quest>[A-Za-z0-9]{1,24}):(?P<mode>[bp])"):
    def __init__(self, quest_id: str, personal: bool = False):
        super().__init__(ui.Button(
            label="Cobrar", emoji="🪙", style=discord.ButtonStyle.green, custom_id=f"qc:{quest_id}:{'p' if personal else 'b'}",
        ))
        self.quest_id, self.personal = quest_id, personal

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["quest"], match["mode"] == "p")

    async def callback(self, interaction: discord.Interaction):
        from core.bot.Module import ModuleCheck
        from core.economy.config import EcoConfig
        from core.economy.constants import MODULE
        from core.economy.quests import Conditions
        from core.economy.registry import Eco
        from core.economy.service import EconomyError

        if not await ModuleCheck(interaction.guild.id, MODULE):
            return await interaction.response.send_message("❌ La economía está desactivada.", ephemeral=True)
        Config = await EcoConfig().Get(interaction.guild.id)
        Mine = Conditions(interaction.user)
        Status = {Q["quest_id"]: (Q, P, C) for Q, P, C in await Eco().quests.Status(interaction.guild.id, interaction.user.id, Config, Mine)}
        if self.quest_id not in Status:
            return await interaction.response.send_message("❌ Esa misión ya no existe.", ephemeral=True)
        Quest, Progress, Claimed = Status[self.quest_id]
        Target = int(Quest["target"])
        if Claimed:
            When = {"daily": " hoy. Vuelve mañana", "weekly": " esta semana. Vuelve la próxima"}.get(Quest["period"], "")
            return await interaction.response.send_message(f"✅ Ya reclamaste **{Quest['name']}**{When}.", ephemeral=True)
        if Progress < Target:
            from core.economy.constants import CONDITIONS, OBJECTIVES

            if Quest["objective"] in CONDITIONS:
                Need = "llevar el tag o la vanity del servidor" if Quest["objective"] == "supporter" else "estar boosteando el servidor"
                return await interaction.response.send_message(f"❌ Para reclamar **{Quest['name']}** tienes que {Need}.", ephemeral=True)
            return await interaction.response.send_message(
                f"⏳ **{Quest['name']}**: llevas **{Progress}/{Target}** ({OBJECTIVES.get(Quest['objective'], '')}).\n{Bar(Progress, Target)} ¡Sigue así!",
                ephemeral=True,
            )
        try:
            await Eco().quests.Claim(interaction.guild.id, interaction.user.id, self.quest_id, Config, Mine)
        except EconomyError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        Items = {I["item_id"]: I for I in await Eco().shop.List(interaction.guild.id)}
        Board = (await Store().Get(interaction.guild.id))["board"]
        Done = f"🎉 Cobraste **{Quest['name']}**: +{Prize(Quest, Board, Items)}"
        if self.personal:
            await interaction.response.edit_message(view=await BoardView(interaction.guild, interaction.user))
            return await interaction.followup.send(Done, ephemeral=True)
        await interaction.response.send_message(Done, ephemeral=True)


class ProgressButton(ui.DynamicItem[ui.Button], template=r"qprog"):
    def __init__(self):
        super().__init__(ui.Button(label="Mi progreso", emoji="📊", style=discord.ButtonStyle.grey, custom_id="qprog"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=await BoardView(interaction.guild, interaction.user), ephemeral=True)


async def PublishBoard(guild: discord.Guild, channel=None) -> str:
    """Posts the board (or edits the one already posted). Returns a message for the admin."""
    Settings = (await Store().Get(guild.id))["board"]
    Channel = channel or guild.get_channel(Settings["channel"] or 0)
    if not Channel:
        return "❌ Elige primero el canal del tablero."
    View = await BoardView(guild)
    if Settings["message_id"] and Settings["channel"] == Channel.id:
        try:
            Message = Channel.get_partial_message(Settings["message_id"])
            await Message.edit(view=View)
            return f"✅ Tablero actualizado en {Channel.mention}."
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            return f"❌ No pude editar el tablero: {e.text or e}"
    try:
        Message = await Channel.send(view=View)
    except discord.HTTPException as e:
        return f"❌ No pude publicar en {Channel.mention}: {e.text or e}"
    await Store().Set(guild.id, "board", {"channel": Channel.id, "message_id": Message.id})
    return f"✅ Tablero publicado en {Channel.mention}."


# ======================= overflow chat =======================


def Notice(text: str, values: dict, color: discord.Color) -> discord.Embed:
    Head, Body = Title(Fill(text, values))
    return discord.Embed(title=Head[:256] or None, description=Body[:4000] or None, color=color)


class Community(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.traffic = Traffic()
        self.extra: dict[int, list[float]] = {}  # extra chat -> times of recent messages
        self.locks: dict[int, asyncio.Lock] = {}
        self.warnings: dict[int, int] = {}  # guild -> warning message id
        self.started = time.time()
        self.Check.start()

    async def cog_load(self):
        self.client.add_dynamic_items(ClaimButton, ProgressButton)

    def cog_unload(self):
        self.Check.cancel()

    def Lock(self, guild_id: int) -> asyncio.Lock:
        return self.locks.setdefault(guild_id, asyncio.Lock())

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.premium_since is None or before.premium_since == after.premium_since:
            return
        try:
            await AnnounceBoost(after)
        except Exception as e:
            logger.warning(f"[Community] Boost card for {after.id} failed: {e!r}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            await AnnounceJoin(member)
        except Exception as e:
            logger.warning(f"[Community] Welcome card for {member.id} failed: {e!r}")

    @commands.Cog.listener()
    async def on_quests_changed(self, guild_id: int):
        Guild = self.client.get_guild(guild_id)
        Settings = (await Store().Get(guild_id))["board"] if Guild else None
        if Settings and Settings["message_id"]:
            Result = await PublishBoard(Guild)
            if not Result.startswith("✅"):
                logger.warning(f"[Community] Board refresh in {guild_id}: {Result}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        Settings = (await Store().Get(message.guild.id))["overflow"]
        if not Settings["enabled"]:
            return
        Now = time.time()
        Channel = message.channel.id
        if Channel == Settings["extra"]:
            List = self.extra.setdefault(Channel, [])
            List.append(Now)
            Keep = Now - max(int(Settings["idle_minutes"]) * 60, int(Settings["warn_seconds"])) - 60
            while List and List[0] < Keep:
                List.pop(0)
        elif Channel == Settings["main"] and not Settings["is_open"]:
            self.traffic.Add(Channel, message.author.id, Now, int(Settings["open_seconds"]))
            if self.traffic.Busy(Channel, Now, Settings):
                async with self.Lock(message.guild.id):
                    Fresh = (await Store().Get(message.guild.id))["overflow"]
                    if not Fresh["is_open"]:
                        await self.Open(message.guild, Fresh)

    async def SetAccess(self, guild: discord.Guild, settings: dict, open_: bool):
        Extra = guild.get_channel(settings["extra"] or 0)
        Role = guild.get_role(settings["role"] or 0) or guild.default_role
        Overwrite = Extra.overwrites_for(Role)
        if settings["mode"] == "hide":
            Overwrite.view_channel = open_
            Overwrite.send_messages = True if open_ else None
        else:
            Overwrite.send_messages = open_
        await Extra.set_permissions(Role, overwrite=Overwrite, reason="Chat extra " + ("abierto" if open_ else "cerrado") + " por actividad")

    def Values(self, guild: discord.Guild, settings: dict) -> dict:
        Main, Extra = guild.get_channel(settings["main"] or 0), guild.get_channel(settings["extra"] or 0)
        return {"principal": Main.mention if Main else "#general", "extra": Extra.mention if Extra else "el otro chat", "server": guild.name}

    async def Open(self, guild: discord.Guild, settings: dict):
        Extra, Main = guild.get_channel(settings["extra"] or 0), guild.get_channel(settings["main"] or 0)
        if not Extra or not Main:
            return
        try:
            await self.SetAccess(guild, settings, True)
        except discord.HTTPException as e:
            return logger.warning(f"[Community] Can't open {Extra.id}: {e}")
        await Store().Set(guild.id, "overflow", {"is_open": True, "opened_at": time.time(), "warned_at": None})
        self.extra[Extra.id] = []
        Values = self.Values(guild, settings)
        try:
            await Extra.send(embed=Notice(settings["text_open"], Values, discord.Color.green()))
            if settings["notice_main"]:
                await Main.send(embed=Notice(settings["text_main"], Values, discord.Color.green()))
        except discord.HTTPException as e:
            logger.warning(f"[Community] Opened {Extra.id} but couldn't announce it: {e}")

    async def Close(self, guild: discord.Guild, settings: dict):
        Extra = guild.get_channel(settings["extra"] or 0)
        await Store().Set(guild.id, "overflow", {"is_open": False, "opened_at": None, "warned_at": None})
        self.traffic.messages.pop(settings["main"], None)  # it needs a new rush to open again
        self.warnings.pop(guild.id, None)
        if not Extra:
            return
        try:
            await Extra.send(embed=Notice(settings["text_close"], self.Values(guild, settings), discord.Color.blurple()))
            await self.SetAccess(guild, settings, False)
        except discord.HTTPException as e:
            logger.warning(f"[Community] Can't close {Extra.id}: {e}")

    @tasks.loop(seconds=CHECK_SECONDS)
    async def Check(self):
        for Guild in self.client.guilds:
            try:
                Settings = (await Store().Get(Guild.id))["overflow"]
                if Settings["enabled"] and Settings["is_open"]:
                    async with self.Lock(Guild.id):
                        await self.Step(Guild, (await Store().Get(Guild.id))["overflow"])
            except Exception as e:
                logger.exception(f"[Community] Overflow check failed in {Guild.id}: {e!r}")

    @Check.before_loop
    async def BeforeCheck(self):
        await self.client.wait_until_ready()

    async def Step(self, guild: discord.Guild, settings: dict):
        if not settings["is_open"]:
            return
        Extra = guild.get_channel(settings["extra"] or 0)
        if not Extra:
            return
        Now = time.time()
        Times = self.extra.get(Extra.id, [])
        Recent = len([T for T in Times if T >= Now - int(settings["idle_minutes"]) * 60])
        Warned = settings["warned_at"]
        SinceWarning = len([T for T in Times if Warned and T > Warned])
        # After a restart we haven't seen the chat: give it a full window before judging it.
        OpenedAt = max(settings["opened_at"] or 0, self.started)
        Action = CloseStep(settings, Now, Recent, OpenedAt, Warned, SinceWarning)
        if Action == "warn":
            try:
                Sent = await Extra.send(embed=Notice(settings["text_warn"], self.Values(guild, settings), discord.Color.yellow()))
                self.warnings[guild.id] = Sent.id
            except discord.HTTPException:
                pass
            await Store().Set(guild.id, "overflow", {"warned_at": Now})
        elif Action == "cancel":
            await Store().Set(guild.id, "overflow", {"warned_at": None})
            if guild.id in self.warnings:
                try:
                    await Extra.get_partial_message(self.warnings.pop(guild.id)).delete()
                except discord.HTTPException:
                    pass
        elif Action == "close":
            await self.Close(guild, settings)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Community(client))
