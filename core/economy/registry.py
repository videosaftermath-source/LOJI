"""Shared economy services, created once and used by every cog."""

from dataclasses import dataclass

from core.economy.bonuses import Bonuses
from core.economy.codes import Codes
from core.economy.quests import Quests
from core.economy.service import Economy, EconomyService
from core.economy.shop import Shop


@dataclass
class Services:
    economy: EconomyService
    shop: Shop
    codes: Codes
    quests: Quests
    bonuses: Bonuses

    async def Setup(self):
        await self.economy.Setup()
        await self.shop.Setup()
        await self.codes.Setup()
        await self.quests.Setup()


_services: Services | None = None


def Build(economy: EconomyService) -> Services:
    S = Shop(economy.db, economy)
    return Services(economy, S, Codes(economy.db, S), Quests(economy.db, economy, S), S.bonuses)


def Eco() -> Services:
    global _services
    if _services is None:
        _services = Build(Economy())
    return _services
