"""Per-guild economy config: defaults from constants.py merged with what's saved in Mongo."""

import copy
import time

from core.economy.constants import CONFIG, DEFAULT_CONFIG, SETTINGS_BY_PATH, Setting

CACHE_SECONDS = 30
YES = ("si", "sí", "s", "yes", "y", "true", "1", "on")
NO = ("no", "n", "false", "0", "off")


class ConfigError(ValueError):
    """Invalid config value; the message is shown to the admin."""


def Merge(defaults: dict, saved: dict) -> dict:
    """Deep-merges saved values over defaults."""
    Result = copy.deepcopy(defaults)
    for Key, Value in (saved or {}).items():
        if isinstance(Value, dict) and isinstance(Result.get(Key), dict):
            Result[Key] = Merge(Result[Key], Value)
        else:
            Result[Key] = Value
    return Result


def GetPath(config: dict, path: str):
    Value = config
    for Part in path.split("."):
        Value = Value[Part]
    return Value


def Parse(setting: Setting, raw: str):
    """Turns admin input into a validated value."""
    raw = raw.strip()
    if setting.kind is bool:
        Lowered = raw.lower()
        if Lowered in YES:
            return True
        if Lowered in NO:
            return False
        raise ConfigError(f"**{setting.label}**: responde `sí` o `no`.")
    if setting.kind is float:
        try:
            Value = float(raw.replace(",", ".").rstrip("%"))
        except ValueError:
            raise ConfigError(f"**{setting.label}** tiene que ser un número (puede tener decimales, ej. `0.5`).")
        if not setting.minimum <= Value <= setting.maximum:
            raise ConfigError(f"**{setting.label}** tiene que estar entre {setting.minimum} y {setting.maximum}.")
        return Value
    if setting.kind is int:
        try:
            Value = int(raw.replace(".", "").replace(",", "").replace("_", "").replace(" ", ""))
        except ValueError:
            raise ConfigError(f"**{setting.label}** tiene que ser un número entero.")
        if not setting.minimum <= Value <= setting.maximum:
            raise ConfigError(
                f"**{setting.label}** tiene que estar entre {setting.minimum:,} y {setting.maximum:,}."
            )
        return Value
    if not setting.minimum <= len(raw) <= setting.maximum:
        raise ConfigError(
            f"**{setting.label}** tiene que tener entre {setting.minimum} y {setting.maximum} caracteres."
        )
    return raw


def Validate(config: dict):
    """Checks rules that involve more than one value."""
    if config["work"]["min"] > config["work"]["max"]:
        raise ConfigError("El mínimo de trabajar no puede ser mayor que el máximo.")
    if config["daily"]["grace"] <= config["daily"]["cooldown"]:
        raise ConfigError("El tiempo para perder la racha tiene que ser mayor que la espera del diario.")
    Activity = config["activity"]
    if Activity["min"] > Activity["max"]:
        raise ConfigError("El mínimo por mensaje no puede ser mayor que el máximo.")
    if Activity["soft_cap"] > Activity["hard_cap"]:
        raise ConfigError("El tope suave no puede ser mayor que el tope máximo.")
    Gacha = config["gacha"]
    if Gacha["rate_legendary"] + Gacha["rate_epic"] + Gacha["rate_rare"] >= 1:
        raise ConfigError("Las probabilidades legendaria + épica + rara tienen que sumar menos de 1 (el resto es común).")
    if Gacha["soft_pity"] > Gacha["hard_pity"]:
        raise ConfigError("El soft pity tiene que empezar antes del hard pity.")
    for Game, Settings in config["casino"].items():
        if Settings["min"] > Settings["max"]:
            raise ConfigError(f"En {Game}, la apuesta mínima no puede ser mayor que la máxima.")


class EconomyConfig:
    """Reads and writes eco_config with a short cache."""

    def __init__(self, db):
        self.db = db
        self._cache: dict[int, tuple[float, dict]] = {}

    async def Get(self, guild_id: int) -> dict:
        Cached = self._cache.get(guild_id)
        if Cached and Cached[0] > time.monotonic():
            return Cached[1]
        Saved = await self.db[CONFIG].find_one({"_id": guild_id}) or {}
        Saved.pop("_id", None)
        Config = Merge(DEFAULT_CONFIG, Saved)
        self._cache[guild_id] = (time.monotonic() + CACHE_SECONDS, Config)
        return Config

    async def Set(self, guild_id: int, path: str, raw: str | None) -> dict:
        """Saves one value (None = back to default). Returns the new config."""
        Option = SETTINGS_BY_PATH.get(path)
        if not Option:
            raise ConfigError("Esa opción no existe.")
        Current = await self.Get(guild_id)
        Candidate = copy.deepcopy(Current)
        *Parents, Key = path.split(".")
        Value = GetPath(DEFAULT_CONFIG, path) if raw is None or not raw.strip() else Parse(Option, raw)
        Target = Candidate
        for Part in Parents:
            Target = Target[Part]
        Target[Key] = Value
        Validate(Candidate)
        if raw is None or not raw.strip():
            Update = {"$unset": {path: ""}}
        else:
            Update = {"$set": {path: Value}}
        await self.db[CONFIG].update_one({"_id": guild_id}, Update, upsert=True)
        self._cache.pop(guild_id, None)
        return await self.Get(guild_id)

    async def SetChannels(self, guild_id: int, channel_ids: list[int]) -> dict:
        """Sets the channels where chatting pays."""
        await self.db[CONFIG].update_one(
            {"_id": guild_id}, {"$set": {"activity.channels": list(channel_ids)}}, upsert=True
        )
        self._cache.pop(guild_id, None)
        return await self.Get(guild_id)


_shared: EconomyConfig | None = None


def EcoConfig() -> EconomyConfig:
    """The shared config reader, so edits clear one cache for everyone."""
    global _shared
    if _shared is None:
        from core.db import db

        _shared = EconomyConfig(db)
    return _shared
