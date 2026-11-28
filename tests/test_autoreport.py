import asyncio
from datetime import timedelta
from types import SimpleNamespace as N

import pytest

from core.autoreport import DEFAULTS, Abuse, Now, ParseVerdict, UserPrompt

S = dict(DEFAULTS)


def test_verdict_is_read_even_with_extra_text():
    V = ParseVerdict('Claro: {"sancionable": true, "norma": "2. Respeto", "motivo": "insulta", "sugerencia": "aviso", "confianza": "ALTA"} listo')
    assert V["sancionable"] is True and V["confianza"] == "alta" and V["norma"] == "2. Respeto"
    assert ParseVerdict('{"sancionable": false, "confianza": "rara"}')["confianza"] == "media"
    with pytest.raises(ValueError):
        ParseVerdict("no sé")


def test_prompt_marks_the_reported_message_last():
    P = UserPrompt({"author": "Ana", "content": "eres tonto"}, [{"author": "Luis", "content": "hola"}])
    assert P.splitlines()[-1] == ">>> MENSAJE REPORTADO · Ana: eres tonto" and "Luis: hola" in P


def test_abuse_by_volume_and_by_target():
    Now_ = Now()
    Reports = [{"at": Now_ - timedelta(hours=1), "reporters": [7, 8], "author_id": 100 + I % 2} for I in range(5)]
    Problems = Abuse(Reports, 7, 100, Now_, S)
    assert any("5" in P for P in Problems) and any("<@100>" in P for P in Problems)
    assert Abuse(Reports, 9, 100, Now_, S) == []  # never reported anything
    Old = [{**R, "at": Now_ - timedelta(hours=30)} for R in Reports]
    assert Abuse(Old, 7, 100, Now_, S) == []  # older than 24 h doesn't count


def test_whole_flow(monkeypatch):
    import cogs.Modules.Guide.autoreport as ar
    import core.guide
    from core.guide import Guide
    from tests.economy.fakes import DB

    D = DB()
    G = Guide(D)
    monkeypatch.setattr(ar, "Db", lambda: D)
    monkeypatch.setattr(ar, "Store", lambda: G)
    Calls = []

    async def Complete(key, system, user, **kw):
        Calls.append((system, user))
        return '{"sancionable": true, "norma": "2. Respeto", "motivo": "Insulto directo.", "sugerencia": "Aviso", "confianza": "alta"}', 900
    monkeypatch.setattr(core.guide, "Complete", Complete)

    async def Setup():
        await G.guides.update_one({"_id": 1}, {"$set": {"rules_text": "1. No spam\n2. Respeto", "groq_key": "gsk_test",
                                                       "autoreport": {"enabled": True, "channel": 10, "staff_channel": 20}}}, upsert=True)
    asyncio.run(Setup())
    Sent = []

    class Staff:
        id = 20

        async def send(self, **kw):
            Sent.append(kw)
            return N(id=999)

    async def History(limit, before):
        for M in [N(author=N(display_name="Luis"), content="hola")]:
            yield M

    Guild = N(id=1, name="Sótano", me=N(display_avatar=N(url="https://cdn/l.png")), get_channel=lambda i: Staff() if i == 20 else None,
              get_role=lambda i: None)
    Channel = N(id=10, history=History)
    Message = N(id=55, jump_url="https://discord.com/channels/1/10/55", content="eres tonto", attachments=[],
                author=N(id=5, display_name="Ana", display_avatar=N(url="https://cdn/a.png")))
    Doc = asyncio.run(G.Get(1))
    Cog = ar.AutoReport.__new__(ar.AutoReport)
    Cog.alerted = {}
    asyncio.run(Cog.Report(Guild, Channel, Message, [7, 8], Doc, ar.Settings(Doc)))
    assert "1. No spam" in Calls[0][0] and "MENSAJE REPORTADO · Ana: eres tonto" in Calls[0][1]
    Card = Sent[0]["embed"]
    assert "Parece sancionable" in Card.fields[0].value and Card.fields[1].value == "2. Respeto"
    assert [C.custom_id for C in Sent[0]["view"].children] == [f"qr:{asyncio.run(D[ar.REPORTS].find_one({}))['_id']}:fa",
                                                              f"qr:{asyncio.run(D[ar.REPORTS].find_one({}))['_id']}:ok"]


def test_buttons_resolve_once(monkeypatch):
    import discord
    import cogs.Modules.Guide.autoreport as ar
    import core.mail.config as mc
    import core.ticket_access as ta
    from tests.economy.fakes import DB

    D = DB()
    monkeypatch.setattr(ar, "Db", lambda: D)
    monkeypatch.setattr(ta, "IsTicketStaff", lambda member, roles, config: True)

    class FakeMail:
        async def Get(self, g):
            return {}
    monkeypatch.setattr(mc, "Mail", FakeMail)
    asyncio.run(D[ar.REPORTS].insert_one({"_id": "ABCDEFGH", "guild_id": 1, "status": None}))
    Replies = []

    def Interaction():
        async def edit_message(**kw):
            Replies.append(("edit", kw))

        async def send_message(text, **kw):
            Replies.append(("msg", text))
        return N(guild=N(id=1), user=N(id=3, mention="<@3>"), message=N(embeds=[discord.Embed(title="🚩 Reporte rápido")]),
                 response=N(edit_message=edit_message, send_message=send_message))

    asyncio.run(ar.ReportButton("ABCDEFGH", "ok").callback(Interaction()))
    asyncio.run(ar.ReportButton("ABCDEFGH", "fa").callback(Interaction()))
    assert Replies[0][0] == "edit" and "Se actuará" in Replies[0][1]["embed"].fields[-1].value and Replies[0][1]["view"] is None
    assert Replies[1] == ("msg", "Este reporte ya lo resolvió otra persona.")
    assert asyncio.run(D[ar.REPORTS].find_one({"_id": "ABCDEFGH"}))["status"] == "act"
