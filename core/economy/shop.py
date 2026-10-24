"""Shop items, inventories and buying/using them."""

import random
import string
from datetime import datetime, timezone

import discord
from pymongo import ReturnDocument

from core.economy.bonuses import Bonuses
from core.economy.constants import (
    COLLECTIBLE,
    CONSUMABLE,
    INVENTORY,
    ITEMS,
    MAX_BUY_AT_ONCE,
    MAX_ITEMS,
    ROLE,
)
from core.economy.service import EconomyError, EconomyService


class ShopError(EconomyError):
    """Message is safe to show to users."""


def NewId(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def Price(item: dict, config: dict) -> int:
    """Current price of one unit. (Inflation and demand come in phase 6.)"""
    return int(item["price"])


def CanGiveRole(guild: discord.Guild, role: discord.Role | None) -> str | None:
    """Why the bot can't give this role, or None if it can."""
    if role is None:
        return "Ese rol ya no existe."
    Me = guild.me
    if not Me.guild_permissions.manage_roles:
        return "Me falta el permiso de **Gestionar roles**."
    if role >= Me.top_role or role.managed or role.is_default():
        return f"No puedo dar {role.mention}: ponme un rol más alto que ese."
    return None


class Shop:
    def __init__(self, db, economy: EconomyService):
        self.items = db[ITEMS]
        self.inventory = db[INVENTORY]
        self.economy = economy
        self.bonuses = Bonuses(db)

    async def Setup(self):
        await self.items.create_index([("guild_id", 1), ("item_id", 1)], unique=True)
        await self.inventory.create_index([("guild_id", 1), ("user_id", 1), ("item_id", 1)], unique=True)
        await self.bonuses.Setup()

    # ---- items (admin) ----

    async def Create(self, guild_id: int, data: dict) -> dict:
        if await self.items.count_documents({"guild_id": guild_id}) >= MAX_ITEMS:
            raise ShopError(f"La tienda ya tiene el máximo de {MAX_ITEMS} items.")
        Item = {
            "guild_id": guild_id,
            "item_id": NewId(),
            "enabled": True,
            "created_at": datetime.now(timezone.utc),
            **data,
        }
        await self.items.insert_one(Item)
        return Item

    async def Update(self, guild_id: int, item_id: str, data: dict) -> dict | None:
        return await self.items.find_one_and_update(
            {"guild_id": guild_id, "item_id": item_id},
            {"$set": data},
            return_document=ReturnDocument.AFTER,
        )

    async def Delete(self, guild_id: int, item_id: str):
        await self.items.delete_one({"guild_id": guild_id, "item_id": item_id})

    async def Get(self, guild_id: int, item_id: str) -> dict | None:
        return await self.items.find_one({"guild_id": guild_id, "item_id": item_id})

    async def List(self, guild_id: int, only_enabled: bool = False) -> list[dict]:
        Filter = {"guild_id": guild_id}
        if only_enabled:
            Filter["enabled"] = True
        return await self.items.find(Filter).sort("price", 1).to_list(length=MAX_ITEMS)

    # ---- inventory ----

    async def Inventory(self, guild_id: int, user_id: int) -> list[dict]:
        return await self.inventory.find(
            {"guild_id": guild_id, "user_id": user_id, "qty": {"$gt": 0}}
        ).to_list(length=MAX_ITEMS * 4)

    async def Give(self, guild_id: int, user_id: int, item_id: str, qty: int, bought: int = 0, session=None):
        await self.inventory.update_one(
            {"guild_id": guild_id, "user_id": user_id, "item_id": item_id},
            {"$inc": {"qty": qty, "bought": bought}},
            upsert=True,
            session=session,
        )

    # ---- buying ----

    async def Buy(self, member: discord.Member, item_id: str, qty: int, config: dict) -> tuple[dict, int, dict]:
        """Buys `qty` units. Returns (item, total paid, updated account)."""
        Guild = member.guild
        if not 1 <= qty <= MAX_BUY_AT_ONCE:
            raise ShopError(f"Puedes comprar entre 1 y {MAX_BUY_AT_ONCE} a la vez.")
        async with self.economy.Lock(Guild.id, member.id):
            Item = await self.Get(Guild.id, item_id)
            if not Item or not Item.get("enabled"):
                raise ShopError("Ese item ya no está a la venta.")
            Role = None
            if Item["type"] == ROLE:
                qty = 1
                Role = Guild.get_role(Item.get("role_id") or 0)
                Problem = CanGiveRole(Guild, Role)
                if Problem:
                    raise ShopError(Problem)
                if Role in member.roles:
                    raise ShopError(f"Ya tienes {Role.mention}.")

            Owned = await self.inventory.find_one({"guild_id": Guild.id, "user_id": member.id, "item_id": item_id}) or {}
            Limit = Item.get("per_user_limit")
            if Limit and int(Owned.get("bought", 0)) + qty > Limit:
                Left = max(0, Limit - int(Owned.get("bought", 0)))
                raise ShopError(f"Solo puedes comprar {Limit} de este item" + (f" (te quedan {Left})." if Left else " y ya llegaste al límite."))

            Total = Price(Item, config) * qty
            async with self.economy.Transaction() as Session:
                await self.ReserveStock(Item, qty, Session)
                try:
                    Account = await self.economy.Remove(
                        Guild.id, member.id, Total, f"Compra: {qty}x {Item['name']}", ref=f"item:{item_id}", session=Session
                    )
                except Exception:
                    if Session is None:
                        await self.ReleaseStock(Item, qty)
                    raise
                await self.Give(Guild.id, member.id, item_id, qty, bought=qty, session=Session)

            if Role:
                try:
                    await member.add_roles(Role, reason=f"Compra en la tienda ({Item['name']})")
                except discord.HTTPException:
                    await self.Refund(member, Item, qty, Total)
                    raise ShopError(f"No pude darte {Role.mention}, te devolví el dinero.")
        return Item, Total, Account

    async def ReserveStock(self, item: dict, qty: int, session=None):
        if item.get("stock") is None:
            return
        Reserved = await self.items.find_one_and_update(
            {"_id": item["_id"], "stock": {"$gte": qty}},
            {"$inc": {"stock": -qty}},
            session=session,
        )
        if Reserved is None:
            raise ShopError("¡Se agotó! No queda suficiente stock.")

    async def ReleaseStock(self, item: dict, qty: int):
        if item.get("stock") is not None:
            await self.items.update_one({"_id": item["_id"]}, {"$inc": {"stock": qty}})

    async def Refund(self, member: discord.Member, item: dict, qty: int, total: int):
        await self.ReleaseStock(item, qty)
        await self.Give(member.guild.id, member.id, item["item_id"], -qty, bought=-qty)
        await self.economy.Add(member.guild.id, member.id, total, f"Reembolso: {item['name']}", ref=f"item:{item['item_id']}")

    # ---- using ----

    async def Use(self, member: discord.Member, item_id: str) -> dict:
        """Uses one consumable and starts its boost. Returns the item."""
        Guild = member.guild
        Item = await self.Get(Guild.id, item_id)
        if not Item:
            raise ShopError("Ese item ya no existe.")
        if Item["type"] != CONSUMABLE:
            raise ShopError("Ese item no se puede usar." if Item["type"] == COLLECTIBLE else "Los roles se dan al comprarlos.")
        Taken = await self.inventory.find_one_and_update(
            {"guild_id": Guild.id, "user_id": member.id, "item_id": item_id, "qty": {"$gte": 1}},
            {"$inc": {"qty": -1}},
        )
        if Taken is None:
            raise ShopError("No tienes ese item.")
        Effect = Item["effect"]
        await self.bonuses.Add(Guild.id, member.id, Effect["kind"], Effect["value"], Effect["seconds"], f"item:{item_id}")
        return Item
