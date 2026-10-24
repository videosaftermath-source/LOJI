"""Redeem codes created by admins."""

import re
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from core.economy.constants import CODE_USES, CODES, MAX_CODES
from core.economy.rewards import Aware
from core.economy.service import EconomyError
from core.economy.shop import NewId, Shop

CODE_FORMAT = re.compile(r"^[A-Z0-9_-]{3,32}$")


class CodeError(EconomyError):
    """Message is safe to show to users."""


def CleanCode(code: str) -> str:
    return code.strip().upper().replace(" ", "")


class Codes:
    def __init__(self, db, shop: Shop):
        self.codes = db[CODES]
        self.uses = db[CODE_USES]
        self.shop = shop
        self.economy = shop.economy

    async def Setup(self):
        await self.codes.create_index([("guild_id", 1), ("code", 1)], unique=True)
        await self.uses.create_index([("guild_id", 1), ("code", 1), ("user_id", 1)], unique=True)

    async def Create(
        self,
        guild_id: int,
        code: str | None,
        credits: int,
        items: list[dict],
        max_uses: int | None,
        expires_at: datetime | None,
        created_by: int,
    ) -> dict:
        Code = CleanCode(code) if code else NewId(8)
        if not CODE_FORMAT.match(Code):
            raise CodeError("El código solo puede tener letras, números, `-` y `_` (de 3 a 32).")
        if credits <= 0 and not items:
            raise CodeError("El código tiene que dar créditos o un item.")
        if await self.codes.count_documents({"guild_id": guild_id}) >= MAX_CODES:
            raise CodeError(f"Ya hay {MAX_CODES} códigos. Borra alguno primero.")
        Doc = {
            "guild_id": guild_id,
            "code": Code,
            "credits": int(credits),
            "items": items,
            "max_uses": max_uses,
            "uses": 0,
            "expires_at": expires_at,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc),
        }
        try:
            await self.codes.insert_one(Doc)
        except DuplicateKeyError:
            raise CodeError(f"Ya existe el código `{Code}`.")
        return Doc

    async def List(self, guild_id: int) -> list[dict]:
        return await self.codes.find({"guild_id": guild_id}).sort("created_at", -1).to_list(length=MAX_CODES)

    async def Delete(self, guild_id: int, code: str):
        await self.codes.delete_one({"guild_id": guild_id, "code": code})

    async def Redeem(self, guild_id: int, user_id: int, code: str) -> dict:
        """Gives the code's reward. Each user can use a code once."""
        Code = CleanCode(code)
        Doc = await self.codes.find_one({"guild_id": guild_id, "code": Code})
        Now = datetime.now(timezone.utc)
        if not Doc:
            raise CodeError("Ese código no existe 🤔")
        if Doc.get("expires_at") and Aware(Doc["expires_at"]) <= Now:
            raise CodeError("Ese código ya caducó ⌛")
        # The unique index makes a second use (or a double click) fail here.
        try:
            await self.uses.insert_one({"guild_id": guild_id, "code": Code, "user_id": user_id, "ts": Now})
        except DuplicateKeyError:
            raise CodeError("Ya canjeaste ese código, tramposo 👀")
        Filter = {"_id": Doc["_id"]}
        if Doc.get("max_uses"):
            Filter["uses"] = {"$lt": Doc["max_uses"]}
        if not await self.codes.find_one_and_update(Filter, {"$inc": {"uses": 1}}):
            await self.uses.delete_one({"guild_id": guild_id, "code": Code, "user_id": user_id})
            raise CodeError("Ese código ya se agotó 😢")

        if Doc.get("credits"):
            await self.economy.Add(guild_id, user_id, Doc["credits"], f"Código {Code}", ref=f"code:{Code}")
        for Reward in Doc.get("items", []):
            await self.shop.Give(guild_id, user_id, Reward["item_id"], int(Reward["qty"]))
        return Doc
