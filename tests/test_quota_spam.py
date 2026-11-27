from core.quota_spam import DEFAULTS, Settings, Tracker

S = dict(DEFAULTS)
K = (1, 2)


def test_normal_chat_always_counts():
    T = Tracker()
    assert all(T.Check(K, I * 4.0, S)[0] for I in range(50))  # one message every 4 s: never spam


def test_level_1_writing_fast():
    T = Tracker()
    Results = [T.Check(K, I * 0.8, S) for I in range(9)]  # hola / como estas / bien / tu / si / jaja / ...
    assert [R[0] for R in Results] == [True] * 6 + [False] * 3  # the extra ones don't count
    assert [R[1] for R in Results] == [0] * 6 + [1, 0, 0]  # one soft notice, not one per message
    assert T.Check(K, 30, S) == (True, 0, 0)  # calm again: counts


def test_level_2_takes_back_and_pauses():
    T = Tracker()
    Results = [T.Check(K, I * 2.0, S) for I in range(30)]  # 30 messages in 60 s
    Counted = sum(1 for R in Results[:-1] if R[0])
    assert Results[-1] == (False, 2, Counted) and Counted > 0
    assert T.Check(K, 61, S) == (False, 0, 0)  # paused: nothing counts
    assert T.Check(K, 60 + 10 * 60 + 1, S)[0] is True  # 10 min later it counts again


def test_people_are_separate_and_settings_merge():
    T = Tracker()
    for I in range(7):
        T.Check((1, 2), I * 0.5, S)
    assert T.Check((1, 3), 4, S) == (True, 0, 0)
    assert Settings({"Message Quota": {"AntiSpam": {"l1_count": 9}}})["l1_count"] == 9
    assert Settings(None)["enabled"] is True


def test_who_is_called():
    from cogs.Events.on_counter import NotifyMention

    assert NotifyMention({"notify": {"id": 5, "type": "user"}}) == "<@5>"
    assert NotifyMention({"notify": {"id": 6, "type": "role"}}) == "<@&6>"
    assert NotifyMention({}) == "la administración"
