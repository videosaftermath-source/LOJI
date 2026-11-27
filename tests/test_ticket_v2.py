import json
from datetime import datetime, timedelta, timezone

import pytest

from core.ticket_afk import Decide, OnMessage
from core.ticket_v2 import Build, ButtonRows

DESIGN = {"components": [{"type": 17, "accent_color": 12298390, "components": [
    {"type": 10, "content": "## Centro de ayuda"},
    {"type": 14},
    {"type": 10, "content": "-# pie"},
]}]}
BUTTONS = [
    {"custom_id": "abc123", "label": "Reporte", "style": "Red", "emoji": "<:ESS_pin_jap:1573211465580814336>"},
    {"custom_id": "def456", "label": "Soporte", "style": "Blurple", "emoji": "🛠️"},
]


def test_buttons_keep_birbs_ids_and_styles():
    Row = ButtonRows(BUTTONS)[0]["components"]
    assert [B["custom_id"] for B in Row] == ["abc123", "def456"]
    assert [B["style"] for B in Row] == [4, 1]
    assert Row[0]["emoji"] == {"name": "ESS_pin_jap", "id": "1573211465580814336", "animated": False}
    assert ButtonRows(BUTTONS, disabled=True)[0]["components"][0]["disabled"] is True
    assert len(ButtonRows([{"custom_id": f"x{I}", "label": "a"} for I in range(7)])) == 2  # 5 per row


def test_buttons_go_at_the_end_or_where_marked():
    Out = Build(json.dumps(DESIGN), BUTTONS)
    Box = Out[0]["components"]
    assert Box[-1]["type"] == 1 and Box[-2]["content"] == "-# pie"
    Marked = json.loads(json.dumps(DESIGN))
    Marked["components"][0]["components"].insert(2, {"type": 10, "content": " {botones} "})
    Box = Build(json.dumps(Marked), BUTTONS)[0]["components"]
    assert [C["type"] for C in Box] == [10, 14, 1, 10]


def test_design_problems_are_reported():
    with pytest.raises(ValueError, match="botones"):
        Build(json.dumps(DESIGN), [])
    Busy = {"components": [{"type": 17, "components": [{"type": 10, "content": "x"}] * 37}]}
    with pytest.raises(ValueError, match="40"):
        Build(json.dumps(Busy), BUTTONS)
    with pytest.raises(ValueError, match="enlace"):  # open buttons can't come from the JSON
        Build(json.dumps({"components": [{"type": 1, "components": [{"type": 2, "style": 1, "custom_id": "abc123"}]}]}), BUTTONS)


T0 = datetime(2026, 11, 27, tzinfo=timezone.utc)


def Ticket(**afk):
    return {"UserID": 1, "claimed": {"claimer": 2}, "afk": afk}


def test_autoclose_warns_at_24h_and_closes_12h_later():
    T = Ticket(staff_last=T0, user_last=T0 - timedelta(minutes=5))
    assert Decide(T, T0 + timedelta(hours=23), autoclose=True) != "autoclose_warn"
    assert Decide(T, T0 + timedelta(hours=24), autoclose=True) == "autoclose_warn"
    T["afk"]["autoclose_warned"] = T0 + timedelta(hours=24)
    assert Decide(T, T0 + timedelta(hours=30), autoclose=True) is None  # warned: no more pings
    assert Decide(T, T0 + timedelta(hours=36), autoclose=True) == "autoclose"
    assert Decide(T, T0 + timedelta(hours=36), autoclose=False) == "remind_user"  # panel without autoclose


def test_user_reply_or_waiting_on_staff_never_autocloses():
    T = Ticket(staff_last=T0, user_last=T0 - timedelta(minutes=5), autoclose_warned=T0 + timedelta(hours=24))
    Changes = OnMessage(T, 1, False, T0 + timedelta(hours=25))
    assert Changes["afk.autoclose_warned"] is None
    Waiting = Ticket(staff_last=T0, user_last=T0 + timedelta(hours=1), pending_since=None)
    assert Decide(Waiting, T0 + timedelta(hours=48), autoclose=True, afk=False) is None


def test_autoclosed_ticket_has_no_staff_to_rate():
    from cogs.Modules.feedback import TicketStaff

    assert TicketStaff({"UserID": 1, "claimed": {"claimer": None}, "closed": {"closer": 99}, "afk": {"autoclosed": True}}) is None
    assert TicketStaff({"UserID": 1, "claimed": {"claimer": 2}, "afk": {"autoclosed": True}}) == 2
