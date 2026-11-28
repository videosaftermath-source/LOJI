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
    Cog.last_reply = {}
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


def test_only_the_tenno_code_switches_her(monkeypatch):
    import cogs.Modules.Growth.lojichat as lc
    import core.mail.config as mc
    from core.community import Community
    from core.mail.config import DefaultConfig, Hash
    from tests.economy.fakes import DB

    D = DB()
    Store = Community(D)
    monkeypatch.setattr(lc, "Community", lambda: Store)
    Config = DefaultConfig(1)
    Config["offices"]["tenno"]["credential"] = Hash("T-1234")

    class FakeMail:
        async def Get(self, g):
            return Config
    monkeypatch.setattr(mc, "Mail", FakeMail)

    class G:
        async def Get(self, g):
            return {"personality_text": "x"}
    monkeypatch.setattr(lc, "Guide", lambda: G())
    asyncio.run(Store.Set(1, "lojichat", {"channel": 7, "enabled": False}))
    Said, Sent, Acts = [], [], []

    class Channel:
        mention = "<#7>"

        async def send(self, text, **kw):
            Sent.append(text)

    Cog = lc.LojiChat.__new__(lc.LojiChat)
    Cog.state, Cog.pending = {}, {}

    async def Act(guild, channel, s, what, people, messages):
        Acts.append(what)
    Cog.Act = Act
    Guild = N(id=1, get_channel=lambda i: Channel() if i == 7 else None)

    def Submit(code, action, uid=60):
        M = lc.TennoSwitch()
        M.code._value = code
        M.action._values = [action]

        async def send_message(text, **kw):
            Said.append(text)

        async def defer(**kw):
            pass

        async def followup_send(text, **kw):
            Said.append(text)
        return M.on_submit(N(guild=Guild, user=N(id=uid), client=N(get_cog=lambda n: Cog),
                             response=N(send_message=send_message, defer=defer), followup=N(send=followup_send)))

    asyncio.run(Submit("M-0000", "talk", uid=50))  # an admin without the code
    assert "incorrecta" in Said[-1] and Acts == []
    asyncio.run(Submit("T-1234", "talk"))  # talk now, even with the automatic mode off
    assert "está hablando" in Said[-1] and Acts == ["wake"] and Cog.state[1]["forced"] and Cog.state[1]["awake"]
    asyncio.run(Submit("T-1234", "quiet"))
    assert "se ha callado" in Said[-1] and Acts == ["wake", "leave"] and not Cog.state[1]["awake"]
    asyncio.run(Submit("T-1234", "toggle"))
    assert "encendido" in Said[-1] and asyncio.run(Store.Get(1))["lojichat"]["enabled"] is True


def test_forced_she_stays_even_if_the_chat_is_busy(monkeypatch):
    import cogs.Modules.Growth.lojichat as lc

    async def Settings(g):
        return {**S, "enabled": True, "channel": 7}
    monkeypatch.setattr(lc, "Settings", Settings)
    Cog = lc.LojiChat.__new__(lc.LojiChat)
    Cog.client = N(guilds=[N(id=1, get_channel=lambda i: N(id=7))])
    Cog.state = {1: {"awake": True, "forced": True}}
    Cog.activity = Activity()
    for I in range(40):
        Cog.activity.Add(7, I, datetime.now(timezone.utc))  # very busy chat
    Cog.ticks = 1
    Acts = []

    async def Act(*a):
        Acts.append(a[3])
    Cog.Act = Act
    asyncio.run(lc.LojiChat.Check.coro(Cog))
    assert Acts == [] and Cog.state[1]["awake"]  # told to talk: she doesn't leave on her own
    Cog.state[1]["forced"] = False
    asyncio.run(lc.LojiChat.Check.coro(Cog))
    assert Acts == ["leave"]  # automatic mode: a busy chat sends her away
