import asyncio
import time
from types import SimpleNamespace as N

import pytest

from core.mail.config import DefaultConfig
from core.staff.feedback import Feedback, FeedbackError, IsStaff, Summary
from tests.economy.fakes import DB


def run(c):
    return asyncio.run(c)


def test_rules_ids_and_tickets():
    db = DB()
    run(db["feedback"].insert_one({"guild_id": 1, "staff": 9, "author": 3, "rating": "8", "feedbackid": 41, "date": 0}))
    f = Feedback(db)
    with pytest.raises(FeedbackError):
        run(f.Add(1, 5, 5, 10))  # self
    a = run(f.Add(1, 5, 9, 10, "genial"))
    assert a["feedbackid"] == 42  # continues Birb's ids
    with pytest.raises(FeedbackError):
        run(f.Add(1, 5, 9, 7))  # once a week by command
    t = run(f.Add(1, 5, 9, 6, "", ticket="abc", ticket_name="reporte-001"))  # tickets are separate
    assert t["feedbackid"] == 43
    with pytest.raises(FeedbackError):
        run(f.Add(1, 5, 9, 6, "", ticket="abc"))  # one per ticket
    run(db["feedback"].update_one({"feedbackid": 42}, {"$set": {"date": time.time() - 8 * 86400}}))
    run(f.Add(1, 5, 9, 9))
    avg, n = Summary(run(f.Of(1, 9)))
    assert n == 4 and round(avg, 2) == round((8 + 10 + 6 + 9) / 4, 2)
    assert run(f.Remove(1, 43))["rating"] == 6 and run(f.Remove(1, 43)) is None


def test_staff_detection():
    c = DefaultConfig(1)
    c["staff_role"], c["profile_roles"], c["offices"]["tenno"]["role"] = 10, [20, 21], 30
    m = lambda *ids: N(roles=[N(id=i) for i in ids])
    assert IsStaff(m(10), c) and IsStaff(m(21), c) and IsStaff(m(30), c)
    assert not IsStaff(m(99), c)


def test_ticket_staff():
    from cogs.Modules.feedback import TicketStaff

    assert TicketStaff({"UserID": 1, "claimed": {"claimer": 2}, "closed": {"closer": 3}}) == 2
    assert TicketStaff({"UserID": 1, "claimed": {"claimer": None}, "closed": {"closer": 3}}) == 3
    assert TicketStaff({"UserID": 1, "closed": {"closer": 1}}) is None
