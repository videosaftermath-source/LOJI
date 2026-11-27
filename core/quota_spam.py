"""
Anti-spam for the staff message quota, in two levels:

1. Writing fast (e.g. "hola" / "como estas" / "bien" / "tu"…): more than `l1_count` messages in `l1_seconds`.
   The extra messages don't count and a soft notice is shown (at most once a minute). Easy to trigger by accident.
2. Real spam: `l2_count` messages in `l2_seconds`. The messages counted in that window are taken back, counting
   stops for `pause_minutes`, and a stern embed (with LOJI's angry banner) mentions whoever was chosen.

Both levels also post an alert in the admins' channel. Only in memory: a restart forgets the recent messages.
"""

from collections import deque

DEFAULTS = {
    "enabled": True,
    "l1_count": 6,
    "l1_seconds": 10,
    "l2_count": 30,
    "l2_seconds": 60,
    "pause_minutes": 10,
    "alert_channel": None,
    "notify": None,  # {"id": 123, "type": "user" | "role"}
    "l1_text": "{user} ⏳ ¡Más despacio! Muchos mensajes seguidos no suman a la cuota: intenta juntarlo en uno solo 😉",
    "l2_title": "👁️ Estoy viéndote.",
    "l2_text": "{user}, acabas de enviar **{cantidad} mensajes** en muy poco tiempo y no cuentan para la cuota.\nEspero tengas una buena explicación a {aviso}.",
    "banner_url": "",
}
L1_NOTICE_EVERY = 60  # seconds between soft notices to the same person


class Tracker:
    def __init__(self):
        self.all: dict = {}  # key -> deque of message times
        self.counted: dict = {}  # key -> deque of times that were added to the quota
        self.paused: dict = {}  # key -> until
        self.noticed: dict = {}  # key -> last soft notice

    def Check(self, key, now: float, s: dict) -> tuple[bool, int, int]:
        """(count this message?, level reached now: 0/1/2, messages to take back)."""
        if self.paused.get(key, 0) > now:
            return False, 0, 0
        Keep = max(int(s["l1_seconds"]), int(s["l2_seconds"]))
        All = self.all.setdefault(key, deque())
        Counted = self.counted.setdefault(key, deque())
        All.append(now)
        for Q in (All, Counted):
            while Q and Q[0] < now - Keep:
                Q.popleft()
        InL2 = sum(1 for T in All if T >= now - int(s["l2_seconds"]))
        if InL2 >= int(s["l2_count"]):
            Back = sum(1 for T in Counted if T >= now - int(s["l2_seconds"]))
            self.paused[key] = now + int(s["pause_minutes"]) * 60
            All.clear()
            Counted.clear()
            return False, 2, Back
        InL1 = sum(1 for T in All if T >= now - int(s["l1_seconds"]))
        if InL1 > int(s["l1_count"]):
            Level = 0
            if now - self.noticed.get(key, -1e9) >= L1_NOTICE_EVERY:
                self.noticed[key] = now
                Level = 1
            return False, Level, 0
        Counted.append(now)
        return True, 0, 0


def Settings(config: dict | None) -> dict:
    return {**DEFAULTS, **(((config or {}).get("Message Quota") or {}).get("AntiSpam") or {})}


def Fill(text: str, values: dict) -> str:
    for K, V in values.items():
        text = text.replace("{" + K + "}", str(V))
    return text
