"""
Buzón (/mail, tasks): departments, the three high offices and their credentials, and permissions.

Permissions come from Discord roles. A credential is an optional bypass for the three high offices
(Tenno, Consejo Supremo, Director de Moderación): it lets them act without the role. Credentials are
stored hashed and never live in the code.
"""

import hashlib
import hmac
import re
import secrets
import string
import time
import uuid

CONFIG = "mail_config"
CACHE_SECONDS = 30

# The high offices. Each has a role (configurable) and an optional credential.
OFFICES = {
    "tenno": "Tenno",
    "consejo": "Consejo Supremo",
    "director": "Director de Moderación",
}
# Who can do what (by role or credential).
DECIDE_SUGGESTIONS = ("tenno", "consejo")
MANAGE_ANY_TASK = ("tenno", "consejo", "director")
CONFIGURE = ("tenno",)

DEFAULT_DEPARTMENTS = [
    ("Moderación", ""),
    ("Comité de Ética", "Mod Senior"),
    ("Control de Calidad", "Mod Senior"),
    ("Gestión de la Comunidad", "Mod Senior"),
    ("Gestión del Staff", "Mod Senior"),
]
MAX_DEPARTMENTS = 20  # one select menu holds 25 options; this leaves room
NAME_MAX = 50

CREDENTIAL = re.compile(r"^([A-Z])-?(\d{4})$")
MAX_FAILS = 5
LOCK_SECONDS = 10 * 60
HASH_ROUNDS = 120_000


class MailError(Exception):
    """Message is safe to show to users."""


# ---------------- credentials ----------------


def NormalizeCredential(text: str) -> str:
    """'m1808', 'M-1808 ' -> 'M-1808'. Raises MailError if it isn't letter + 4 digits."""
    Match = CREDENTIAL.match((text or "").strip().upper().replace(" ", ""))
    if not Match:
        raise MailError("La credencial es una letra y 4 números, por ejemplo `M-1808`.")
    return f"{Match.group(1)}-{Match.group(2)}"


def NewCredential(letter: str | None = None) -> str:
    Letter = letter or secrets.choice(string.ascii_uppercase)
    return f"{Letter}-{secrets.randbelow(10_000):04d}"


def Hash(code: str, salt: str | None = None) -> dict:
    Salt = salt or secrets.token_hex(16)
    Digest = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(Salt), HASH_ROUNDS).hex()
    return {"salt": Salt, "hash": Digest}


def Matches(code: str, stored: dict | None) -> bool:
    if not stored:
        return False
    try:
        Code = NormalizeCredential(code)
    except MailError:
        return False
    return hmac.compare_digest(Hash(Code, stored["salt"])["hash"], stored["hash"])


class Attempts:
    """Locks someone out for a while after too many wrong credentials (stops guessing)."""

    def __init__(self):
        self.fails: dict[tuple[int, int], list[float]] = {}

    def LockedFor(self, key: tuple[int, int], now: float | None = None) -> int:
        Now = now if now is not None else time.monotonic()
        Recent = [T for T in self.fails.get(key, []) if Now - T < LOCK_SECONDS]
        self.fails[key] = Recent
        return int(LOCK_SECONDS - (Now - Recent[0])) if len(Recent) >= MAX_FAILS else 0

    def Fail(self, key: tuple[int, int], now: float | None = None):
        self.fails.setdefault(key, []).append(now if now is not None else time.monotonic())

    def Clear(self, key: tuple[int, int]):
        self.fails.pop(key, None)


ATTEMPTS = Attempts()


def CheckCredential(guild_id: int, user_id: int, code: str, offices: tuple[str, ...], config: dict, attempts: Attempts = ATTEMPTS) -> str:
    """Returns which office the credential belongs to (among `offices`). Raises MailError otherwise."""
    Key = (guild_id, user_id)
    Locked = attempts.LockedFor(Key)
    if Locked:
        raise MailError(f"Demasiados intentos fallidos. Espera {Locked // 60 + 1} min.")
    for Office in offices:
        if Matches(code, config["offices"][Office].get("credential")):
            attempts.Clear(Key)
            return Office
    attempts.Fail(Key)
    raise MailError("Credencial incorrecta.")


# ---------------- permissions ----------------


def RoleIds(member) -> set[int]:
    return {R.id for R in getattr(member, "roles", [])}


def OfficesOf(member, config: dict) -> set[str]:
    """High offices the member holds by role."""
    Roles = RoleIds(member)
    return {O for O, D in config["offices"].items() if D.get("role") and D["role"] in Roles}


def HasAny(member, offices: tuple[str, ...], config: dict) -> bool:
    return bool(OfficesOf(member, config) & set(offices))


def IsStaff(member, config: dict) -> bool:
    Staff = config.get("staff_role")
    return bool(Staff and Staff in RoleIds(member)) or bool(OfficesOf(member, config))


def InDepartment(member, department: dict) -> bool:
    return bool(department.get("role") and department["role"] in RoleIds(member))


def CanConfigure(member, config: dict) -> bool:
    """The Tenno, or a server administrator (so the first setup is possible)."""
    Perms = getattr(member, "guild_permissions", None)
    return HasAny(member, CONFIGURE, config) or bool(Perms and Perms.administrator)


# ---------------- storage ----------------


def DefaultConfig(guild_id: int) -> dict:
    return {
        "_id": guild_id,
        "staff_role": None,
        "suggestions_channel": None,
        "debate_channel": None,
        "offices": {O: {"role": None, "credential": None} for O in OFFICES},
        "departments": [NewDepartment(Name, Group) for Name, Group in DEFAULT_DEPARTMENTS],
    }


def NewDepartment(name: str, group: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:8], "name": name[:NAME_MAX], "group": group[:NAME_MAX], "role": None, "channel": None}


def Department(config: dict, department_id: str) -> dict | None:
    return next((D for D in config["departments"] if D["id"] == department_id), None)


class MailConfig:
    def __init__(self, db):
        self.col = db[CONFIG]
        self._cache: dict[int, tuple[float, dict]] = {}

    async def Get(self, guild_id: int) -> dict:
        Cached = self._cache.get(guild_id)
        if Cached and Cached[0] > time.monotonic():
            return Cached[1]
        Doc = await self.col.find_one({"_id": guild_id})
        if not Doc:
            Doc = DefaultConfig(guild_id)
            await self.col.update_one({"_id": guild_id}, {"$setOnInsert": Doc}, upsert=True)
            Doc = await self.col.find_one({"_id": guild_id}) or Doc
        for Office in OFFICES:  # offices added later
            Doc["offices"].setdefault(Office, {"role": None, "credential": None})
        self._cache[guild_id] = (time.monotonic() + CACHE_SECONDS, Doc)
        return Doc

    async def Set(self, guild_id: int, changes: dict) -> dict:
        await self.Get(guild_id)
        await self.col.update_one({"_id": guild_id}, {"$set": changes})
        self._cache.pop(guild_id, None)
        return await self.Get(guild_id)

    async def SetCredential(self, guild_id: int, office: str, code: str | None) -> str:
        """Sets (or generates, if `code` is empty) an office's credential. Returns the code once."""
        if office not in OFFICES:
            raise MailError("Ese cargo no existe.")
        Code = NormalizeCredential(code) if code else NewCredential()
        await self.Set(guild_id, {f"offices.{office}.credential": Hash(Code)})
        return Code

    async def AddDepartment(self, guild_id: int, name: str, group: str = "") -> dict:
        Config = await self.Get(guild_id)
        Name = " ".join(name.split())
        if not Name:
            raise MailError("Ponle un nombre.")
        if len(Config["departments"]) >= MAX_DEPARTMENTS:
            raise MailError(f"Como mucho {MAX_DEPARTMENTS} departamentos.")
        if any(D["name"].lower() == Name.lower() for D in Config["departments"]):
            raise MailError("Ya hay un departamento con ese nombre.")
        New = NewDepartment(Name, " ".join(group.split()))
        await self.Set(guild_id, {"departments": Config["departments"] + [New]})
        return New

    async def UpdateDepartment(self, guild_id: int, department_id: str, changes: dict) -> dict:
        Config = await self.Get(guild_id)
        Departments = [dict(D, **changes) if D["id"] == department_id else D for D in Config["departments"]]
        if not any(D["id"] == department_id for D in Departments):
            raise MailError("Ese departamento ya no existe.")
        await self.Set(guild_id, {"departments": Departments})
        return Department(await self.Get(guild_id), department_id)

    async def RemoveDepartment(self, guild_id: int, department_id: str):
        Config = await self.Get(guild_id)
        await self.Set(guild_id, {"departments": [D for D in Config["departments"] if D["id"] != department_id]})


_shared: MailConfig | None = None


def Mail() -> MailConfig:
    global _shared
    if _shared is None:
        from core.db import db

        _shared = MailConfig(db)
    return _shared
