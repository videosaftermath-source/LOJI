import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

from core.lojichat import SETTINGS, Activity, BuildPrompt, Decide, ParseReply, Tokens

S = dict(SETTINGS)
T0 = datetime(2026, 12, 1, 4, 0, tzinfo=timezone.utc)


def test_activity_window():
    A = Activity()
    for I in range(6):
        A.Add(1, 100 + I % 2, T0 + timedelta(minutes=I))
    assert A.Stats(1, T0 + timedelta(minutes=6), 5) == (5, 2)
    assert A.Stats(1, T0 + timedelta(minutes=30), 5) == (0, 0)


def test_wakes_after_a_quiet_while_then_leaves():
    State = {}
    assert Decide(State, 30, 8, T0, S) is None  # busy
    assert Decide(State, 3, 2, T0, S) is None  # quiet, but only just
    assert Decide(State, 3, 2, T0 + timedelta(minutes=2), S) == "wake"
    assert Decide(State, 3, 2, T0 + timedelta(minutes=3), S) is None  # already awake
    assert Decide(State, 12, 4, T0 + timedelta(minutes=10), S) == "leave"
    assert Decide(State, 2, 1, T0 + timedelta(minutes=15), S) is None  # resting after leaving (20 min)
    assert Decide(State, 2, 1, T0 + timedelta(minutes=31), S) == "wake"


def test_two_people_chatting_fast_is_not_dead():
    State = {}
    Decide(State, 25, 2, T0, S)
    assert Decide(State, 25, 2, T0 + timedelta(minutes=5), S) is None  # 2 people but many messages


def test_prompt_stays_within_budget():
    Recent = [{"author": f"U{I}", "content": "hola " * 50} for I in range(200)]
    System, User = BuildPrompt("Soy LOJI. " * 200, [{"name": "Ana", "text": "le gusta Frieren"}], Recent[:50], Recent, 6000, "Sótano", False)
    assert Tokens(System) + Tokens(User) <= 6000 + 200
    assert "U199" in User  # the newest lines are kept first
    assert "le gusta Frieren" in User and "menores" in System


def test_reply_parsing():
    R = ParseReply('ok {"mensajes": ["holi", "", "qué tal", "tres"], "recordar": [{"persona": "Ana", "dato": "examen el lunes"}], "alerta": ""}')
    assert R["messages"] == ["holi", "qué tal"] and R["notes"] == [{"name": "Ana", "text": "examen el lunes"}] and R["alert"] == ""


def test_a_conversation(monkeypatch):
    import cogs.Modules.Growth.lojichat as lc
    import core.guide
    from tests.economy.fakes import DB

    D = DB()
    monkeypatch.setattr(lc, "Db", lambda: D)

    class G:
        async def Get(self, g):
            return {"personality_text": "Eres LOJI, cálida y bromista."}

        async def Key(self, g):
            return "gsk_x"
    monkeypatch.setattr(lc, "Guide", lambda: G())

    async def Complete(key, system, user, **kw):
        return '{"mensajes": ["jajaja eso es muy de lunes"], "recordar": [{"persona": "Ana", "dato": "odia los lunes"}], "alerta": ""}', 100
    monkeypatch.setattr(core.guide, "Complete", Complete)

    async def NoSleep(*a):
        pass
    monkeypatch.setattr(lc.asyncio, "sleep", NoSleep)
    Sent = []

    class Channel:
        id = 7

        def typing(self):
            class T:
                async def __aenter__(s):
                    pass

                async def __aexit__(s, *a):
                    pass
            return T()

        async def send(self, text, **kw):
            Sent.append(text)

    Cog = lc.LojiChat.__new__(lc.LojiChat)
    Cog.client = N(user=N(id=999))
    Cog.state = {1: {"awake": True, "woke_at": T0}}
    Cog.live = {1: deque([{"author": "Ana", "author_id": 5, "content": "odio los lunes"}], maxlen=40)}
    Guild = N(id=1, name="Sótano")
    Settings = {**S, "daily_limit": 1}
    asyncio.run(Cog.Reply(Guild, Channel(), Settings, opening=False))
    assert Sent == ["jajaja eso es muy de lunes"]
    assert asyncio.run(D[lc.NOTES].find_one({}))["text"] == "odia los lunes"
    asyncio.run(Cog.Reply(Guild, Channel(), Settings, opening=False))  # her own message is last: she doesn't talk again
    Cog.live[1].append({"author": "Ana", "author_id": 5, "content": "jaja"})
    asyncio.run(Cog.Reply(Guild, Channel(), Settings, opening=False))  # daily limit (1) reached
    assert len(Sent) == 1
