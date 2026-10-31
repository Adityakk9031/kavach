"""M5 offline: decoy guard, evidence extraction/validation, persona takeover / interruption / take-back."""

import asyncio
import json

import pytest
import websockets

from app.call_room import SOURCE_PERSONA, CallRoom
from app.config import Settings
from app.evidence import EvidenceCollector, LlmItem, regex_items, supported_by_text
from app.llm import LLMError
from app.persona import OPENING, STALLS, Persona, guard
from app.store import Store
from app.tts import TtsSession
from tests.test_tts_warner import FakeTtsServer, FakeWs, NoStt

DECOY = "nine nine nine nine nine, zero zero zero zero zero"


# ---- guard -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,reason", [
    ("My number is 9876543210.", "digits"),
    ("Send it to ramesh@oksbi please", "digits"),  # no digits but address-like -> see below
])
def test_guard_blocks_digits_and_addresses(text, reason):
    out, why = guard(text, DECOY)
    assert why is not None and out in STALLS


def test_guard_blocks_address_without_digits():
    for t in ("You can mail me at ramesh at gmail dot com or ramesh@gmail.com", "Go to www.something.com", "see https://x"):
        assert guard(t, DECOY)[1] == "address-like"


def test_guard_allows_the_decoy_phone_but_not_other_number_runs():
    ok = f"Sure, my number is {DECOY}, did you get it?"
    assert guard(ok, DECOY) == (ok, None)
    out, why = guard("My number is five five five one two three four, ok?", DECOY)
    assert why == "number-run" and out in STALLS
    assert guard("Oh, one moment, I have two sons and three grandchildren.", DECOY)[1] is None


def test_guard_blocks_empty_and_overlong():
    assert guard("   ", DECOY)[1] == "empty"
    assert guard("word " * 120, DECOY)[1] == "too-long"
    assert guard('"Ah, please say that again."', DECOY) == ("Ah, please say that again.", None)  # quotes stripped


# ---- evidence regexes --------------------------------------------------------------------------------------

def kinds(text):
    return {(i.type, i.value) for i in regex_items(text)}


def test_regex_finds_scam_identifiers():
    k = kinds("Pay at customs.clear@okbank now, IFSC SBIN0001234, account 123456789012, call +91 98765 43210 "
              "or visit www.rbi-verify.in/pay and install AnyDesk. The fine is Rs. 50,000.")
    types = {t for t, _ in k}
    assert {"upi_id", "ifsc", "bank_account", "phone_number", "url", "app_name", "amount"} <= types
    assert ("upi_id", "customs.clear@okbank") in k and ("ifsc", "SBIN0001234") in k
    assert ("bank_account", "123456789012") in k
    # the UPI handle's domain is not reported as a separate URL, and the account is not mistaken for a phone
    assert not any(t == "url" and "okbank" in v for t, v in k)
    assert not any(t == "phone_number" and v == "123456789012" for t, v in k)


def test_regex_ignores_ordinary_text():
    assert kinds("Hello, this is the bank, please stay on the line and do not worry.") == set()
    assert not any(t == "bank_account" for t, _ in kinds("It is two thirty on 5 June 2026"))


# ---- evidence validation ----------------------------------------------------------------------------------

def test_supported_by_text():
    assert supported_by_text(LlmItem(type="person_name", value="Inspector Vikram Rathore"), "I am inspector Vikram Rathore.")
    assert not supported_by_text(LlmItem(type="person_name", value="Inspector Sameer Khan"), "I am Vikram Rathore.")
    assert supported_by_text(LlmItem(type="phone_number", value="98765 43210"), "call me on 9876543210")
    assert not supported_by_text(LlmItem(type="phone_number", value="9876500000"), "call me on 9876543210")
    assert supported_by_text(LlmItem(type="upi_id", value="Pay@OkBank"), "send to pay @ okbank")
    assert supported_by_text(LlmItem(type="agency", value="Mumbai Cyber Crime"), "from the Mumbai cyber crime branch")
    with pytest.raises(ValueError):
        LlmItem(type="shoe_size", value="9")


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    async def chat(self, model, messages, **kw):
        self.calls.append(messages)
        if self.error:
            raise LLMError(self.error)
        return self.reply, 42

    async def chat_json(self, schema, messages, **kw):
        self.calls.append(messages)
        if self.error:
            raise LLMError(self.error)
        return schema.model_validate(json.loads(self.reply)), 42, "fake"


def turn(text, idx=0):
    return {"channel": "caller", "text": text, "idx": idx, "turn_id": idx + 1, "audio_end_ms": 1000 * (idx + 1)}


async def test_collector_dedupes_validates_and_stores():
    room = CallRoom("e1", NoStt, Store(":memory:"))
    llm = FakeLLM(json.dumps({"entities": [
        {"type": "person_name", "value": "Vikram Rathore", "quote": "I am Vikram Rathore"},
        {"type": "officer_id", "value": "BX 4471", "quote": "made up"},  # not in the text -> invalid
        {"type": "upi_id", "value": "pay@okbank", "quote": "pay@okbank"},  # duplicate of the regex hit
    ]}))
    room.takeover = True  # flagged call -> the LLM pass runs
    ev = EvidenceCollector(room, llm, "m")
    new = await ev.process(turn("I am Vikram Rathore, pay to pay@okbank today"))
    values = {(n["type"], n["value"], n["valid"]) for n in new}
    assert ("person_name", "Vikram Rathore", True) in values
    assert ("officer_id", "BX 4471", False) in values
    assert sum(1 for n in new if n["type"] == "upi_id") == 1  # regex and LLM found the same UPI ID once
    assert await ev.process(turn("again: pay@okbank", idx=1)) == []  # de-duplicated across turns
    assert all(v["valid"] for v in ev.valid_items()) and not any(v["value"] == "BX 4471" for v in ev.valid_items())
    rows = room.store.query("SELECT type, value, valid, ts_ms FROM evidence WHERE call_id='e1'")
    assert len(rows) == 3 and {r["valid"] for r in rows} == {0, 1} and rows[0]["ts_ms"] == 1000
    await ev.close()


async def test_collector_uses_regex_only_until_call_is_flagged_and_survives_llm_errors():
    room = CallRoom("e2", NoStt, Store(":memory:"))
    llm = FakeLLM(error="down")
    ev = EvidenceCollector(room, llm, "m")
    new = await ev.process(turn("send money to pay.now@okbank"))
    assert [n["type"] for n in new] == ["upi_id"] and llm.calls == []  # not flagged: no LLM call
    room.takeover = True
    await ev.process(turn("my name is Vikram", idx=1))
    assert llm.calls  # flagged: LLM tried
    assert any(e["type"] == "evidence_llm_error" for e in room.store.events("e2"))  # failure logged, nothing raised
    await ev.close()


# ---- persona ------------------------------------------------------------------------------------------------

@pytest.fixture
async def server():
    fake = FakeTtsServer(frames=60)
    srv = await websockets.serve(fake.handler, "127.0.0.1", 0)
    fake.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/ws"
    yield fake
    srv.close()
    await srv.wait_closed()


class OnePool:
    def __init__(self, s):
        self.s = s

    async def get(self, voice, label="x"):
        return self.s


async def make(server, llm_reply="Ah, can you say the account number slowly please?"):
    cfg = Settings(_env_file=None, tts_ws_url=server.url, assemblyai_api_key="k", persona_voice_id="aai-gunnar")
    s = TtsSession(cfg, "aai-gunnar")
    await s.start()
    llm = FakeLLM(llm_reply)
    room = CallRoom("p1", NoStt, Store(":memory:"))
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    cp = Persona(cfg, llm, OnePool(s)).attach(room)
    return room, cp, llm, caller, receiver, s


async def wait_for(cond, t=3.0):
    end = asyncio.get_event_loop().time() + t
    while not cond():
        assert asyncio.get_event_loop().time() < end, "timed out"
        await asyncio.sleep(0.01)


async def test_takeover_mutes_receiver_speaks_opening_to_both_and_ignores_caller_role(server):
    room, cp, llm, caller, receiver, s = await make(server)
    await room.control_handlers["takeover"](room, "caller", {})  # a scammer cannot trigger takeover
    assert not cp.active and not room.takeover
    await room.control_handlers["takeover"](room, "receiver", {})
    assert cp.active and room.takeover
    await wait_for(lambda: len(caller.binary) >= 3)
    assert caller.binary[0][0] == SOURCE_PERSONA and receiver.binary[0][0] == SOURCE_PERSONA  # caller hears, user monitors
    assert any(e["type"] == "persona" and e.get("text") == OPENING for e in receiver.text)
    await room.on_audio("receiver", b"\x01\x00" * 800)  # the user's own voice must NOT reach the caller
    assert all(b[0] == SOURCE_PERSONA for b in caller.binary)
    assert room.store.query("SELECT takeover_at FROM calls WHERE id='p1'")[0]["takeover_at"] is not None
    await s.close()


async def test_persona_replies_to_each_caller_turn_and_stores_decoy_turns(server):
    room, cp, llm, caller, receiver, s = await make(server)
    await room.control_handlers["takeover"](room, "receiver", {})
    await wait_for(lambda: cp.request is not None and cp.request.done.is_set())
    await cp.on_final(room, turn("Send the money to pay@okbank now."))
    await wait_for(lambda: len(llm.calls) == 1)
    sent = llm.calls[0]
    assert sent[0]["role"] == "system" and "Ramesh Kumar" in sent[0]["content"] and "Nagpur" in sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": "Send the money to pay@okbank now."}
    await wait_for(lambda: any(e["type"] == "persona" and e.get("text", "").startswith("Ah, can you say") for e in receiver.text))
    rows = room.store.query("SELECT channel, is_decoy FROM turns WHERE call_id='p1' AND channel='persona'")
    assert rows and all(r["is_decoy"] == 1 for r in rows)  # decoy speech is flagged in the log
    await s.close()


async def test_unsafe_llm_output_is_replaced_before_it_is_spoken(server):
    room, cp, llm, caller, receiver, s = await make(server, llm_reply="Sure, my Aadhaar is 1234 5678 9012.")
    await room.control_handlers["takeover"](room, "receiver", {})
    await wait_for(lambda: cp.request is not None and cp.request.done.is_set())
    await cp.on_final(room, turn("Tell me your Aadhaar number."))
    await wait_for(lambda: any(e["type"] == "persona_guard" for e in room.store.events("p1")))
    spoken = [e["text"] for e in receiver.text if e["type"] == "persona" and e.get("text")]
    assert not any("1234" in t for t in spoken) and spoken[-1] in STALLS
    await s.close()


async def test_llm_failure_falls_back_to_a_stall(server):
    room, cp, llm, caller, receiver, s = await make(server)
    llm.error = "429"
    await room.control_handlers["takeover"](room, "receiver", {})
    await wait_for(lambda: cp.request is not None and cp.request.done.is_set())
    await cp.on_final(room, turn("Hello? Are you there?"))
    await wait_for(lambda: any(e["type"] == "persona" and e.get("text") in STALLS for e in receiver.text))
    await s.close()


async def test_caller_speaking_interrupts_the_persona(server):
    room, cp, llm, caller, receiver, s = await make(server)
    await room.control_handlers["takeover"](room, "receiver", {})
    await wait_for(lambda: len(caller.binary) >= 3 and cp.speaking)
    n = len(caller.binary)
    await cp.on_speech_started(room, "caller", {})
    await asyncio.sleep(0.3)
    assert len(caller.binary) <= n + 1  # generation cancelled; at most a frame already on the wire
    assert [e for e in caller.text if e["type"] == "flush_playback" and e["source"] == SOURCE_PERSONA]
    assert any(e["type"] == "persona_interrupted" for e in room.store.events("p1"))
    await s.close()


async def test_takeback_unmutes_cancels_and_flushes_both_tabs(server):
    room, cp, llm, caller, receiver, s = await make(server)
    await room.control_handlers["takeover"](room, "receiver", {})
    await wait_for(lambda: len(caller.binary) >= 3 and cp.speaking)
    await room.control_handlers["takeback"](room, "receiver", {})
    assert not cp.active and not room.takeover  # unmuted immediately
    for ws in (caller, receiver):
        assert [e for e in ws.text if e["type"] == "flush_playback" and e["source"] == SOURCE_PERSONA]
    n = len(caller.binary)
    await asyncio.sleep(0.3)
    assert len(caller.binary) == n  # persona audio stopped
    assert any(e["type"] == "takeover" and e["state"] == "off" for e in receiver.text)
    ev = [e for e in room.store.events("p1") if e["type"] == "takeback"]
    assert ev and ev[0]["payload"]["total_ms"] < 300
    caller.binary.clear()
    await room.on_audio("receiver", b"\x01\x00" * 800)
    assert caller.binary and caller.binary[0][0] == 0  # the user's voice reaches the caller again (SOURCE_PEER)
    await cp.on_final(room, turn("Hello?", idx=3))  # no persona reply after take back
    await asyncio.sleep(0.1)
    assert llm.calls == []
    await s.close()


@pytest.mark.parametrize("text", [
    "My pin is one two three, ok?", "It is one two three four.", "You can write to me, Ramesh at the rate okaxis.",
    "Send it to ramesh dot com please", "My UPI is ramesh at gmail", "Is it zero zero zero? I will check.",
])
def test_guard_blocks_invented_pins_and_spoken_addresses(text):
    out, why = guard(text, DECOY)
    assert why is not None and out in STALLS


def test_guard_blocks_extra_digits_next_to_the_decoy_phone():
    out, why = guard(f"My number is {DECOY} and my pin is one two three four.", DECOY)
    assert why == "number-run"  # the decoy phone no longer excuses other number runs in the same reply
    assert guard(f"Ah, my number is {DECOY}.", DECOY)[1] is None


async def test_invalid_evidence_is_upgraded_when_the_caller_really_says_it():
    room = CallRoom("e3", NoStt, Store(":memory:"))
    llm = FakeLLM(json.dumps({"entities": [{"type": "officer_id", "value": "BX 4471", "quote": "x"}]}))
    room.takeover = True
    ev = EvidenceCollector(room, llm, "m")
    await ev.process(turn("I am an officer", idx=0))  # hallucinated: not in the text
    assert not ev.valid_items()
    llm.reply = json.dumps({"entities": [{"type": "officer_id", "value": "BX 4471", "quote": "my badge is BX 4471"}]})
    await ev.process(turn("my badge is BX 4471", idx=1))  # now genuinely said
    assert [v["value"] for v in ev.valid_items()] == ["BX 4471"]
    assert room.store.query("SELECT valid FROM evidence WHERE call_id='e3' AND type='officer_id'")[0]["valid"] == 1
    await ev.close()


async def test_two_finals_from_one_long_caller_line_get_one_reply(server):
    room, cp, llm, caller, receiver, s = await make(server)
    await room.control_handlers["takeover"](room, "receiver", {})
    await wait_for(lambda: cp.request is not None and cp.request.done.is_set())
    llm.calls.clear()
    await cp.on_final(room, turn("Listen carefully, this is a criminal matter.", idx=3))
    await asyncio.sleep(0.2)
    await cp.on_final(room, turn("You must not tell anyone.", idx=5))  # STT split the same sentence
    await wait_for(lambda: len(llm.calls) >= 1)
    await asyncio.sleep(1.2)
    assert len(llm.calls) == 1  # one reply, to the latest thing said
    assert [m["content"] for m in llm.calls[0] if m["role"] == "user"][-2:] == [
        "Listen carefully, this is a criminal matter.", "You must not tell anyone."]
    await s.close()


async def test_caller_starting_to_speak_drops_a_reply_that_is_still_being_prepared(server):
    room, cp, llm, caller, receiver, s = await make(server)
    await room.control_handlers["takeover"](room, "receiver", {})
    await wait_for(lambda: cp.request is not None and cp.request.done.is_set())
    llm.calls.clear()
    cp.play_until = 0.0  # the opening line has finished playing: nothing is audible
    await cp.on_final(room, turn("Are you there?", idx=3))
    await cp.on_speech_started(room, "caller", {})  # the caller is not done
    await asyncio.sleep(1.2)
    assert llm.calls == [] and any(e["type"] == "persona_reply_dropped" for e in room.store.events("p1"))
    await s.close()


async def test_opening_line_said_before_the_call_was_flagged_is_still_scanned_by_the_llm():
    room = CallRoom("e4", NoStt, Store(":memory:"))
    llm = FakeLLM(json.dumps({"entities": [
        {"type": "person_name", "value": "Vikram Rathore", "quote": "Inspector Vikram Rathore"},
        {"type": "agency", "value": "Mumbai Cyber Crime Cell", "quote": "Mumbai Cyber Crime Cell"}]}))
    ev = EvidenceCollector(room, llm, "m")
    await ev.process(turn("Hello, I am Inspector Vikram Rathore from the Mumbai Cyber Crime Cell.", idx=0))
    assert llm.calls == [] and ev.valid_items() == []  # not flagged yet: no LLM spend
    room.takeover = True  # the call gets flagged on the next turn
    await ev.process(turn("Pay fifty thousand rupees now.", idx=1))
    assert len(llm.calls) == 1  # one request covering the earlier turn too
    assert {v["type"] for v in ev.valid_items()} == {"person_name", "agency"}
    await ev.close()


def test_plausibility_rejects_what_must_never_reach_a_police_complaint():
    from app.evidence import plausible

    ok = lambda typ, val, names=(): plausible(LlmItem(type=typ, value=val), names)  # noqa: E731
    assert not ok("upi_id", "")  # empty values are not "in" every text
    assert not ok("agency", "Inspector") and not ok("person_name", "Mr.") and not ok("person_name", "Officer")
    assert not ok("person_name", "Mr. Ramesh Kumar", ("Ramesh Kumar",))  # the person being called, not the caller
    assert ok("person_name", "Inspector Vikram Rathore", ("Ramesh Kumar",))
    assert not ok("upi_id", "customs clear okbank") and ok("upi_id", "customs.clear@okbank")
    assert not ok("ifsc", "HDFC123") and ok("ifsc", "HDFC0001234")
    assert not ok("phone_number", "98765") and ok("phone_number", "9820133456")
    assert not ok("bank_account", "1234") and ok("bank_account", "50100234567891")
    assert not ok("amount", "the money") and ok("amount", "fifty thousand rupees") and ok("amount", "Rs. 50,000")
    assert ok("agency", "Mumbai Cyber Crime Cell")


async def test_collector_marks_implausible_llm_items_invalid():
    room = CallRoom("e5", NoStt, Store(":memory:"))
    llm = FakeLLM(json.dumps({"entities": [
        {"type": "person_name", "value": "Mr. Ramesh Kumar", "quote": "Mister Ramesh Kumar"},
        {"type": "agency", "value": "Inspector", "quote": "Inspector"},
        {"type": "person_name", "value": "Vikram Rathore", "quote": "I am Vikram Rathore"}]}))
    room.takeover = True
    ev = EvidenceCollector(room, llm, "m", listener_names=("Ramesh Kumar",))
    await ev.process(turn("Am I speaking with Mister Ramesh Kumar? I am Inspector Vikram Rathore."))
    assert [(v["type"], v["value"]) for v in ev.valid_items()] == [("person_name", "Vikram Rathore")]
    await ev.close()
