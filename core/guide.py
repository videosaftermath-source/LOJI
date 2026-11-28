"""
Sanctions guide Q&A (/guia): the whole guide goes to the model with each question, so a new upload
applies at once. Model: DeepSeek (deepseek-chat) or Groq (openai/gpt-oss-120b), chosen by the key.

- The guide is uploaded as .docx, .txt or .md from /config → Mando Central → Guía de sanciones.
- Who can ask: one configurable role; 2 questions per person per rolling 24 h.
- No memory: each question is independent. Only the time of each question is stored (for the limit).
- The AI key: set in /config (stored in the database) or DEEPSEEK_API_KEY / GROQ_API_KEY in .env.
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

SYSTEM = """Eres el asistente de la guía de sanciones del staff de {server}. Piensas como un administrador con experiencia:
conoces la guía al dedillo, pero también tienes criterio propio para los casos graves.
Respondes a moderadores que tienen una duda concreta sobre cómo sancionar.

Cómo responder:
1. **Según la guía:** lo que dice la guía (qué sanción y cuánto tiempo), citando la sección o el título
   (por ejemplo: «Según 3.2 Spam reincidente…»). No inventes sanciones, plazos ni excepciones que no estén.
   Si la guía no cubre la duda, dilo: "Esto no está en la guía."
2. **Criterio:** piensa de forma crítica sobre el caso concreto: intención, reincidencia, daño a otras personas,
   si es un usuario nuevo o una cuenta sospechosa. Si la gravedad lo justifica, añade una sección
   "⚠️ Recomendación" donde puedes recomendar saltarse pasos de la escala o un ban directo. Casos típicos:
   - trolls y cuentas creadas solo para molestar, evadir sanciones o hacer raid;
   - bots, spam automatizado, enlaces de estafa o phishing;
   - acoso por MD, amenazas, doxxing o insistir con alguien que ya pidió que pare;
   - comentarios sexuales o sugestivos, sobre todo hacia menores (esto es lo más grave: ban y avisar a un superior ya);
   - discriminación o discurso de odio deliberado.
   La recomendación es tuya, no de la guía: márcala siempre como recomendación y di que saltarse pasos
   **necesita la autorización de un superior** (salvo que la guía ya permita actuar directamente).
   En casos leves o dudosos, no recomiendes endurecer: sigue la guía.
3. Si falta información para decidir (pruebas, reincidencia, edad...), di qué hay que comprobar.

Estilo: en español, directo, con formato de Discord (negritas, listas cortas). Primero la respuesta, luego el porqué.
Máximo unas 250 palabras.

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
        return Doc.get("groq_key") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("GROQ_API_KEY")

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
# Two OpenAI-compatible providers; which one is decided by the key itself:
#   Groq     (keys "gsk_…") -> openai/gpt-oss-120b
#   DeepSeek (keys "sk-…")  -> deepseek-chat (cheaper; repeated prompts like the guide are cached and cost less)

PROVIDERS = {
    "groq": {"name": "Groq", "url": GROQ_URL, "model": MODEL, "reasoning": True},
    "deepseek": {"name": "DeepSeek", "url": "https://api.deepseek.com/chat/completions", "model": "deepseek-chat", "reasoning": False},
}


def Provider(key: str | None) -> dict:
    return PROVIDERS["deepseek" if (key or "").startswith("sk-") else "groq"]


def ValidKey(key: str) -> bool:
    return key.startswith(("gsk_", "sk-"))


def Body(key: str, messages: list[dict], temperature: float, max_tokens: int, effort: str, json_mode: bool, model: str | None = None) -> dict:
    """model: the admin's choice in /config (empty = the provider's default)."""
    P = Provider(key)
    Data = {"model": (model or "").strip() or P["model"], "messages": messages, "temperature": temperature}
    if P["reasoning"]:  # gpt-oss thinks first: its limit counts the thinking too
        Data.update(max_completion_tokens=max_tokens, reasoning_effort=effort)
    else:
        Data["max_tokens"] = max_tokens
    if json_mode:
        Data["response_format"] = {"type": "json_object"}
    return Data


async def Post(key: str, body: dict, session: aiohttp.ClientSession | None, retry_note: str = "") -> dict:
    """Sends one request; every failure becomes a GuideError with a message that can be shown on Discord."""
    P = Provider(key)
    Headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    Own = session is None
    Session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90))
    try:
        async with Session.post(P["url"], json=body, headers=Headers) as R:
            Data = await R.json(content_type=None)
            if R.status == 401:
                raise GuideError(f"La key de {P['name']} no es válida. Revísala en `/config` → Mando Central → Guía de sanciones.")
            if R.status == 402:
                raise GuideError(f"La cuenta de {P['name']} no tiene saldo. Recárgala.{retry_note}")
            if R.status == 429:
                Wait = R.headers.get("retry-after")
                raise GuideError(
                    f"{P['name']} está al límite de uso ahora mismo. Inténtalo "
                    + (f"en unos {int(float(Wait)) + 1} segundos." if Wait else "en un minuto.") + retry_note
                )
            if R.status >= 400:
                Message = (Data or {}).get("error", {}).get("message", "") if isinstance(Data, dict) else ""
                if "model" in Message.lower() and ("exist" in Message.lower() or "not found" in Message.lower() or "invalid" in Message.lower()):
                    raise GuideError(f"{P['name']} no reconoce el modelo «{body.get('model')}». Revisa el nombre en `/config` → Mando Central → Guía de sanciones → Key de la IA.")
                raise GuideError(f"{P['name']} respondió con un error ({R.status}). {Message[:200]}".strip())
    except aiohttp.ClientError:
        raise GuideError(f"No pude conectar con {P['name']}. Inténtalo en un momento.{retry_note}")
    except TimeoutError:
        raise GuideError(f"{P['name']} tardó demasiado en responder.{retry_note}")
    finally:
        if Own:
            await Session.close()
    return Data


def Text(data: dict, key: str, retry_note: str = "") -> str:
    try:
        Answer = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        Answer = ""
    if not Answer:
        raise GuideError(f"{Provider(key)['name']} devolvió una respuesta vacía. Inténtalo de nuevo.{retry_note}")
    return Answer


async def Ask(key: str, guide: str, question: str, server: str, session: aiohttp.ClientSession | None = None, model: str | None = None) -> str:
    """One question, no memory. Raises GuideError with a message for the user."""
    Messages = [
        {"role": "system", "content": SYSTEM.format(server=server, guide=guide)},
        {"role": "user", "content": question},
    ]
    Note = " No se te ha descontado la pregunta."
    Data = await Post(key, Body(key, Messages, 0.2, 2000, "medium", False, model), session, Note)
    return Text(Data, key, Note)


async def Complete(key: str, system: str, user: str, max_tokens: int = 900, json_mode: bool = False,
                   session: aiohttp.ClientSession | None = None, temperature: float = 0.1, model: str | None = None) -> tuple[str, int]:
    """One call to the same model (quick reports, LOJI chat). Returns (text, tokens used).
    Raises GuideError with a message that can be shown to staff."""
    Messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    Data = await Post(key, Body(key, Messages, temperature, max_tokens, "low", json_mode, model), session)
    return Text(Data, key), int((Data.get("usage") or {}).get("total_tokens") or 0)
