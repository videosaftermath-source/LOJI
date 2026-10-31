"""Shared economy services, created once and used by every cog."""

from dataclasses import dataclass

from core.economy.bonuses import Bonuses
from core.economy.casino import Casino
from core.economy.codes import Codes
from core.economy.economics import Economics
from core.economy.gacha import Gacha
from core.economy.marcha import Marcha
from core.economy.pets import Pets
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
    pets: Pets
    gacha: Gacha
    casino: Casino
    economics: Economics
    marcha: Marcha

    async def Setup(self):
        await self.economy.Setup()
        await self.shop.Setup()
        await self.codes.Setup()
        await self.quests.Setup()
        await self.pets.Setup()
        await self.gacha.Setup()
        await self.economics.Setup()
        await self.marcha.Setup()


_services: Services | None = None


def Build(economy: EconomyService) -> Services:
    S = Shop(economy.db, economy)
    P = Pets(economy.db, economy)
    E = Economics(economy.db, economy)
    G = Gacha(economy.db, economy, S, P)
    S.pets = P
    S.bonuses.pets = P
    S.economics = P.economics = G.economics = E
    C = Casino(economy, P)
    return Services(economy, S, Codes(economy.db, S), Quests(economy.db, economy, S), S.bonuses, P, G, C, E, Marcha(economy.db, economy, C))


def Eco() -> Services:
    global _services
    if _services is None:
        _services = Build(Economy())
    return _services
