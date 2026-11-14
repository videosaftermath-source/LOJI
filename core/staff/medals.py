"""
Medals: roles the admins chose in /config → Mando Central → "Roles de medalla". The profile shows the ones
the member has, with the role's icon.

A role icon can't be written inside an embed, so the bot uploads each icon once as one of its own
(application) emojis and reuses it; it's re-uploaded only if the icon changes. Nothing else is stored.
"""

import asyncio
import logging

import discord

logger = logging.getLogger(__name__)
FALLBACK = "🏅"
PREFIX = "m"


def MedalRoles(member, config: dict) -> list:
    """The medal roles the member has, most important (highest in Discord) first."""
    Chosen = set(config.get("medal_roles") or [])
    return sorted((R for R in getattr(member, "roles", []) if R.id in Chosen), key=lambda R: -R.position)


def EmojiName(role_id: int, icon_key: str) -> str:
    """m<role>_<icon>: the icon part tells when the role's icon changed (max 32 characters)."""
    return f"{PREFIX}{role_id}_{icon_key.replace('a_', '')[:8]}"


class MedalEmojis:
    """role id -> emoji text, uploading role icons as application emojis when needed."""

    def __init__(self, client):
        self.client = client
        self.existing: dict[str, discord.Emoji] | None = None
        self.lock = asyncio.Lock()

    async def Load(self):
        if self.existing is None:
            try:
                self.existing = {E.name: E for E in await self.client.fetch_application_emojis() if E.name.startswith(PREFIX)}
            except discord.HTTPException as e:
                logger.warning(f"[Medals] Can't list the bot's emojis: {e}")
                self.existing = {}

    async def Get(self, role) -> str:
        if getattr(role, "unicode_emoji", None):
            return role.unicode_emoji
        Icon = getattr(role, "icon", None)
        if Icon is None:
            return FALLBACK
        Name = EmojiName(role.id, Icon.key)
        if self.existing is not None and Name in self.existing:
            return str(self.existing[Name])
        async with self.lock:
            await self.Load()
            if Name in self.existing:
                return str(self.existing[Name])
            try:
                for Old in [E for N, E in self.existing.items() if N.startswith(f"{PREFIX}{role.id}_")]:
                    await Old.delete()  # the icon changed: the old one goes
                    self.existing.pop(Old.name, None)
                New = await self.client.create_application_emoji(name=Name, image=await Icon.read())
            except (discord.HTTPException, ValueError) as e:
                logger.warning(f"[Medals] Couldn't make the emoji for role {role.id}: {e}")
                return FALLBACK
            self.existing[Name] = New
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
