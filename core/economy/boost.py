"""Perks for people who boost the server."""

from core.economy.constants import CREATED

MAX_TOP_RATE = 0.99  # legendary + epic + rare never fill the whole table


def IsBooster(member) -> bool:
    return getattr(member, "premium_since", None) is not None


def EarningsMultiplier(member, config: dict) -> float:
    """x1.3 (by default) on work, daily, chat and voice earnings for boosters."""
    Settings = config["booster"]
    return float(Settings["multiplier"]) if Settings["enabled"] and IsBooster(member) else 1.0


def Boosted(amount: int, member, config: dict) -> int:
    return int(round(amount * EarningsMultiplier(member, config)))


def GachaSettings(member, config: dict) -> dict:
    """Gacha settings for this player: boosters get higher legendary/epic rates (pity stays the same)."""
    Settings = dict(config["gacha"])
    Booster = config["booster"]
    if Booster["enabled"] and IsBooster(member) and Booster["gacha_luck"] > 0:
        Extra = 1 + Booster["gacha_luck"]
        Settings["rate_legendary"] = Settings["rate_legendary"] * Extra
        Settings["rate_epic"] = Settings["rate_epic"] * Extra
        # Keep room for the other rarities.
        Top = Settings["rate_legendary"] + Settings["rate_epic"]
        if Top > MAX_TOP_RATE:
            Settings["rate_legendary"] *= MAX_TOP_RATE / Top
            Settings["rate_epic"] *= MAX_TOP_RATE / Top
        Total = Settings["rate_legendary"] + Settings["rate_epic"] + Settings["rate_rare"]
        if Total >= MAX_TOP_RATE:
            Settings["rate_rare"] = max(0.0, MAX_TOP_RATE - Settings["rate_legendary"] - Settings["rate_epic"])
    return Settings


async def RewardBoost(economy, member, config: dict) -> int:
    """
    Pays the one-time boost reward. Paid once per boost: the boost start time is
    stored, so restarts or repeated events don't pay twice. Returns what was paid.
    """
    Settings = config["booster"]
    if not Settings["enabled"] or Settings["reward"] <= 0 or not IsBooster(member):
        return 0
    # Whole seconds: Mongo keeps milliseconds and Discord gives microseconds, so a datetime
    # read back would never equal the new one and the reward would repeat.
    Since = int(member.premium_since.timestamp())
    await economy.Account(member.guild.id, member.id)
    Updated = await economy.users.find_one_and_update(
        {"guild_id": member.guild.id, "user_id": member.id, "boost_rewarded": {"$ne": Since}},
        {"$set": {"boost_rewarded": Since}},
    )
    if Updated is None:
        return 0
    await economy.Add(member.guild.id, member.id, int(Settings["reward"]), "Gracias por boostear", kind=CREATED, ref="boost")
    return int(Settings["reward"])
