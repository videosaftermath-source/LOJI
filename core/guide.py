"""
Sanctions guide Q&A (/guia): the whole guide goes to the model with each question, so a new upload
applies at once. Model: openai/gpt-oss-120b on Groq (OpenAI-compatible API).

- The guide is uploaded as .docx, .txt or .md from /config → Mando Central → Guía de sanciones.
- Who can ask: one configurable role; 2 questions per person per rolling 24 h.
- No memory: each question is independent. Only the time of each question is stored (for the limit).
- The Groq key: set in /config (stored in the database) or GROQ_API_KEY in .env.
"""

import io
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import aiohttp

GUIDES = "sanction_guide"
QUESTIONS = "guide_questions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"
PER_DAY = 2
WINDOW = timedelta(hours=24)
MAX_GUIDE_CHARS = 200_000  # ~50k tokens: far more than a 16-page guide
QUESTION_MAX = 500
ALLOWED = (".docx", ".txt", ".md")

SYSTEM = """Eres el asistente de la guía de sanciones del staff de {server}.
Respondes a moderadores que tienen una duda concreta sobre cómo sancionar.

Reglas:
- Responde SOLO con lo que dice la guía de abajo. No inventes sanciones, plazos ni excepciones.
- Si la guía no cubre la duda, dilo claramente: "Esto no está en la guía; consúltalo con un superior." Puedes añadir qué parte de la guía se acerca más, si la hay.
- Cita la sección o el título de donde sale la respuesta (por ejemplo: «Según 3.2 Spam reincidente…»).
- Sé breve y directo: primero la respuesta (qué sanción, cuánto tiempo), luego el porqué en una o dos frases.
- Responde en español. Usa formato de Discord (negritas, listas cortas). Máximo unas 200 palabras.

<guia>
{guide}
</guia>"""


class GuideError(Exception):
    """Message is safe to show to users."""


def Now() -> datetime:
    return datetime.now(timezone.utc)


def Aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


# ---------------- reading the file ----------------


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def DocxText(data: bytes) -> str:
    """Paragraphs and tables of a Word file, as plain text (tables as 'a | b | c' rows)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as Z:
            Root = ElementTree.fromstring(Z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise GuideError("Ese archivo no parece un Word válido (.docx).")
    Body = Root.find(f"{W}body")
    Lines = []

    def Para(p) -> str:
        Parts = []
        for Node in p.iter():
            if Node.tag == f"{W}t" and Node.text:
                Parts.append(Node.text)
            elif Node.tag == f"{W}tab":
                Parts.append("\t")
            elif Node.tag in (f"{W}br", f"{W}cr"):
                Parts.append("\n")
        Text = "".join(Parts).strip()
        Style = p.find(f"{W}pPr/{W}pStyle")
        Name = (Style.get(f"{W}val") or "") if Style is not None else ""
        Level = re.search(r"(?:Heading|Ttulo|Titulo|Título)(\d)", Name, re.I)
        if Text and Level:  # keep headings recognisable so answers can cite them
            Text = "#" * min(int(Level.group(1)), 4) + " " + Text
        elif Text and p.find(f"{W}pPr/{W}numPr") is not None:
            Text = "- " + Text
        return Text

    for Child in list(Body) if Body is not None else []:
        if Child.tag == f"{W}p":
            Lines.append(Para(Child))
        elif Child.tag == f"{W}tbl":
            for Row in Child.iter(f"{W}tr"):
                Cells = [" ".join(filter(None, (Para(p) for p in Cell.iter(f"{W}p")))) for Cell in Row.iter(f"{W}tc")]
                if any(Cells):
                    Lines.append(" | ".join(Cells))
            Lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(Lines)).strip()


def ExtractText(filename: str, data: bytes) -> str:
    Name = (filename or "").lower()
    if Name.endswith(".docx"):
        Text = DocxText(data)
    elif Name.endswith((".txt", ".md")):
        for Encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                Text = data.decode(Encoding)
                break
            except UnicodeDecodeError:
                continue
    elif Name.endswith(".doc"):
        raise GuideError("Ese es el formato antiguo de Word (.doc). Ábrelo en Word y guárdalo como .docx.")
    else:
        raise GuideError("Sube la guía como Word (.docx), .txt o .md.")
    Text = Text.replace("\r\n", "\n").strip()
    if len(Text) < 50:
        raise GuideError("El archivo está vacío o casi vacío.")
    if len(Text) > MAX_GUIDE_CHARS:
        raise GuideError(f"La guía es demasiado larga ({len(Text):,} caracteres; máximo {MAX_GUIDE_CHARS:,}).".replace(",", "."))
    return Text


def ApproxTokens(text: str) -> int:
    return len(text) // 4


# ---------------- storage ----------------


class Guide:
    def __init__(self, db):
        self.guides = db[GUIDES]
        self.questions = db[QUESTIONS]

    async def Get(self, guild_id: int) -> dict | None:
        return await self.guides.find_one({"_id": guild_id})

    async def Save(self, guild_id: int, text: str, filename: str, by: int):
        await self.guides.update_one(
            {"_id": guild_id},
            {"$set": {"text": text, "filename": filename, "updated_at": Now(), "updated_by": by}},
            upsert=True,
        )

    async def SetKey(self, guild_id: int, key: str | None):
        await self.guides.update_one({"_id": guild_id}, {"$set": {"groq_key": key or None}}, upsert=True)

    async def SetRole(self, guild_id: int, role_id: int | None):
        await self.guides.update_one({"_id": guild_id}, {"$set": {"role": role_id}}, upsert=True)

    async def Key(self, guild_id: int) -> str | None:
        Doc = await self.Get(guild_id) or {}
        return Doc.get("groq_key") or os.getenv("GROQ_API_KEY")

    async def Used(self, guild_id: int, user_id: int, now: datetime | None = None) -> list[datetime]:
        Since = (now or Now()) - WINDOW
        Docs = await self.questions.find({"guild_id": guild_id, "user": user_id, "at": {"$gt": Since}}).to_list(length=None)
        return sorted(Aware(D["at"]) for D in Docs)

    async def Remaining(self, guild_id: int, user_id: int, now: datetime | None = None) -> tuple[int, datetime | None]:
        """(questions left, when the next one frees up if none are left)."""
        Used = await self.Used(guild_id, user_id, now)
        Left = max(0, PER_DAY - len(Used))
        return Left, (Used[0] + WINDOW if not Left and Used else None)

    async def Count(self, guild_id: int, user_id: int, now: datetime | None = None):
        await self.questions.insert_one({"guild_id": guild_id, "user": user_id, "at": now or Now()})


def MaskKey(key: str | None) -> str:
    if not key:
        return "*sin configurar*"
    return f"`{key[:4]}…{key[-4:]}`" if len(key) > 10 else "`configurada`"


# ---------------- asking ----------------


async def Ask(key: str, guide: str, question: str, server: str, session: aiohttp.ClientSession | None = None) -> str:
    """One question, no memory. Raises GuideError with a message for the user."""
    Body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM.format(server=server, guide=guide)},
            {"role": "user", "content": question},
        ],
        "temperature": 0.2,
        "max_completion_tokens": 2000,
        "reasoning_effort": "medium",
    }
    Headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    Own = session is None
    Session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
    try:
        async with Session.post(GROQ_URL, json=Body, headers=Headers) as R:
            Data = await R.json(content_type=None)
            if R.status == 401:
                raise GuideError("La key de Groq no es válida. Revísala en `/config` → Mando Central → Guía de sanciones.")
            if R.status == 429:
                Wait = R.headers.get("retry-after")
                raise GuideError(
                    "Groq está al límite de uso por minuto (varias preguntas a la vez). Inténtalo "
                    + (f"en unos {int(float(Wait)) + 1} segundos." if Wait else "en un minuto.")
                    + " No se te ha descontado la pregunta."
                )
            if R.status >= 400:
                Message = (Data or {}).get("error", {}).get("message", "") if isinstance(Data, dict) else ""
                raise GuideError(f"Groq respondió con un error ({R.status}). {Message[:200]}".strip())
    except aiohttp.ClientError:
        raise GuideError("No pude conectar con Groq. Inténtalo en un momento; no se te ha descontado la pregunta.")
    finally:
        if Own:
            await Session.close()
    try:
        Answer = Data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise GuideError("Groq devolvió una respuesta vacía. Inténtalo de nuevo; no se te ha descontado la pregunta.")
    Answer = Answer.strip()
    if not Answer:
        raise GuideError("Groq devolvió una respuesta vacía. Inténtalo de nuevo; no se te ha descontado la pregunta.")
    return Answer
