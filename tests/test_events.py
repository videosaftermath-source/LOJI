import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

import pytest

from core.events import Awards, CanJoin, Due, ParsePrizes, ResolveRoles

NOW = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)


def test_prizes_mix_coins_roles_and_manual():
    P = ParsePrizes("1: 5.000 monedas, <@&123456789012345678>, Nitro Basic\n2º 2000 monedas\n\n3) Una mención especial")
    assert [(X["place"], X["coins"], X["roles"], X["manual"]) for X in P] == [
        (1, 5000, [123456789012345678], ["Nitro Basic"]), (2, 2000, [], []), (3, 0, [], ["Una mención especial"]),
    ]
    with pytest.raises(ValueError, match="repetido"):
        ParsePrizes("1: a\n1: b")
    with pytest.raises(ValueError, match="puesto"):
        ParsePrizes("premio sin puesto")
    assert ParsePrizes("") == []


def test_role_names_typed_in_the_form():
    Roles = [(1, "Campeón"), (2, "Campeón del mes"), (3, "@everyone")]
    assert ResolveRoles("1: @Campeón del mes y @campeón", Roles) == "1: <@&2> y <@&1>"


def test_signup_and_slots():
    E = {"status": "open", "slots": 2, "participants": [1, 2]}
    assert CanJoin(E, 3) == (False, "No quedan plazas. 😔")
    assert CanJoin(E, 1)[0]  # already in: can leave
    assert CanJoin({**E, "slots": None}, 3)[0]
    assert not CanJoin({**E, "status": "finished"}, 3)[0]


def test_reminder_then_start():
    E = {"status": "open", "start": NOW}
    assert Due(E, NOW - timedelta(minutes=90), 60) is None
    assert Due(E, NOW - timedelta(minutes=30), 60) == "remind"
    assert Due({**E, "reminded": True}, NOW - timedelta(minutes=30), 60) is None
    assert Due({**E, "reminded": True}, NOW + timedelta(minutes=1), 60) == "start"
    assert Due({**E, "started": True}, NOW + timedelta(minutes=5), 60) is None


def test_winners_get_their_place():
    Prizes = ParsePrizes("1: 500 monedas\n3: Nitro")
    assert [(U, P["place"]) for U, P in Awards(Prizes, [10, 20, 30, 40])] == [(10, 1), (30, 3)]


def test_announcement_renders_and_fits():
    from cogs.Modules.Growth.events import DefaultView, JsonComponents
    from core.events import SETTINGS

    Guild = N(name="Sótano")
    Event = {"_id": "ABCDEFGH", "title": "Torneo", "description": "Gana", "start": NOW, "prizes": ParsePrizes("1: 500 monedas"),
             "signup": True, "slots": 10, "participants": [1, 2], "organizer": 5, "status": "open", "banner": "evento.png"}
    Text = str(DefaultView(Guild, Event, SETTINGS).to_components())
    assert "## 🎉 Torneo" in Text and "Inscritos · 2/10" in Text and "attachment://evento.png" in Text and "ev:ABCDEFGH:join" in Text
    Finished = str(DefaultView(Guild, {**Event, "status": "finished"}, SETTINGS).to_components())
    assert "Evento finalizado" in Finished and "'disabled': True" in Finished
    Json = '{"components": [{"type": 17, "components": [{"type": 10, "content": "# {titulo} · {inscritos}"}, {"type": 10, "content": "{botones}"}]}]}'
    Out = JsonComponents(Guild, {**Event, "json": Json})
    assert Out[0]["components"][0]["content"] == "# Torneo · 2/10" and Out[0]["components"][1]["type"] == 1


def test_signup_button_respects_the_last_seat(monkeypatch):
    import cogs.Modules.Growth.events as ev
    from tests.economy.fakes import DB

    D = DB()
    monkeypatch.setattr(ev, "Db", lambda: D)
    asyncio.run(D[ev.EVENTS].insert_one({"_id": "ABCDEFGH", "title": "T", "status": "open", "slots": 1, "participants": []}))
    Said = []

    async def Refresh(*a):
        pass
    monkeypatch.setattr(ev, "Refresh", Refresh)

    def Click(uid):
        async def send_message(text, **kw):
            Said.append(text)
        return N(user=N(id=uid), guild=N(), client=None, response=N(send_message=send_message))

    asyncio.run(ev.EventButton("ABCDEFGH", "join").callback(Click(1)))
    asyncio.run(ev.EventButton("ABCDEFGH", "join").callback(Click(2)))
    assert Said[0].startswith("✅") and "plazas" in Said[1]
    asyncio.run(ev.EventButton("ABCDEFGH", "join").callback(Click(1)))  # clicking again: leaves
    assert asyncio.run(D[ev.EVENTS].find_one({}))["participants"] == []
