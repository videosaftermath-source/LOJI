"""
The only place that changes balances.

Every change is a single atomic Mongo update (conditional filter + $inc) and
writes an entry to the ledger. Transfers use a transaction when the cluster is
a replica set (MongoDB Atlas always is).

Locks are in-process asyncio locks: enough while the bot runs as one process.
If it's ever split across processes, switch to DB-based locks.
"""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from pymongo import ReturnDocument

from core.economy.constants import CREATED, DESTROYED, LEDGER, TRANSFER, USERS

logger = logging.getLogger(__name__)


class EconomyError(Exception):
    """Base error; the message is safe to show to users."""


class InvalidAmount(EconomyError):
    pass


class InsufficientFunds(EconomyError):
    def __init__(self, balance: int):
        super().__init__("No tienes suficientes créditos.")
        self.balance = balance


class ConditionFailed(EconomyError):
    """The extra filter didn't match (cooldown not over, already claimed, ...)."""


def Now() -> datetime:
    return datetime.now(timezone.utc)


class EconomyService:
    def __init__(self, db, client=None):
        self.db = db
        self.client = client
        self.users = db[USERS]
        self.ledger = db[LEDGER]
        self.transactions = False
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def Setup(self):
        """Creates indexes and checks whether transactions are available."""
        await self.users.create_index([("guild_id", 1), ("user_id", 1)], unique=True)
        await self.users.create_index([("guild_id", 1), ("balance", -1)])
        await self.users.create_index([("guild_id", 1), ("last_active", -1)])
        await self.ledger.create_index([("guild_id", 1), ("user_id", 1), ("ts", -1)])
        await self.ledger.create_index([("guild_id", 1), ("ts", -1)])
        if self.client is not None:
            try:
                Hello = await self.client.admin.command("hello")
                self.transactions = bool(Hello.get("setName"))
            except Exception as e:
                logger.warning(f"[Economy] Couldn't check replica set: {e}")
        logger.info(
            f"[Economy] Ready. Replica set / transactions: {'yes' if self.transactions else 'no'}"
        )

    @contextlib.asynccontextmanager
    async def Lock(self, guild_id: int, *user_ids: int):
        """Locks one or more users, always in the same order to avoid deadlocks."""
        Locks = [
            self._locks.setdefault((guild_id, U), asyncio.Lock())
            for U in sorted(set(user_ids))
        ]
        async with contextlib.AsyncExitStack() as Stack:
            for L in Locks:
                await Stack.enter_async_context(L)
            yield

    @contextlib.asynccontextmanager
    async def Transaction(self):
        """Yields a session inside a transaction, or None when transactions aren't available."""
        if not self.transactions:
            yield None
            return
        async with self.client.start_session() as Session:
            async with await Session.start_transaction():
                yield Session

    def IsLocked(self, guild_id: int, user_id: int) -> bool:
        L = self._locks.get((guild_id, user_id))
        return bool(L and L.locked())

    async def Account(self, guild_id: int, user_id: int, session=None) -> dict:
        """Gets the user's account, creating it if needed."""
        return await self.users.find_one_and_update(
            {"guild_id": guild_id, "user_id": user_id},
            {
                "$setOnInsert": {
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "balance": 0,
                    "created_at": Now(),
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )

    async def PeekBalance(self, guild_id: int, user_id: int) -> int:
        """Balance without creating an account (0 if there isn't one)."""
        Account = await self.users.find_one(
            {"guild_id": guild_id, "user_id": user_id}, {"balance": 1}
        )
        return int((Account or {}).get("balance", 0))

    async def Balance(self, guild_id: int, user_id: int) -> int:
        return int((await self.Account(guild_id, user_id)).get("balance", 0))

    async def Log(self, guild_id, user_id, amount, reason, kind, balance_after, ref=None, session=None, extra=None):
        await self.ledger.insert_one(
            {
                "guild_id": guild_id,
                "user_id": user_id,
                "amount": amount,
                "reason": reason,
                "kind": kind,
                "balance_after": balance_after,
                "ref": ref,
                "ts": Now(),
                **(extra or {}),
            },
            session=session,
        )

    async def Change(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
        reason: str,
        *,
        kind: str,
        ref=None,
        when: dict | None = None,
        also_set: dict | None = None,
        also_inc: dict | None = None,
        session=None,
        extra: dict | None = None,
    ) -> dict:
        """
        Adds `amount` (negative to remove) in one atomic update.
        `when` is an extra filter that must match (e.g. a cooldown), and `also_set`
        fields are written in the same update. Returns the updated account.
        """
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise InvalidAmount("La cantidad tiene que ser un número entero.")
        await self.Account(guild_id, user_id, session=session)
        Filter = {"guild_id": guild_id, "user_id": user_id, **(when or {})}
        if amount < 0:
            Filter["balance"] = {"$gte": -amount}
        Update = {"$inc": {"balance": amount, **(also_inc or {})}}
        if also_set:
            Update["$set"] = also_set
        Updated = await self.users.find_one_and_update(
            Filter, Update, return_document=ReturnDocument.AFTER, session=session
        )
        if Updated is None:
            Current = await self.users.find_one(
                {"guild_id": guild_id, "user_id": user_id}, session=session
            )
            Balance = int((Current or {}).get("balance", 0))
            if amount < 0 and Balance < -amount:
                raise InsufficientFunds(Balance)
            raise ConditionFailed("No se cumplen las condiciones.")
        await self.Log(guild_id, user_id, amount, reason, kind, Updated["balance"], ref, session, extra)
        return Updated

    async def Add(self, guild_id: int, user_id: int, amount: int, reason: str, **kw) -> dict:
        """Creates money for a user (work, daily, admin...)."""
        if amount <= 0:
            raise InvalidAmount("La cantidad tiene que ser mayor que 0.")
        return await self.Change(guild_id, user_id, amount, reason, kind=kw.pop("kind", CREATED), **kw)

    async def Remove(self, guild_id: int, user_id: int, amount: int, reason: str, **kw) -> dict:
        """Takes money from a user. Raises InsufficientFunds if they don't have it."""
        if amount <= 0:
            raise InvalidAmount("La cantidad tiene que ser mayor que 0.")
        return await self.Change(guild_id, user_id, -amount, reason, kind=kw.pop("kind", DESTROYED), **kw)

    async def Transfer(
        self, guild_id: int, sender: int, receiver: int, amount: int, reason: str, fee: int = 0
    ) -> tuple[dict, dict]:
        """
        Moves money between users, in a transaction when available.
        The sender also pays `fee`, which is destroyed (logged as `fee` on their entry).
        """
        if sender == receiver:
            raise InvalidAmount("No puedes pagarte a ti mismo.")
        if not isinstance(amount, int) or amount <= 0 or not isinstance(fee, int) or fee < 0:
            raise InvalidAmount("La cantidad tiene que ser mayor que 0.")
        Total = amount + fee
        Fee = {"fee": fee} if fee else None
        Ref = f"transfer:{sender}:{receiver}:{Now().timestamp()}"
        Active = {"last_active": Now()}
        async with self.Lock(guild_id, sender, receiver):
            if self.transactions:
                async with self.client.start_session() as Session:
                    async with await Session.start_transaction():
                        From = await self.Change(guild_id, sender, -Total, reason, kind=TRANSFER, ref=Ref, also_set=Active, session=Session, extra=Fee)
                        To = await self.Change(guild_id, receiver, amount, reason, kind=TRANSFER, ref=Ref, session=Session)
                        return From, To
            From = await self.Change(guild_id, sender, -Total, reason, kind=TRANSFER, ref=Ref, also_set=Active, extra=Fee)
            try:
                To = await self.Change(guild_id, receiver, amount, reason, kind=TRANSFER, ref=Ref)
            except Exception:
                # No transaction to roll back: give the sender their money back.
                await self.Change(guild_id, sender, Total, f"Reembolso: {reason}", kind=TRANSFER, ref=Ref)
                raise
            return From, To

    async def Top(self, guild_id: int, skip: int, limit: int) -> list[dict]:
        return (
            await self.users.find({"guild_id": guild_id, "balance": {"$gt": 0}})
            .sort([("balance", -1), ("user_id", 1)])
            .skip(skip)
            .limit(limit)
            .to_list(length=limit)
        )

    async def CountRanked(self, guild_id: int) -> int:
        return await self.users.count_documents({"guild_id": guild_id, "balance": {"$gt": 0}})

    async def Rank(self, guild_id: int, user_id: int) -> int | None:
        Balance = await self.Balance(guild_id, user_id)
        if Balance <= 0:
            return None
        return await self.users.count_documents({"guild_id": guild_id, "balance": {"$gt": Balance}}) + 1


def Build():
    from core.db import client, db

    return EconomyService(db, client)


economy: EconomyService | None = None


def Economy() -> EconomyService:
    """The shared service (created on first use)."""
    global economy
    if economy is None:
        economy = Build()
    return economy
