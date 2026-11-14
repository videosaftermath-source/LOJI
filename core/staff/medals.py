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
