"""M1: relay + per-channel STT taps, with a fake STT so no network is needed."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.call_room import SOURCE_PEER, AudioClock, CallRoom
from app.store import Store
from app.stt import build_url, normalize
from app.config import Settings


class FakeWs:
    def __init__(self):
        self.binary: list[bytes] = []
        self.text: list[dict] = []

    async def send_bytes(self, data: bytes) -> None:
        self.binary.append(data)

    async def send_text(self, data: str) -> None:
        self.text.append(json.loads(data))


class FakeStt:
    instances: dict[str, "FakeStt"] = {}

    def __init__(self, channel, on_event):
        self.channel, self.on_event = channel, on_event
        self.audio = bytearray()
        self.closed = False
        self.model = "fake"
        FakeStt.instances[channel] = self

    async def start(self):
        await self.on_event({"type": "begin", "model": "fake", "session_id": f"s-{self.channel}"})

    async def send_audio(self, pcm):
        self.audio += pcm

    async def close(self):
        self.closed = True


@pytest.fixture
def room():
    FakeStt.instances.clear()
    return CallRoom("t1", FakeStt, Store(":memory:"))


def chunk(ms=50, value=1):
    return (value).to_bytes(2, "little", signed=True) * (16 * ms)


async def test_audio_relayed_to_other_party_and_tapped_per_channel(room):
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)

    await room.on_audio("caller", chunk(value=7))
    await room.on_audio("receiver", chunk(value=9))

    assert receiver.binary[-1][0] == SOURCE_PEER and receiver.binary[-1][1:] == chunk(value=7)
    assert caller.binary[-1][0] == SOURCE_PEER and caller.binary[-1][1:] == chunk(value=9)
    # Each channel's STT hears only its own party: speaker identity comes from the channel.
    assert bytes(FakeStt.instances["caller"].audio) == chunk(value=7)
    assert bytes(FakeStt.instances["receiver"].audio) == chunk(value=9)


async def test_takeover_mutes_receiver_to_caller_but_keeps_stt_tap(room):
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    room.takeover = True

    await room.on_audio("receiver", chunk())
    assert caller.binary == []
    assert len(FakeStt.instances["receiver"].audio) == len(chunk())
    # Caller audio still reaches the receiver so they can monitor the call.
    await room.on_audio("caller", chunk())
    assert len(receiver.binary) == 1


async def test_final_turn_broadcast_with_stt_latency_and_stored(room):
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    for _ in range(20):  # 1 s of caller audio
        await room.on_audio("caller", chunk())
    seen = []

    async def hook(r, turn):
        seen.append(turn)

    room.on_final_hooks.append(hook)
    await FakeStt.instances["caller"].on_event(
        {"type": "final", "text": "This is CBI calling.", "turn_order": 0, "audio_start_ms": 100, "audio_end_ms": 900}
    )

    finals = [e for e in receiver.text if e["type"] == "transcript" and e["final"]]
    assert finals and finals[0]["channel"] == "caller" and finals[0]["text"] == "This is CBI calling."
    assert finals[0]["stt_latency_ms"] is not None and finals[0]["stt_latency_ms"] >= 0
    assert seen and seen[0]["idx"] == 0
    turns = room.store.turns("t1")
    assert turns[0]["channel"] == "caller" and turns[0]["audio_end_ms"] == 900
    types = [e["type"] for e in room.store.events("t1")]
    assert "stt_begin" in types and "turn_final" in types


async def test_empty_final_ignored_and_partial_not_stored(room):
    ws = FakeWs()
    await room.join("caller", ws)
    stt = FakeStt.instances["caller"]
    await stt.on_event({"type": "partial", "text": "this is", "turn_order": 0, "audio_start_ms": 0, "audio_end_ms": 10})
    await stt.on_event({"type": "final", "text": "  ", "turn_order": 0, "audio_start_ms": None, "audio_end_ms": None})
    assert room.store.turns("t1") == []
    assert any(e["type"] == "transcript" and not e["final"] for e in ws.text)


async def test_end_closes_stt_sessions(room):
    await room.join("caller", FakeWs())
    await room.join("receiver", FakeWs())
    await room.end()
    assert FakeStt.instances["caller"].closed and FakeStt.instances["receiver"].closed
    assert room.store.query("SELECT ended_at FROM calls WHERE id='t1'")[0]["ended_at"] is not None


def test_audio_clock_maps_audio_time_to_send_time():
    clock = AudioClock(16000)
    clock.add(1600, at=10.0)  # 0-50 ms
    clock.add(1600, at=10.5)  # 50-100 ms
    assert clock.time_at(30) == 10.0
    assert clock.time_at(50) == 10.0
    assert clock.time_at(51) == 10.5
    assert clock.time_at(101) is None
    assert clock.audio_ms == 100


def test_stt_url_and_message_normalization():
    s = Settings(_env_file=None, stt_model="universal-3-6-pro")
    url = build_url(s)
    assert "speech_model=universal-3-6-pro" in url and "language_codes=%5B%22en%22%5D" in url
    assert "language_codes" not in build_url(Settings(_env_file=None, stt_model="universal-streaming-english"))

    turn = {"type": "Turn", "end_of_turn": True, "transcript": "Hi.", "turn_order": 2,
            "words": [{"start": 10, "end": 20, "text": "Hi."}]}
    assert normalize(turn) == {"type": "final", "text": "Hi.", "turn_order": 2, "audio_start_ms": 10, "audio_end_ms": 20}
    assert normalize({"type": "SpeechStarted", "timestamp": 5}) == {"type": "speech_started", "audio_ms": 5}
    assert normalize({"type": "Begin", "id": "x", "configuration": {"model": "m"}})["model"] == "m"
    assert normalize({"type": "Termination"}) is None


def test_websocket_endpoints_relay_between_two_tabs(monkeypatch):
    import uuid

    import app.main as main

    call_id = f"wsrelay-{uuid.uuid4().hex[:8]}"  # a used call id is refused, and the DB persists across runs
    monkeypatch.setattr(main.rooms, "stt_factory", FakeStt)
    # Entering the client shares one event loop between both sockets, as uvicorn does.
    with TestClient(main.app) as client, \
         client.websocket_connect(f"/ws/call/{call_id}/caller?caller_number=%2B911234") as caller, \
         client.websocket_connect(f"/ws/call/{call_id}/receiver") as receiver:
        caller.send_bytes(chunk(value=3))
        while True:  # skip JSON status events until the audio frame arrives
            msg = receiver.receive()
            if msg.get("bytes"):
                assert msg["bytes"] == bytes([SOURCE_PEER]) + chunk(value=3)
                break
        caller.send_text(json.dumps({"type": "end_call"}))
        deadline = time.time() + 2
        while time.time() < deadline:
            msg = receiver.receive()
            if msg.get("text") and json.loads(msg["text"])["type"] == "call_ended":
                break
        else:
            pytest.fail("no call_ended event")
    row = main.store.query("SELECT caller_number FROM calls WHERE id=?", (call_id,))[0]
    assert row["caller_number"] == "+911234"


async def test_unexpected_stt_close_is_logged_and_restarted(room):
    await room.join("caller", FakeWs())
    first = FakeStt.instances["caller"]
    await first.on_event({"type": "closed", "code": 1008, "reason": "limit", "clean": False})
    assert FakeStt.instances["caller"] is not first  # a fresh session replaced it
    types = [e["type"] for e in room.store.events("t1")]
    assert "stt_closed" in types and "stt_restarted" in types


async def test_clean_close_and_leave_do_not_restart(room):
    await room.join("caller", FakeWs())
    first = FakeStt.instances["caller"]
    await first.on_event({"type": "closed", "code": 1000, "reason": "", "clean": True})
    assert FakeStt.instances["caller"] is first
    await room.leave("caller")
    await first.on_event({"type": "closed", "code": 1006, "reason": "", "clean": False})
    assert "caller" not in room.stt


async def test_restart_limit(room):
    await room.join("caller", FakeWs())
    for _ in range(5):
        await FakeStt.instances["caller"].on_event({"type": "closed", "code": 1006, "reason": "", "clean": False})
    restarted = [e for e in room.store.events("t1") if e["type"] == "stt_restarted"]
    assert len(restarted) == CallRoom.MAX_STT_RESTARTS


def test_ended_call_id_cannot_be_reused_and_a_viewer_does_not_create_a_call(monkeypatch):
    import uuid

    import app.main as main

    cid = f"reuse-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(main.rooms, "stt_factory", FakeStt)
    with TestClient(main.app) as client:
        with client.websocket_connect(f"/ws/call/{cid}/caller") as caller:
            caller.send_text(json.dumps({"type": "end_call"}))
            while True:  # wait until the server has finished ending the call
                msg = caller.receive()
                if msg.get("text") and json.loads(msg["text"])["type"] == "call_ended":
                    break
        assert main.store.query("SELECT 1 FROM calls WHERE id=? AND ended_at IS NOT NULL", (cid,))
        with client.websocket_connect(f"/ws/call/{cid}/receiver") as again:
            msg = again.receive()
            assert msg["type"] == "websocket.close" and msg["code"] == 4409  # refused: the call already ended
        with client.websocket_connect(f"/ws/events/never-started-{cid}") as viewer:
            pass
        assert not main.store.query("SELECT 1 FROM calls WHERE id=?", (f"never-started-{cid}",))


async def test_the_caller_side_never_learns_what_kavach_is_doing(room):
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    for ev in ({"type": "warning", "state": "speaking", "text": "Papa, stop"}, {"type": "takeover", "state": "on"},
               {"type": "persona", "state": "speaking", "text": "Ah, hello", "decoy": True},
               {"type": "detection", "risk_cum": 91}, {"type": "evidence", "items": [{"type": "upi_id"}]},
               {"type": "speech_started", "channel": "receiver"},
               {"type": "transcript", "channel": "receiver", "text": "my pin is secret", "final": True},
               {"type": "transcript", "channel": "caller", "text": "pay now", "final": True}, {"type": "call_ended"}):
        await room.broadcast(ev)
    seen = [e["type"] + ":" + e.get("channel", "") for e in caller.text if e["type"] not in ("presence", "stt_status")]
    assert seen == ["transcript:caller", "call_ended:"]  # its own words and the end of the call, nothing else
    assert {"warning", "takeover", "persona", "detection", "evidence"} <= {e["type"] for e in receiver.text}


async def test_ending_a_call_announces_it_first_and_blocks_id_reuse_before_the_slow_work(room):
    receiver = FakeWs()
    await room.join("receiver", receiver)
    order = []

    async def slow_finalize():
        order.append(("finalize_started", room.store.query("SELECT ended_at FROM calls WHERE id='t1'")[0]["ended_at"] is not None,
                      [e["type"] for e in receiver.text if e["type"] in ("call_ended", "report_ready")]))
        return {"report": {"md": "/m", "pdf": "/p"}}

    room.finalize_hooks.append(slow_finalize)
    await room.end()
    assert order == [("finalize_started", True, ["call_ended"])]  # ended_at written and UIs told BEFORE finalizing
    assert [e["type"] for e in receiver.text if e["type"] in ("call_ended", "report_ready")] == ["call_ended", "report_ready"]


async def test_no_audio_flows_after_the_call_has_ended(room):
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    await room.end()
    await room.on_audio("caller", chunk())
    await room.send_audio("receiver", 1, chunk())
    assert receiver.binary == [] and caller.binary == []
    assert FakeStt.instances["caller"].audio == bytearray()  # and the STT tap is closed too


async def test_stt_restart_offset_is_set_when_the_new_session_takes_its_first_byte_and_reset_on_rejoin(room):
    await room.join("caller", FakeWs())
    for _ in range(10):  # 500 ms of audio before the drop
        await room.on_audio("caller", chunk())
    await FakeStt.instances["caller"].on_event({"type": "closed", "code": 1006, "reason": "", "clean": False})
    new = FakeStt.instances["caller"]
    new.accepting = False  # still connecting: audio must not move the offset yet
    await room.on_audio("caller", chunk())
    assert "caller" not in room.stt_offset_ms
    new.accepting = True
    await room.on_audio("caller", chunk())  # first byte the new session receives: 11 chunks (550 ms) came before it
    assert room.stt_offset_ms["caller"] == pytest.approx(550)
    seen = []

    async def hook(r, t):
        seen.append(t)

    room.on_final_hooks.append(hook)
    await new.on_event({"type": "final", "text": "hello there", "turn_order": 0, "audio_start_ms": 100, "audio_end_ms": 900})
    assert room.store.turns("t1")[0]["audio_end_ms"] == 1450  # 900 on the new session = 1450 on the channel clock
    await room.join("caller", FakeWs())  # the tab reloads: new clock, so the old offset must go
    assert "caller" not in room.stt_offset_ms and "caller" not in room.stt_restarts
