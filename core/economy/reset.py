"""Wipes one user's economy (admin tool for mistakes or abuse)."""

from core.economy.constants import DESTROYED, EFFECTS, INVENTORY, PETS, PITY, PULLS, QUEST_PROGRESS, USERS

# Everything a user owns or has progressed. Code uses are kept on purpose, so a reset
# can't be used to redeem the same codes again; the ledger is kept as the audit trail.
WIPED = {
    INVENTORY: "items",
    EFFECTS: "boosts activos",
    PETS: "mascotas",
    PITY: "contadores del gacha",
    PULLS: "historial del gacha",
    QUEST_PROGRESS: "progreso de misiones",
}
# Kept on the user doc so a reset doesn't pay the one-time boost reward again.
KEEP_FIELDS = ("boost_rewarded",)


async def ResetUser(economy, guild_id: int, user_id: int, admin_id: int, reason: str) -> dict:
    """
    Deletes the user's account (wallet, bank, streaks, stats), pets, items, boosts, gacha
    progress and quest progress. Logs the removed money in the ledger. Returns what was removed.
    """
    db = economy.db
    async with economy.Lock(guild_id, user_id):
        Account = await db[USERS].find_one({"guild_id": guild_id, "user_id": user_id}) or {}
        Money = int(Account.get("balance", 0)) + int(Account.get("bank", 0))
        Summary = {"wallet": int(Account.get("balance", 0)), "bank": int(Account.get("bank", 0))}
        Query = {"guild_id": guild_id, "user_id": user_id}
        for Collection, Label in WIPED.items():
            Summary[Label] = (await db[Collection].delete_many(Query)).deleted_count
        Kept = {K: Account[K] for K in KEEP_FIELDS if K in Account}
        await db[USERS].delete_one(Query)
        if Kept:
            await db[USERS].insert_one({**Query, "balance": 0, **Kept})
        if Money:
            await economy.Log(
                guild_id, user_id, -Summary["wallet"], f"Reinicio de economía por admin {admin_id}: {reason}",
                DESTROYED, 0, ref="reset", extra={"bank": -Summary["bank"]},
            )
    return Summary
