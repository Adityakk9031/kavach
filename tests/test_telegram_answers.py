"""The family answers the two complaint questions with Telegram buttons (mock Telegram: nothing is really sent)."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.alerts import Alerter, CallAlerts, answer_keyboard
from app.call_room import CallRoom
from app.config import Settings
from app.finalize import handle_answer_callback
from app.store import Store
from tests.test_report_alerts import decision, make_call_alerts, seeded_store
from tests.test_tts_warner import NoStt


def test_keyboard_has_four_buttons_within_telegrams_limit_and_marks_the_chosen_answers():
    kb = answer_keyboard("abc123", money=False, otp=None)["inline_keyboard"]
    flat = [b for row in kb for b in row]
    assert len(flat) == 4 and all(len(b["callback_data"].encode()) <= 64 for b in flat)
    assert [b["callback_data"] for b in flat] == ["a:abc123:m:y", "a:abc123:m:n", "a:abc123:o:y", "a:abc123:o:n"]
    assert [b["text"].startswith("✅") for b in flat] == [False, True, False, False]  # money: No is marked


def test_a_token_stands_for_one_call():
    st = Store(":memory:")
    t1, t2 = st.make_answer_token("callA"), st.make_answer_token("callA")
    assert t1 != t2 and st.call_for_token(t1) == "callA" and st.call_for_token("nope") is None


async def test_the_call_end_message_carries_the_buttons_and_a_token_for_this_call():
    sent = []

    def handler(req: httpx.Request):
        sent.append((req.url.path, json.loads(req.content) if req.content and req.url.path.endswith("sendMessage") else None))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9, "chat": {"id": 999}}})

    room = CallRoom("tk1", NoStt, Store(":memory:"))
    cfg = Settings(_env_file=None, telegram_bot_token="123:abc", telegram_chat_id="999")
    alerter = Alerter(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    pipeline = SimpleNamespace(on_trigger=[], on_new_stage=[], triggered=True, max_risk=80.0)
    ca = CallAlerts(alerter, room, pipeline, None, 3)
    await ca.call_ended("call ended", None)
    await ca.drain()
    payload = next(p for path, p in sent if path.endswith("sendMessage"))
    buttons = [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]
    token = buttons[0]["callback_data"].split(":")[1]
    assert room.store.call_for_token(token) == "tk1" and len(buttons) == 4


class FakeAlerter:
    def __init__(self):
        self.answers, self.edits, self.docs = [], [], []

    async def answer_callback(self, cid, text):
        self.answers.append((cid, text))

    async def edit_markup(self, chat_id, message_id, markup):
        self.edits.append((chat_id, message_id, markup))

    async def send_document(self, path, caption):
        self.docs.append((Path(path), caption))


def press(token, q, a, chat=999, cid="cb1"):
    return {"update_id": 1, "callback_query": {"id": cid, "data": f"a:{token}:{q}:{a}",
                                               "message": {"message_id": 5, "chat": {"id": chat}}}}


async def test_pressing_the_buttons_records_the_answers_rebuilds_the_draft_and_sends_it_when_complete(tmp_path):
    st = seeded_store()
    cfg = Settings(_env_file=None, telegram_chat_id="999", reports_dir=str(tmp_path))
    fake = FakeAlerter()
    token = st.make_answer_token("r1")

    await handle_answer_callback(press(token, "m", "n"), fake, st, cfg)
    assert st.query("SELECT money_shared, otp_shared FROM calls WHERE id='r1'")[0] == {"money_shared": 0, "otp_shared": None}
    assert fake.answers[-1][1] == "Saved: Money sent = No" and fake.docs == []  # one question left: no document yet
    marked = [b["text"] for row in fake.edits[-1][2]["inline_keyboard"] for b in row]
    assert marked[1].startswith("✅") and not marked[2].startswith("✅")
    assert "Money sent:** No" in (tmp_path / "r1.md").read_text()

    await handle_answer_callback(press(token, "o", "y", cid="cb2"), fake, st, cfg)
    assert st.query("SELECT otp_shared FROM calls WHERE id='r1'")[0]["otp_shared"] == 1
    md = (tmp_path / "r1.md").read_text()
    assert "Money sent:** No" in md and "OTP / PIN / card details shared:** YES" in md
    assert len(fake.docs) == 1 and fake.docs[0][0].suffix == ".pdf"  # both answered: the finished draft is sent once


async def test_presses_from_other_chats_expired_tokens_and_junk_are_ignored(tmp_path):
    st = seeded_store()
    cfg = Settings(_env_file=None, telegram_chat_id="999", reports_dir=str(tmp_path))
    fake = FakeAlerter()
    token = st.make_answer_token("r1")
    await handle_answer_callback(press(token, "m", "y", chat=12345), fake, st, cfg)  # not the family chat
    assert st.query("SELECT money_shared FROM calls WHERE id='r1'")[0]["money_shared"] is None and fake.answers == []
    await handle_answer_callback(press("unknowntk", "m", "y"), fake, st, cfg)
    assert fake.answers[-1][1] == "This question has expired."
    await handle_answer_callback({"update_id": 2, "callback_query": {"id": "x", "data": "rm -rf /", "message": {"message_id": 1, "chat": {"id": 999}}}}, fake, st, cfg)
    await handle_answer_callback({"update_id": 3, "message": {"text": "hi"}}, fake, st, cfg)
    assert len(fake.answers) == 1  # nothing else did anything


async def test_poll_hands_updates_to_the_handler_and_advances_the_offset():
    seen, offsets = [], []

    def handler(req: httpx.Request):
        offsets.append(req.url.params.get("offset"))
        result = [{"update_id": 41, "callback_query": {"id": "c"}}] if len(offsets) == 1 else []
        return httpx.Response(200, json={"ok": True, "result": result})

    cfg = Settings(_env_file=None, telegram_bot_token="123:abc", telegram_chat_id="999")
    alerter = Alerter(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def on_update(u):
        seen.append(u["update_id"])

    task = asyncio.create_task(alerter.poll(on_update, long_poll_s=0))
    for _ in range(100):
        if len(offsets) >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert seen == [41] and offsets[0] is None and offsets[1] == "42"
