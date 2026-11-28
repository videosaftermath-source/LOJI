"""
Quick reports: in one chosen channel, when a message gets enough 🚩 reactions from different people, LOJI asks
the /guia model (same Groq key) whether it breaks the server rules (uploaded as a .txt, like the guide) and posts a
report card to staff, sancionable or not, with "Falsa alarma" / "Se actuará". Only reported messages are sent.

- Daily cap on AI reviews (cost); past it, reports still arrive, without the AI's opinion.
- Abuse: someone reporting a lot in 24 h, or the same person reporting the same member again and again, raises an alert.
"""

import json
import re
from datetime import datetime, timedelta, timezone

REPORTS = "quick_reports"
DAY = timedelta(hours=24)
MAX_RULES_CHARS = 60_000
CONTEXT_MESSAGES = 6

DEFAULTS = {
    "enabled": False,
    "channel": None,  # old single watched chat (kept for configs made before "channels")
    "channels": [],  # the chats that are watched
    "emoji": "🚩",
    "threshold": 2,  # reactions from different people
    "staff_channel": None,  # where the report cards go
    "ping_role": None,
    "daily_limit": 60,  # AI reviews per 24 h
    "abuse_reports": 5,  # reports by one person in 24 h
    "abuse_pair": 3,  # reports by one person against the same member in 24 h
}

SYSTEM = """Eres LOJI, la moderadora del servidor {server}. Un mensaje del chat ha sido reportado por usuarios.
Decide si rompe alguna de las normas del servidor (están abajo). Sé justa: los usuarios a veces reportan bromas,
desacuerdos o cosas que no les gustan sin que haya infracción. Ten en cuenta el contexto de la conversación,
el sarcasmo y las bromas entre amigos. No inventes normas que no estén.

Responde SOLO con un JSON así:
{{"sancionable": true o false,
  "norma": "la norma que se rompe, citada o resumida (vacío si no se rompe ninguna)",
  "motivo": "por qué, en 1-2 frases, en español",
  "sugerencia": "qué debería hacer el staff (aviso, borrar el mensaje, aislamiento...), vacío si no es sancionable",
  "confianza": "alta" | "media" | "baja"}}

<normas>
{rules}
</normas>"""


def Now() -> datetime:
    return datetime.now(timezone.utc)


def Aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


MAX_CHANNELS = 25


def Settings(doc: dict | None) -> dict:
    S = {**DEFAULTS, **((doc or {}).get("autoreport") or {})}
    Channels = list(S.get("channels") or [])
    if S.get("channel") and S["channel"] not in Channels:  # the old single channel still counts
        Channels.insert(0, S["channel"])
    S["channels"] = Channels
    return S


def UserPrompt(reported: dict, context: list[dict]) -> str:
    """reported/context: {"author": name, "content": text}. The reported message goes last, marked."""
    Lines = ["Conversación (los más antiguos primero):"]
    for M in context:
        Lines.append(f"- {M['author']}: {M['content'][:500]}")
    Lines.append(f">>> MENSAJE REPORTADO · {reported['author']}: {reported['content'][:1500]}")
    return "\n".join(Lines)


def ParseVerdict(text: str) -> dict:
    """The model's JSON, tolerant to extra text around it. Raises ValueError."""
    Match = re.search(r"\{.*\}", text, re.S)
    if not Match:
        raise ValueError("sin JSON")
    Data = json.loads(Match.group(0))
    Confidence = str(Data.get("confianza", "media")).lower()
    return {
        "sancionable": bool(Data.get("sancionable")),
        "norma": str(Data.get("norma") or "")[:500],
        "motivo": str(Data.get("motivo") or "")[:800],
        "sugerencia": str(Data.get("sugerencia") or "")[:500],
        "confianza": Confidence if Confidence in ("alta", "media", "baja") else "media",
    }


def Abuse(reports: list[dict], reporter: int, target: int, now: datetime, settings: dict) -> list[str]:
    """Why this reporter looks suspicious (empty = fine). reports: the last 24 h of reports in the guild."""
    Recent = [R for R in reports if Aware(R["at"]) >= now - DAY and reporter in R.get("reporters", [])]
    Problems = []
    if len(Recent) >= int(settings["abuse_reports"]):
        Problems.append(f"ha participado en **{len(Recent)}** reportes en 24 h")
    Against = [R for R in Recent if R.get("author_id") == target]
    if len(Against) >= int(settings["abuse_pair"]):
        Problems.append(f"ha reportado a <@{target}> **{len(Against)}** veces en 24 h")
    return Problems
