import asyncio
import io
import zipfile
from datetime import timedelta

import pytest

from core.guide import PER_DAY, WINDOW, Ask, ExtractText, Guide, GuideError, Now
from tests.economy.fakes import DB

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def run(c):
    return asyncio.run(c)


def docx(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def p(text, style=None, numbered=False):
    props = ""
    if style or numbered:
        props = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:numPr/>" if numbered else "") + "</w:pPr>"
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_word_headings_lists_and_tables():
    body = (
        p("3 Spam", style="Heading1") + p("3.2 Reincidente", style="Heading2") + p("Mute de 1 hora", numbered=True)
        + "<w:tbl><w:tr><w:tc>" + p("Falta") + "</w:tc><w:tc>" + p("Sanción") + "</w:tc></w:tr>"
        + "<w:tr><w:tc>" + p("Spam x3") + "</w:tc><w:tc>" + p("Ban 1 día") + "</w:tc></w:tr></w:tbl>"
        + p("Texto normal que hace que la guía tenga más de cincuenta caracteres en total.")
    )
    text = ExtractText("Guía.docx", docx(body))
    assert "# 3 Spam" in text and "## 3.2 Reincidente" in text and "- Mute de 1 hora" in text
    assert "Falta | Sanción" in text and "Spam x3 | Ban 1 día" in text


def test_bad_files():
    with pytest.raises(GuideError):
        ExtractText("guia.pdf", b"x")
    with pytest.raises(GuideError):
        ExtractText("guia.doc", b"x")
    with pytest.raises(GuideError):
        ExtractText("guia.docx", b"not a zip")
    with pytest.raises(GuideError):
        ExtractText("guia.txt", b"corta")
    assert ExtractText("g.txt", ("Sección 1: mute por spam, una hora. " * 3).encode("cp1252")).startswith("Sección 1")


def test_two_per_rolling_24h():
    g = Guide(DB())
    t0 = Now()
    assert run(g.Remaining(1, 5, t0)) == (PER_DAY, None)
    run(g.Count(1, 5, t0))
    run(g.Count(1, 5, t0 + timedelta(hours=3)))
    left, free = run(g.Remaining(1, 5, t0 + timedelta(hours=4)))
    assert left == 0 and abs((free - (t0 + WINDOW)).total_seconds()) < 1
    assert run(g.Remaining(1, 5, t0 + WINDOW + timedelta(minutes=1)))[0] == 1
    assert run(g.Remaining(1, 6, t0))[0] == PER_DAY  # per person


class FakeResponse:
    def __init__(self, status, data, headers=None):
        self.status, self.data, self.headers = status, data, headers or {}

    async def json(self, content_type=None):
        return self.data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, response):
        self.response, self.sent = response, None

    def post(self, url, json=None, headers=None):
        self.sent = (url, json, headers)
        return self.response


def test_ask_sends_the_guide_and_handles_errors():
    ok = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": "  **Mute 1 h** (3.2)  "}}]}))
    assert run(Ask("gsk_x", "GUIA COMPLETA", "¿spam?", "LOJI", ok)) == "**Mute 1 h** (3.2)"
    url, body, headers = ok.sent
    assert body["model"] == "openai/gpt-oss-120b" and "GUIA COMPLETA" in body["messages"][0]["content"]
    assert body["messages"][1] == {"role": "user", "content": "¿spam?"} and headers["Authorization"] == "Bearer gsk_x"
    for status, needle in ((401, "no es válida"), (429, "No se te ha descontado"), (500, r"error \(500\)")):
        with pytest.raises(GuideError, match=needle):
            run(Ask("k", "g", "q", "L", FakeSession(FakeResponse(status, {"error": {"message": "x"}}, {"retry-after": "7"}))))
    with pytest.raises(GuideError, match="vacía"):
        run(Ask("k", "g", "q", "L", FakeSession(FakeResponse(200, {"choices": []}))))


def test_the_key_chooses_the_provider():
    from core.guide import Complete, Provider, ValidKey

    assert Provider("sk-abc")["name"] == "DeepSeek" and Provider("gsk_abc")["name"] == "Groq"
    assert ValidKey("sk-1") and ValidKey("gsk_1") and not ValidKey("hola")
    Deep = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": '{"ok": 1}'}}], "usage": {"total_tokens": 42}}))
    assert run(Complete("sk-abc", "sys json", "user", max_tokens=300, json_mode=True, session=Deep, temperature=0.9)) == ('{"ok": 1}', 42)
    url, body, headers = Deep.sent
    assert url == "https://api.deepseek.com/chat/completions" and body["model"] == "deepseek-chat"
    assert body["max_tokens"] == 300 and "reasoning_effort" not in body and "max_completion_tokens" not in body
    assert body["response_format"] == {"type": "json_object"} and body["temperature"] == 0.9
    Groq = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": "x"}}]}))
    run(Ask("gsk_x", "g", "q", "L", Groq))
    assert Groq.sent[0].startswith("https://api.groq.com") and Groq.sent[1]["reasoning_effort"] == "medium"
    with pytest.raises(GuideError, match="DeepSeek no tiene saldo"):
        run(Ask("sk-x", "g", "q", "L", FakeSession(FakeResponse(402, {"error": {"message": "Insufficient Balance"}}))))


def test_model_can_be_chosen():
    from core.guide import Body

    assert Body("sk-x", [], 0.2, 100, "low", False, "deepseek-v4-flash")["model"] == "deepseek-v4-flash"
    assert Body("sk-x", [], 0.2, 100, "low", False, " ")["model"] == "deepseek-chat"
    with pytest.raises(GuideError, match="no reconoce el modelo"):
        run(Ask("sk-x", "g", "q", "L", FakeSession(FakeResponse(400, {"error": {"message": "Model Not Exist"}})), model="deepseek-V4-flash"))
