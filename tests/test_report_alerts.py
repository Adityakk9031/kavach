"""M6 offline: alert policy and formatting, Telegram calls (mock transport), complaint report fields + PDF."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pypdf
import pytest

from app import report
from app.alerts import Alerter, AlertPolicy, CallAlerts, snippet, stage_list
from app.call_room import CallRoom
from app.config import Settings
from app.store import Store
from tests.test_tts_warner import FakeWs, NoStt


# ---- policy / formatting ------------------------------------------------------------------------------------

def test_policy_never_spends_the_takeover_or_call_end_slot_on_anything_else():
    p = AlertPolicy(3)
    assert p.allow("warning"); p.record("warning")
    assert not p.allow("warning")  # one warning alert per call
    assert not p.allow("stage_update", ["S6"])  # takeover + call_end are still owed: no room for updates at cap 3
    assert p.allow("takeover"); p.record("takeover")
    assert p.allow("call_end"); p.record("call_end")
    assert p.sent == 3 and not p.allow("call_end")


def test_policy_one_alert_per_stage_change_when_there_is_room():
    p = AlertPolicy(6)
    assert not p.allow("stage_update", ["S1"])  # not an action stage, nothing new to say
    assert p.allow("stage_update", ["S6"]); p.record("stage_update", ["S6"])
    assert not p.allow("stage_update", ["S6"])  # same stage again: no
    assert p.allow("stage_update", ["S6", "S7"])  # S7 is new
    for kind in ("warning", "takeover", "call_end"):
        assert p.allow(kind); p.record(kind)
    assert not p.allow("takeover")


def test_snippet_is_two_short_lines_at_most():
    long = "word " * 200
    s = snippet(long)
    assert len(s) <= 142 and s.endswith("…")
    assert snippet("  hello   there ") == "hello there"
    assert stage_list(["S6", "S1"]) == "Authority, Payment request" and stage_list([]) == "none yet"


# ---- Telegram ------------------------------------------------------------------------------------------------

def mock_alerter(requests, ok=True):
    def handler(req: httpx.Request):
        requests.append(req)
        body = {"ok": True, "result": {"message_id": 7}} if ok else {"ok": False, "description": "chat not found"}
        return httpx.Response(200, json=body)

    cfg = Settings(_env_file=None, telegram_bot_token="123:abc", telegram_chat_id="999")
    return Alerter(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_send_message_hits_the_bot_api_with_chat_id():
    reqs = []
    a = mock_alerter(reqs)
    await a.send_message("hello")
    r = reqs[0]
    assert str(r.url) == "https://api.telegram.org/bot123:abc/sendMessage"
    assert json.loads(r.content) == {"chat_id": "999", "text": "hello", "disable_web_page_preview": True}
    with pytest.raises(RuntimeError, match="chat not found"):
        await mock_alerter([], ok=False).send_message("x")


async def test_send_message_truncates_to_telegram_limit():
    reqs = []
    await mock_alerter(reqs).send_message("x" * 9000)
    assert len(json.loads(reqs[0].content)["text"]) <= 4000


def make_call_alerts(reqs, mode="live", enabled=True):
    room = CallRoom("a1", NoStt, Store(":memory:"))
    room.mode = mode
    room.store.update_call("a1", caller_number="+91 98765 43210")
    alerter = mock_alerter(reqs)
    alerter.enabled = enabled
    pipeline = SimpleNamespace(on_trigger=[], on_new_stage=[], triggered=True, max_risk=88.0)
    persona = SimpleNamespace(on_takeover_hooks=[])
    ca = CallAlerts(alerter, room, pipeline, persona, 3)
    return room, ca, pipeline, persona


def decision(stages, new=(), risk=87.2):
    return SimpleNamespace(stages_all=list(stages), new_stages=list(new), risk_cum=risk)


async def test_alert_flow_respects_rate_limit_and_message_content():
    reqs = []
    room, ca, pipeline, persona = make_call_alerts(reqs)
    await ca.remember(room, {"channel": "caller", "text": "Transfer the money to the safe account immediately."})
    await pipeline.on_trigger[0](pipeline, decision(["S1", "S2", "S3"]), {})
    await pipeline.on_new_stage[0](pipeline, decision(["S1", "S2", "S3", "S6"], ["S6"]), {})  # no spare slot: suppressed
    await pipeline.on_new_stage[0](pipeline, decision(["S1", "S2", "S3", "S6"], ["S6"]), {})
    await persona.on_takeover_hooks[0](persona)  # takeover: its slot was kept free for it
    await ca.call_ended("call ended", None)
    await ca.drain()
    texts = [json.loads(r.content)["text"] for r in reqs]
    assert len(texts) == 3 and "taken over" in texts[1] and texts[2] == "call ended"
    first = texts[0]
    assert "no warning could be played" in first  # honest: no warner/receiver in this test
    assert "Risk 87/100" in first and "Authority, Threat, Secrecy" in first
    assert "+91 98765 43210" in first and "Transfer the money" in first and "IST" in first
    types = [e["type"] for e in room.store.events("a1")]
    assert types.count("alert_sent") == 3 and "alert_suppressed" in types


async def test_eval_calls_and_unconfigured_telegram_never_send():
    reqs = []
    room, ca, pipeline, _ = make_call_alerts(reqs, mode="eval")
    await pipeline.on_trigger[0](pipeline, decision(["S1"]), {})
    await ca.call_ended("x", None)
    assert reqs == [] and {e["payload"]["reason"] for e in room.store.events("a1") if e["type"] == "alert_skipped"} == {"eval call"}
    room2, ca2, p2, _ = make_call_alerts(reqs, enabled=False)
    await p2.on_trigger[0](p2, decision(["S1"]), {})
    assert reqs == []


async def test_alert_failure_is_logged_not_raised():
    room, ca, pipeline, _ = make_call_alerts([])
    ca.alerter = mock_alerter([], ok=False)
    await pipeline.on_trigger[0](pipeline, decision(["S1"]), {})
    await ca.drain()
    assert any(e["type"] == "alert_failed" for e in room.store.events("a1"))


# ---- report ---------------------------------------------------------------------------------------------------

def seeded_store():
    st = Store(":memory:")
    st.start_call("r1", caller_number="+91 98201 33456")
    t0 = time.time() - 120
    st.update_call("r1", started_at=t0, ended_at=t0 + 95, max_risk=91.5, warned_at=t0 + 40, takeover_at=t0 + 55)
    rows = [("caller", "I am Inspector Vikram Rathore from the Mumbai cyber crime branch."),
            ("receiver", "What is this about?"),
            ("caller", "Pay fifty thousand rupees to pay.now@okbank. IFSC SBIN0001234, account 123456789012. Install AnyDesk."),
            ("persona", "Ah, can you say that slowly please?")]
    for i, (ch, text) in enumerate(rows):
        tid = st.add_turn("r1", ch, i, text, i * 1000, i * 1000 + 800, time.monotonic(), 400, is_decoy=(ch == "persona"))
        st.add_event("r1", "turn_final", float(i), {"turn_id": tid, "channel": ch})
    caller_turn = 3  # row id of the second caller turn
    st._exec("INSERT INTO detections(call_id, turn_id, stages, evidence_quotes, risk_llm, risk_cum, rationale, triggered, llm_ms, model) "
             "VALUES ('r1', 1, '[\"S1\"]', '[\"Inspector Vikram Rathore from the Mumbai cyber crime branch\"]', 40, 28, '', 0, 700, 'q')")
    st._exec("INSERT INTO detections(call_id, turn_id, stages, evidence_quotes, risk_llm, risk_cum, rationale, triggered, llm_ms, model) "
             "VALUES ('r1', 3, '[\"S1\",\"S6\",\"S7\"]', '[\"Pay fifty thousand rupees to pay.now@okbank\"]', 95, 91, '', 1, 700, 'q')")
    for typ, val, valid in [("person_name", "Vikram Rathore", 1), ("agency", "Mumbai cyber crime branch", 1),
                            ("officer_id", "BX 4471", 1), ("amount", "fifty thousand rupees", 1), ("upi_id", "pay.now@okbank", 1),
                            ("bank_account", "123456789012", 1), ("ifsc", "SBIN0001234", 1), ("phone_number", "9820133456", 1),
                            ("url", "www.rbi-verify.in", 1), ("email", "help@rbi-verify.in", 1), ("app_name", "AnyDesk", 1),
                            ("upi_id", "hallucinated@bank", 0)]:
        st._exec("INSERT INTO evidence(call_id, turn_id, type, value, normalized, quote, ts_ms, valid) VALUES ('r1', 3, ?, ?, ?, '', 0, ?)",
                 (typ, val, val.lower(), valid))
    return st


def test_every_report_field_is_filled_from_the_call():
    r = report.build(seeded_store(), "r1")
    assert r.caller_number == "+91 98201 33456" and "IST" in r.incident_time and r.duration == "95 seconds"
    assert r.stages == ["S1", "S6", "S7"] and r.peak_risk == 91.5
    assert r.warned_at and r.takeover_at
    for key, label in report.EVIDENCE_LABELS:
        assert r.evidence.get(key), f"{label} is empty"
    assert "hallucinated@bank" not in r.evidence["upi_id"]  # invalid LLM items never reach the report
    assert len(r.key_quotes) == 2 and r.key_quotes[0]["time"]
    assert [t["who"] for t in r.transcript][-1].startswith("Kavach decoy persona")
    assert r.money_shared is None and r.otp_shared is None and r.missing == []


def test_markdown_and_pdf_contain_the_banner_fields_and_next_steps(tmp_path):
    st = seeded_store()
    st.update_call("r1", money_shared=0, otp_shared=1)
    r, md, pdf = report.generate(st, "r1", str(tmp_path), notes="Caller sounded rehearsed.")
    text = md.read_text()
    for needle in ["DRAFT — review before filing", "+91 98201 33456", "pay.now@okbank", "SBIN0001234", "123456789012",
                   "AnyDesk", "Vikram Rathore", "fifty thousand rupees", "www.rbi-verify.in", "BX 4471",
                   "Money sent:** No", "OTP / PIN / card details shared:** YES", "1930", "cybercrime.gov.in",
                   "Sanchar Saathi", "freeze or dispute", "Caller sounded rehearsed", "decoy persona"]:
        assert needle in text, needle
    pages = pypdf.PdfReader(str(pdf))
    pdf_text = " ".join(p.extract_text() for p in pages.pages)
    for needle in ["DRAFT", "review before filing", "+91 98201 33456", "pay.now@okbank", "SBIN0001234", "AnyDesk",
                   "1930", "cybercrime.gov.in", "Sanchar Saathi", "Vikram Rathore"]:
        assert needle in pdf_text.replace("\n", " "), needle
    assert all("DRAFT" in (p.extract_text() or "") for p in pages.pages)  # banner/footer on every page
    row = st.query("SELECT report_md_path, report_pdf_path FROM calls WHERE id='r1'")[0]
    assert row["report_md_path"] == str(md) and row["report_pdf_path"] == str(pdf)


def test_report_flags_gaps_instead_of_inventing_data():
    st = Store(":memory:")
    st.start_call("r2")
    st.update_call("r2", started_at=time.time() - 30, ended_at=time.time())
    r = report.build(st, "r2")
    assert r.caller_number.startswith("unknown") and len(r.missing) == 2
    md = report.markdown(r)
    assert "none stated" in md and "Not answered yet" in md and "Gaps to fill in" in md


def test_report_drops_detector_quotes_the_caller_never_said():
    st = seeded_store()
    st._exec("INSERT INTO detections(call_id, turn_id, stages, evidence_quotes, risk_llm, risk_cum, rationale, triggered, llm_ms, model) "
             "VALUES ('r1', 3, '[\"S6\"]', '[\"Send me your OTP right now\", \"What is this about?\"]', 90, 90, '', 1, 700, 'q')")
    quotes = [q["quote"] for q in report.build(st, "r1").key_quotes]
    assert "Send me your OTP right now" not in quotes  # paraphrase the model invented
    assert "What is this about?" not in quotes  # a listener line, not the caller's
    assert any(q.startswith("Pay fifty thousand rupees") for q in quotes)


def test_report_drops_quotes_nested_inside_a_longer_quote_from_the_same_turn():
    st = seeded_store()
    st._exec("INSERT INTO detections(call_id, turn_id, stages, evidence_quotes, risk_llm, risk_cum, rationale, triggered, llm_ms, model) "
             "VALUES ('r1', 3, '[\"S6\"]', '[\"Pay fifty thousand rupees to pay.now@okbank\", \"Pay fifty thousand rupees\"]', 90, 90, '', 1, 700, 'q')")
    quotes = [q["quote"] for q in report.build(st, "r1").key_quotes]
    assert "Pay fifty thousand rupees" not in quotes and "Pay fifty thousand rupees to pay.now@okbank" in quotes
