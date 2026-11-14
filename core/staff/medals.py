"""
Medals: roles the admins chose in /config → Mando Central → "Roles de medalla". The profile shows the ones
the member has, with the role's icon.

A role icon can't be written inside an embed, so the bot uploads each icon once as one of its own
(application) emojis, named like the role, and reuses it: re-uploaded only if the icon changes, renamed if
the role is. Which emoji belongs to which role is kept in "medal_emojis".
"""

import asyncio
import logging
import re
import unicodedata

import discord

logger = logging.getLogger(__name__)
FALLBACK = "🏅"


def MedalRoles(member, config: dict) -> list:
    """The medal roles the member has, most important (highest in Discord) first."""
    Chosen = set(config.get("medal_roles") or [])
    return sorted((R for R in getattr(member, "roles", []) if R.id in Chosen), key=lambda R: -R.position)


LEGACY = re.compile(r"^m(\d{15,21})_([0-9a-f]{1,8})$")  # the old names: m<role>_<icon>
MAPPING = "medal_emojis"  # role id -> which bot emoji is its icon, and from which icon


def PrettyName(role_name: str) -> str:
    """'Medalla de Oro ⭐' -> 'Medalla_de_Oro' (emoji names: letters, numbers and _, 2-32 characters)."""
    Text = unicodedata.normalize("NFKD", role_name).encode("ascii", "ignore").decode()
    Text = re.sub(r"[^A-Za-z0-9_]+", "_", Text).strip("_")
    Text = re.sub(r"_+", "_", Text)[:32].strip("_")
    return Text if len(Text) >= 2 else "medalla"


def IconTag(icon_key: str) -> str:
    return icon_key.replace("a_", "")[:8]


class MedalEmojis:
    """role id -> emoji text, uploading role icons as the bot's own emojis named like the role."""

    def __init__(self, client, db=None):
        self.client = client
        self.db = db
        self.emojis: dict[int, discord.Emoji] | None = None  # emoji id -> emoji
        self.mapping: dict[int, dict] = {}  # role id -> {"emoji": id, "icon": tag}
        self.lock = asyncio.Lock()

    def Col(self):
        if self.db is None:
            from core.db import db

            self.db = db
        return self.db[MAPPING]

    async def Load(self):
        if self.emojis is not None:
            return
        try:
            All = await self.client.fetch_application_emojis()
        except discord.HTTPException as e:
            logger.warning(f"[Medals] Can't list the bot's emojis: {e}")
            All = []
        self.emojis = {E.id: E for E in All}
        self.mapping = {D["_id"]: D for D in await self.Col().find({}).to_list(length=None)}
        for E in All:  # emojis made before the mapping existed
            Match = LEGACY.match(E.name)
            if Match and int(Match.group(1)) not in self.mapping:
                await self.Remember(int(Match.group(1)), E.id, Match.group(2))

    async def Remember(self, role_id: int, emoji_id: int, tag: str):
        Doc = {"_id": role_id, "emoji": emoji_id, "icon": tag}
        self.mapping[role_id] = Doc
        await self.Col().update_one({"_id": role_id}, {"$set": Doc}, upsert=True)

    def FreeName(self, wanted: str, mine: int | None) -> str:
        Taken = {E.name for I, E in self.emojis.items() if I != mine}
        Name, N = wanted, 2
        while Name in Taken:
            Suffix = f"_{N}"
            Name, N = wanted[: 32 - len(Suffix)] + Suffix, N + 1
        return Name

    async def Get(self, role) -> str:
        if getattr(role, "unicode_emoji", None):
            return role.unicode_emoji
        Icon = getattr(role, "icon", None)
        if Icon is None:
            return FALLBACK
        Tag, Wanted = IconTag(Icon.key), PrettyName(role.name)
        Known = self.mapping.get(role.id)
        Emoji = self.emojis.get(Known["emoji"]) if Known and self.emojis else None
        if Emoji and Known["icon"] == Tag and Emoji.name == self.FreeName(Wanted, Emoji.id):
            return str(Emoji)  # the usual case: no API call
        async with self.lock:
            await self.Load()
            Known = self.mapping.get(role.id)
            Emoji = self.emojis.get(Known["emoji"]) if Known else None
            Name = self.FreeName(Wanted, Emoji.id if Emoji else None)
            try:
                if Emoji and Known["icon"] == Tag:
                    if Emoji.name != Name:  # the role was renamed (or the emoji had the old name)
                        Emoji = await Emoji.edit(name=Name)
                        self.emojis[Emoji.id] = Emoji
                    return str(Emoji)
                if Emoji:  # the icon changed: the old one goes
                    await Emoji.delete()
                    self.emojis.pop(Emoji.id, None)
                New = await self.client.create_application_emoji(name=Name, image=await Icon.read())
            except (discord.HTTPException, ValueError) as e:
                logger.warning(f"[Medals] Couldn't make the emoji for role {role.id}: {e}")
                return str(Emoji) if Emoji else FALLBACK
            self.emojis[New.id] = New
            await self.Remember(role.id, New.id, Tag)
            return str(New)

    async def Line(self, roles: list, names: bool = True) -> str:
        Parts = []
        for R in roles:
            Emoji = await self.Get(R)
            Parts.append(f"{Emoji} {R.name}" if names else Emoji)
        return (" · " if names else " ").join(Parts)


_manager: MedalEmojis | None = None


def Setup(client):
    global _manager
    _manager = MedalEmojis(client)


def Manager() -> MedalEmojis | None:
    return _manager


DESCRIPTION_MAX = 150


async def CatalogEmbed(guild: discord.Guild, config: dict, viewer=None) -> discord.Embed:
    """Every medal: icon, name, how to get it and how many have it (✅ = the viewer has it)."""
    Info = config.get("medal_info") or {}
    Roles = sorted((R for R in (guild.get_role(I) for I in config.get("medal_roles") or []) if R), key=lambda R: -R.position)
    Mine = {R.id for R in getattr(viewer, "roles", [])}
    embed = discord.Embed(title="🏅 Catálogo de medallas", color=discord.Color.gold())
    if not Roles:
        embed.description = "Todavía no hay medallas. Se eligen en `/config` → Mando Central → Roles de medalla."
        return embed
    M, Lines = Manager(), []
    for R in Roles:
        Emoji = await M.Get(R) if M else (getattr(R, "unicode_emoji", None) or FALLBACK)
        Count = len(R.members)
        Have = " ✅" if R.id in Mine else ""
        How = Info.get(str(R.id)) or "*Sin descripción todavía.*"
        Lines.append(f"{Emoji} **{R.name}**{Have} · {Count} la tiene{'n' if Count != 1 else ''}\n> {How}")
    embed.description = "\n".join(Lines)[:4096]
    Got = len([R for R in Roles if R.id in Mine])
    embed.set_footer(text=f"Tienes {Got} de {len(Roles)}" if viewer and Mine else f"{len(Roles)} medallas")
    return embed


async def MemberMedalsEmbed(member, config: dict) -> discord.Embed:
    """A staff member's medals with how each one is earned (the "Detalle condecoraciones" button)."""
    Info = config.get("medal_info") or {}
    Mine = MedalRoles(member, config)
    embed = discord.Embed(title=f"🏅 Condecoraciones de {member.display_name}", color=discord.Color.gold())
    embed.set_thumbnail(url=member.display_avatar.url)
    if not Mine:
        embed.description = "Todavía no tiene ninguna medalla."
        return embed
    M, Lines = Manager(), []
    for R in Mine:
        Emoji = await M.Get(R) if M else (getattr(R, "unicode_emoji", None) or FALLBACK)
        Lines.append(f"{Emoji} **{R.name}**\n> {Info.get(str(R.id)) or '*Sin descripción.*'}")
    embed.description = "\n".join(Lines)[:4096]
    embed.set_footer(text=f"{len(Mine)} medalla{'s' if len(Mine) != 1 else ''}")
    return embed


DEFAULT_AWARD = (
    "En virtud de las facultades conferidas al **Tenno** de {servidor}, y en reconocimiento a la labor, "
    "el compromiso y la dedicación demostrados en el servicio, por la presente se le otorga a {usuario} la condecoración\n\n"
    "# {emoji} {medalla}\n\n"
    "**Por:** {motivo}\n\n"
    "Que esta distinción quede como testimonio de su entrega al servidor y como ejemplo para todo el staff. "
    "Se le exhorta a seguir honrándola con su conducta."
)
AWARD_VARIABLES = "`{usuario}` `{nombre}` `{medalla}` `{emoji}` `{motivo}` `{descripcion}` `{otorga}` `{servidor}` `{fecha}`"
AWARD_MAX = 1500


def AwardText(template: str | None, member, role, giver, reason: str, description: str, emoji: str, server: str, date: str) -> str:
    Values = {
        "{usuario}": member.mention, "{nombre}": member.display_name, "{medalla}": role.name, "{emoji}": emoji,
        "{motivo}": reason or description or "sus méritos en el servicio", "{descripcion}": description or "—",
        "{otorga}": giver.mention, "{servidor}": f"**{server}**", "{fecha}": date,
    }
    Text = template or DEFAULT_AWARD
    for K, V in Values.items():
        Text = Text.replace(K, V)
    return Text[:4096]


async def AwardEmbed(guild, member, role, giver, reason: str, config: dict) -> discord.embeds.Embed:
    from datetime import datetime, timezone

    M = Manager()
    Emoji = await M.Get(role) if M else (getattr(role, "unicode_emoji", None) or FALLBACK)
    Description = (config.get("medal_info") or {}).get(str(role.id), "")
    embed = discord.Embed(
        title="🏅 Entrega de condecoración",
        description=AwardText(config.get("medal_award_text"), member, role, giver, reason, Description, Emoji, guild.name,
                              datetime.now(timezone.utc).strftime("%d/%m/%Y")),
        color=role.color if role.color.value else discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    Icon = getattr(role, "display_icon", None)
    embed.set_thumbnail(url=Icon.url if isinstance(Icon, discord.Asset) else member.display_avatar.url)
    embed.set_footer(text="Otorgada por el Tenno · Mando Central")
    return embed
