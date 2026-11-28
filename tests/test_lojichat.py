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
    assert ParseReply('{"mensajes": ["a"], "responder_a": "[3]"}')["reply_to"] == 3
    assert ParseReply('{"mensajes": ["a"], "responder_a": null}')["reply_to"] is None
    R = ParseReply('ok {"mensajes": ["holi", "", "qué tal", "tres"], "recordar": [{"persona": "Ana", "dato": "examen el lunes"}], "alerta": ""}')
    assert R["messages"] == ["holi"] and R["notes"] == [{"name": "Ana", "text": "examen el lunes"}] and R["alert"] == ""


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
        return '{"mensajes": ["jajaja eso es muy de lunes"], "responder_a": "[0]", "recordar": [{"persona": "Ana", "dato": "odia los lunes"}], "alerta": ""}', 100
    monkeypatch.setattr(core.guide, "Complete", Complete)

    async def NoSleep(*a):
        pass
    monkeypatch.setattr(lc.asyncio, "sleep", NoSleep)
    Sent, Replies = [], []

    class Channel:
        id = 7

        def get_partial_message(self, i):
            return N(id=i)

        def typing(self):
            class T:
                async def __aenter__(s):
                    pass

                async def __aexit__(s, *a):
                    pass
            return T()

        async def send(self, text, **kw):
            Sent.append(text)
            Replies.append(getattr(kw.get("reference"), "id", None))

    Cog = lc.LojiChat.__new__(lc.LojiChat)
    Cog.client = N(user=N(id=999))
    Cog.last_reply, Cog.handled = {}, {}
    Cog.state = {1: {"awake": True, "woke_at": T0}}
    Cog.live = {1: deque([{"author": "Ana", "author_id": 5, "content": "odio los lunes", "id": 501}], maxlen=40)}
    Guild = N(id=1, name="Sótano")
    Settings = {**S, "daily_limit": 1}
    asyncio.run(Cog.Reply(Guild, Channel(), Settings, opening=False))
    assert Sent == ["jajaja eso es muy de lunes"] and Replies == [501]  # nobody spoke to her: she chose to reply to Ana
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
    Cog.state, Cog.pending, Cog.batches = {}, {}, {}

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


def test_she_answers_one_person():
    from core.lojichat import AddressesLoji, PickTarget

    Lines = [
        {"author": "LOJI", "author_id": 999, "content": "holaa"},
        {"author": "Ana", "author_id": 1, "content": "loji qué haces", "to_loji": True, "id": 11},
        {"author": "Luis", "author_id": 2, "content": "@LOJI hola", "to_loji": True, "id": 12},
        {"author": "Eva", "author_id": 3, "content": "jaja", "id": 13},
    ]
    Target, Others = PickTarget(Lines)
    assert Target["author"] == "Luis" and Others == ["Ana"]  # the newest one talking to her; Ana is "the rest"
    Target, Others = PickTarget(Lines[:1] + [Lines[3]])
    assert Target["author"] == "Eva" and Others == []  # nobody tagged her: the newest message
    assert PickTarget(Lines[:1] + [Lines[3]], only_addressed=True) == (None, [])  # busy chat, told to talk: only if spoken to
    assert AddressesLoji("Hola LOJI", False, False) and AddressesLoji("x", True, False) and AddressesLoji("x", False, True)
    assert not AddressesLoji("hola a todos", False, False)


def test_several_tags_get_the_rest_text(monkeypatch):
    import cogs.Modules.Growth.lojichat as lc
    import core.guide
    from tests.economy.fakes import DB

    D = DB()
    monkeypatch.setattr(lc, "Db", lambda: D)

    class G:
        async def Get(self, g):
            return {"personality_text": "Eres LOJI.", "ai_model": "deepseek-v4-flash"}

        async def Key(self, g):
            return "sk-x"
    monkeypatch.setattr(lc, "Guide", lambda: G())
    Models = []

    async def Complete(key, system, user, **kw):
        Models.append(kw.get("model"))
        assert "Luis (mensaje [1]: «loji hola») te ha hablado a ti" in user
        return '{"mensajes": ["holi Luis", "esto sobra"], "responder_a": 0, "recordar": [], "alerta": ""}', 10  # Luis wins anyway
    monkeypatch.setattr(core.guide, "Complete", Complete)

    async def NoSleep(*a):
        pass
    monkeypatch.setattr(lc.asyncio, "sleep", NoSleep)
    Sent = []

    class Channel:
        def get_partial_message(self, i):
            return N(id=i)

        def typing(self):
            class T:
                async def __aenter__(s):
                    pass

                async def __aexit__(s, *a):
                    pass
            return T()

        async def send(self, text, **kw):
            Sent.append((text, getattr(kw.get("reference"), "id", None)))

    Cog = lc.LojiChat.__new__(lc.LojiChat)
    Cog.client = N(user=N(id=999))
    Cog.last_reply, Cog.handled = {}, {}
    Cog.state = {1: {"awake": True, "woke_at": T0}}
    Cog.live = {1: deque([{"author": "Ana", "author_id": 1, "content": "loji!", "to_loji": True, "id": 11},
                          {"author": "Luis", "author_id": 2, "content": "loji hola", "to_loji": True, "id": 12}], maxlen=40)}
    Cog.used_phrases = {}
    from core.lojichat_phrases import REST_PHRASES

    class Dice:  # answers only 1 person, and doesn't ignore the rest
        randint = staticmethod(lambda a, b: 1)  # (the real range is 4-6)
        random = staticmethod(lambda: 0.9)
        choice = staticmethod(lambda xs: xs[0])
        uniform = staticmethod(lambda a, b: a)
    monkeypatch.setattr(lc, "random", Dice)
    asyncio.run(Cog.Reply(N(id=1, name="S"), Channel(), dict(S), opening=False))
    assert Sent == [("holi Luis", 12), (REST_PHRASES[0], None)]  # one reply to Luis, then a phrase for the rest
    assert Models == ["deepseek-v4-flash"]


def test_she_answers_a_few_and_the_rest_gets_a_phrase():
    import random

    from core.lojichat import BuildPrompt, PickTargets, RestPhrase, RestPhrases

    Lines = [{"author": N, "author_id": I, "content": f"loji {N}", "to_loji": True, "id": 10 + I} for I, N in enumerate("ABCDE")]
    Lines.insert(2, {"author": "A", "author_id": 0, "content": "loji otra vez", "to_loji": True, "id": 99})
    Targets, Rest = PickTargets(Lines, most=3)
    assert [T["author"] for T in Targets] == ["C", "D", "E"] and Rest == 2  # the 3 newest people; A and B are "the rest"
    Targets, Rest = PickTargets(Lines, most=10)
    assert [T["author"] for T in Targets] == ["B", "A", "C", "D", "E"] and Rest == 0 and Targets[1]["id"] == 99  # A's newest
    _, User = BuildPrompt("x", [], [], Lines, 6000, "S", False, Targets[-2:])
    assert "exactamente 2" in User and "D (mensaje [4]" in User
    assert ParseReply('{"mensajes": ["a", "b", "c"]}', most=2)["messages"] == ["a", "b"]
    # the phrase: never one of the last ones, sometimes nothing at all, "nada" turns it off, own phrases one per line
    R, Recent = random.Random(1), []
    Said = [RestPhrase({**S, "rest_ignore": 0}, Recent, R) for _ in range(40)]
    assert all(Said[I] not in Said[max(0, I - 20):I] for I in range(40))
    Ignored = sum(RestPhrase(S, [], random.Random(I)) is None for I in range(300))
    assert 60 < Ignored < 140  # ~33 %
    assert RestPhrases({"rest_text": "nada"}) == [] and RestPhrases({"rest_text": "uno\n\n dos "}) == ["uno", "dos"]
    assert len(RestPhrases({"rest_text": "No respondo al resto porque me canso lol"})) == 110  # the old default = LOJI's list


def test_the_window_before_answering():
    from core.lojichat import BatchAdd, BatchReady, NewBatch

    def At(s):
        return T0 + timedelta(seconds=s)
    B = NewBatch(T0, 8)  # one person, nobody else in the first 4 s: she waits the slow 7-10 s
    assert not BatchReady(B, At(7.9)) and BatchReady(B, At(8))
    BatchAdd(B, At(6))  # after the first 4 s: joins the batch, but it stays slow
    assert not B["quick"] and BatchReady(B, At(8))
    B = NewBatch(T0, 8)
    BatchAdd(B, At(2))  # someone else within 4 s: quick, 3 s of silence is enough
    assert B["quick"] and not BatchReady(B, At(4.9)) and BatchReady(B, At(5))
    for I in range(30):  # a never-ending stream: 20 s at most
        BatchAdd(B, At(2 + I))
    assert not BatchReady(B, At(19.9)) and BatchReady(B, At(20))


def test_she_never_answers_the_same_message_twice():
    from core.lojichat import PickTargets

    Lines = [{"author": "Ana", "author_id": 1, "content": "loji", "to_loji": True, "id": 1},
             {"author": "LOJI", "author_id": 999, "content": "dime"},
             {"author": "Luis", "author_id": 2, "content": "loji yo tmb", "to_loji": True, "id": 2}]
    Targets, _ = PickTargets(Lines, most=4, handled=set())
    assert [T["id"] for T in Targets] == [1, 2]  # Ana wrote while she was sending: still answered
    assert PickTargets(Lines, most=4, handled={1, 2}) == ([], 0)
