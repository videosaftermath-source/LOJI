"""
Ticket transcripts as a single .html file sent to the transcript channel.

Discord stores the file, so it costs us no database space. Images are put inside the file (compressed)
up to IMAGE_BUDGET, because Discord's own attachment links expire; anything beyond that, or other files,
is listed by name with its (possibly expired) link.
"""

import base64
import html
from datetime import datetime, timezone

FILE_LIMIT = 9 * 1024 * 1024  # Discord accepts 10 MB from bots in any server
IMAGE_BUDGET = 6 * 1024 * 1024
IMAGE_MAX = 3 * 1024 * 1024  # bigger originals aren't downloaded
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

CSS = """
*{box-sizing:border-box}body{margin:0;background:#313338;color:#dbdee1;font:15px/1.4 "gg sans","Segoe UI",Roboto,Arial,sans-serif}
header{background:#1e1f22;padding:18px 22px;border-bottom:3px solid #960c12}header h1{margin:0 0 6px;font-size:20px;color:#fff}
header .meta{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:#b5bac1}header b{color:#fff;font-weight:600}
main{padding:10px 0 30px}.m{display:flex;gap:14px;padding:6px 22px}.m:hover{background:#2e3035}
.av{width:40px;height:40px;border-radius:50%;flex:none;background:#5865f2}.c{min-width:0;flex:1}
.n{font-weight:600;color:#fff}.bot{background:#5865f2;color:#fff;font-size:10px;padding:1px 4px;border-radius:3px;margin-left:4px;vertical-align:middle}
.t{font-size:12px;color:#949ba4;margin-left:6px}.x{white-space:pre-wrap;word-wrap:break-word}
.cont{padding:1px 22px 1px 76px}.cont:hover{background:#2e3035}
img.at{display:block;max-width:min(420px,100%);max-height:350px;border-radius:6px;margin-top:6px}
.f{display:inline-block;margin-top:6px;padding:8px 12px;background:#2b2d31;border:1px solid #1e1f22;border-radius:6px;color:#00a8fc}
.e{margin-top:6px;max-width:520px;background:#2b2d31;border-left:4px solid #1e1f22;border-radius:4px;padding:8px 12px}
.e .et{font-weight:600;color:#fff}.e .fn{font-weight:600;color:#fff;margin-top:6px;font-size:13px}.e .fv{white-space:pre-wrap;font-size:13px}
footer{color:#949ba4;font-size:12px;text-align:center;padding:16px}
@media (max-width:600px){.m{padding:6px 12px}.cont{padding-left:66px}}
"""


def Esc(text) -> str:
    return html.escape(str(text or ""))


def When(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def EmbedHtml(e: dict) -> str:
    Color = f"#{int(e.get('color') or 0x1e1f22):06x}"
    Parts = [f'<div class="e" style="border-left-color:{Color}">']
    if e.get("author", {}).get("name"):
        Parts.append(f'<div class="fv">{Esc(e["author"]["name"])}</div>')
    if e.get("title"):
        Parts.append(f'<div class="et">{Esc(e["title"])}</div>')
    if e.get("description"):
        Parts.append(f'<div class="fv">{Esc(e["description"])}</div>')
    for F in e.get("fields", []):
        Parts.append(f'<div class="fn">{Esc(F.get("name"))}</div><div class="fv">{Esc(F.get("value"))}</div>')
    if e.get("footer", {}).get("text"):
        Parts.append(f'<div class="t" style="margin:6px 0 0">{Esc(e["footer"]["text"])}</div>')
    Parts.append("</div>")
    return "".join(Parts)


def Attachment(a: dict) -> str:
    if a.get("data"):
        return f'<img class="at" src="data:{a["type"]};base64,{a["data"]}" alt="{Esc(a["name"])}">'
    return f'<a class="f" href="{Esc(a.get("url"))}">📎 {Esc(a["name"])}</a>'


def Build(info: dict, messages: list[dict]) -> str:
    """
    info: title, guild, panel, opened_by, closed_by, claimed_by, reason, opened, closed (timestamps).
    messages (oldest first): author, author_id, avatar, bot, ts, content, embeds (dicts), attachments
      (name, url, and type+data when embedded).
    """
    Meta = [
        ("Servidor", info.get("guild")), ("Panel", info.get("panel")), ("Abierto por", info.get("opened_by")),
        ("Atendido por", info.get("claimed_by") or "—"), ("Cerrado por", info.get("closed_by")),
        ("Abierto", When(info["opened"]) if info.get("opened") else "—"), ("Cerrado", When(info["closed"]) if info.get("closed") else "—"),
        ("Mensajes", str(len(messages))),
    ]
    Out = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{Esc(info.get('title'))}</title><style>{CSS}</style></head><body><header>",
        f"<h1>🎫 #{Esc(info.get('title'))}</h1><div class='meta'>",
        "".join(f"<span>{Esc(K)}: <b>{Esc(V)}</b></span>" for K, V in Meta),
        f"</div><div class='meta' style='margin-top:8px'><span>Solución: <b>{Esc(info.get('reason'))}</b></span></div></header><main>",
    ]
    Last = None
    for M in messages:
        Body = ""
        if M.get("content"):
            Body += f"<div class='x'>{Esc(M['content'])}</div>"
        Body += "".join(EmbedHtml(E) for E in M.get("embeds", []))
        Body += "".join(Attachment(A) for A in M.get("attachments", []))
        # Group consecutive messages from the same person within 7 minutes, like Discord.
        if Last and Last["author_id"] == M["author_id"] and M["ts"] - Last["ts"] < 420:
            Out.append(f"<div class='cont' title='{When(M['ts'])}'>{Body}</div>")
        else:
            Bot = "<span class='bot'>BOT</span>" if M.get("bot") else ""
            Avatar = f"<img class='av' src='{Esc(M.get('avatar'))}' alt='' onerror=\"this.style.visibility='hidden'\">" if M.get("avatar") else "<div class='av'></div>"
            Out.append(
                f"<div class='m'>{Avatar}<div class='c'><span class='n'>{Esc(M['author'])}</span>{Bot}"
                f"<span class='t'>{When(M['ts'])}</span>{Body}</div></div>"
            )
        Last = M
    Out.append(f"</main><footer>Transcripción generada por LOJI · {When(info.get('closed') or 0)}</footer></body></html>")
    return "".join(Out)


async def Collect(channel, compress=None) -> list[dict]:
    """Reads the channel (oldest first). `compress(bytes) -> bytes` shrinks images before embedding."""
    Messages, Budget = [], IMAGE_BUDGET
    async for Msg in channel.history(limit=None, oldest_first=True):
        Files = []
        for A in Msg.attachments:
            Entry = {"name": A.filename, "url": A.url}
            if A.filename.lower().endswith(IMAGE_TYPES) and A.size <= IMAGE_MAX and Budget > 0:
                try:
                    Data = await A.read()
                    Type = "image/gif" if A.filename.lower().endswith(".gif") else "image/jpeg"
                    if compress and Type == "image/jpeg":
                        Data = await compress(Data)
                    if len(Data) <= Budget:
                        Budget -= len(Data)
                        Entry.update(type=Type, data=base64.b64encode(Data).decode())
                except Exception:
                    pass  # keep the link
            Files.append(Entry)
        Messages.append({
            "author": Msg.author.display_name, "author_id": Msg.author.id, "bot": Msg.author.bot,
            "avatar": Msg.author.display_avatar.replace(size=64).url, "ts": Msg.created_at.timestamp(),
            "content": Msg.clean_content, "embeds": [E.to_dict() for E in Msg.embeds], "attachments": Files,
        })
    return Messages


def Fit(info: dict, messages: list[dict]) -> bytes:
    """The html, dropping embedded images (newest first) if it would be too big for Discord."""
    Data = Build(info, messages).encode()
    Images = [A for M in reversed(messages) for A in M["attachments"] if A.get("data")]
    while len(Data) > FILE_LIMIT and Images:
        for A in Images[:5]:
            A.pop("data", None)
        Images = Images[5:]
        Data = Build(info, messages).encode()
    return Data
