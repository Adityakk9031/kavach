"""Call end: only flagged calls get a complaint draft and a family message; secrets stay out of logs."""

import asyncio
import json
import logging
import time
from types import SimpleNamespace

from app.call_room import CallRoom
from app.config import Settings
from app.finalize import make_finalize, was_flagged
from app.store import Store
from tests.test_tts_warner import NoStt


def build(tmp_path, triggered=False, takeover=False, evidence=None):
    store = Store(":memory:")
    room = CallRoom("f1", NoStt, store)
    store.update_call("f1", started_at=time.time() - 60, caller_number="+91 90000 00000")
    q1, q2 = asyncio.Queue(), asyncio.Queue()
    room.pipeline = SimpleNamespace(queue=q1, triggered=triggered, max_risk=80.0)
    room.evidence = SimpleNamespace(queue=q2, valid_items=lambda: evidence or [])
    room.persona = SimpleNamespace(active=False, replies=1 if takeover else 0)
    room.takeover = False
    sent = []

    async def call_ended(text, pdf):
        sent.append((text, pdf))

    async def drain():
        pass

    room.alerts = SimpleNamespace(call_ended=call_ended, drain=drain)
    settings = Settings(_env_file=None, reports_dir=str(tmp_path))
    return room, store, settings, sent


async def test_unflagged_call_with_a_phone_number_gets_no_report_and_no_alert(tmp_path):
    # A genuine delivery agent says "call 9876543210": regexes capture it, but nothing flagged the call.
    ev = [{"type": "phone_number", "value": "9876543210", "valid": True}]
    room, store, settings, sent = build(tmp_path, triggered=False, takeover=False, evidence=ev)
    assert was_flagged(room) is False
    assert await make_finalize(room, store, settings)() == {}
    assert sent == [] and list(tmp_path.iterdir()) == []


async def test_triggered_call_gets_a_report_a_link_and_one_call_end_message(tmp_path):
    room, store, settings, sent = build(tmp_path, triggered=True)
    out = await make_finalize(room, store, settings)()
    assert out["report"]["pdf"] == "/api/calls/f1/report.pdf" and out["report"]["md"].endswith("/report.md")
    assert len(sent) == 1 and "Complaint draft ready" in sent[0][0] and sent[0][1].suffix == ".pdf"
    assert sent[0][1].exists() and (tmp_path / "f1.md").exists()
    assert "report_ready" in [e["type"] for e in store.events("f1")]


async def test_a_call_that_used_takeover_is_flagged_even_if_never_triggered(tmp_path):
    room, store, settings, sent = build(tmp_path, triggered=False, takeover=True)
    assert was_flagged(room)
    assert (await make_finalize(room, store, settings)())["report"]


def test_http_client_request_urls_are_not_logged_because_they_contain_the_bot_token():
    import app.main  # noqa: F401  (configures logging on import)

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
