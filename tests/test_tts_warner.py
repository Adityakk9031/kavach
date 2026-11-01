"""M3 offline: TTS session protocol (fake server), cancel tail-dropping, template choice, warner flow."""

import asyncio
import base64
import json
import time
from types import SimpleNamespace

import pytest
import websockets

from app.call_room import SOURCE_WARNING, CallRoom
from app.config import Settings
from app.store import Store
from app.tts import TtsError, TtsSession
from app.warner import PRIORITY, TEMPLATES, CallWarning, Warner, pick_template

CHUNK = base64.b64encode(b"\x01\x00" * 1280).decode()  # 80 ms at 16 kHz


class FakeTtsServer:
    """Speaks the documented frames. Each Flush streams `frames` Audio frames 20 ms apart. A Cancel makes the
    server emit `tail` more Audio frames of the old request before `Cancelled` (as the docs warn)."""

    def __init__(self, frames=20, tail=2, voice_ok=True):
        self.frames, self.tail, self.voice_ok = frames, tail, voice_ok
        self.received: list[dict] = []
        self.flush_id = 0
        self.stream_task = None

    async def handler(self, ws):
        if not self.voice_ok:
            await ws.send(json.dumps({"type": "Error", "error_code": 3012, "error": "voice not found",
                                      "error_type": "voice_not_found"}))
            return
        await ws.send(json.dumps({"type": "Begin", "id": "s1", "expires_at": 0,
                                  "configuration": {"resolved_voice": {"voice_id": "uuid-1"}}}))
        async for raw in ws:
            msg = json.loads(raw)
            self.received.append(msg)
            if msg["type"] == "Flush":
                fid = self.flush_id
                self.flush_id += 1
                self.stream_task = asyncio.create_task(self.stream(ws, fid))
            elif msg["type"] == "Cancel":
                if self.stream_task:
                    self.stream_task.cancel()
                for _ in range(self.tail):
                    await ws.send(json.dumps({"type": "Audio", "audio": CHUNK, "flush_id": self.flush_id - 1}))
                self.flush_id += 1  # ids may skip after a cancel
                await ws.send(json.dumps({"type": "Cancelled", "audio_duration_seconds": 0.1}))
            elif msg["type"] == "Terminate":
                await ws.send(json.dumps({"type": "Termination"}))
                await ws.close()

    async def stream(self, ws, fid):
        for _ in range(self.frames):
            await ws.send(json.dumps({"type": "Audio", "audio": CHUNK, "flush_id": fid}))
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "FlushDone", "flush_id": fid, "audio_duration_ms": self.frames * 80}))


@pytest.fixture
async def server():
    fake = FakeTtsServer(frames=60)
    srv = await websockets.serve(fake.handler, "127.0.0.1", 0)
    fake.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/ws"
    yield fake
    srv.close()
    await srv.wait_closed()


def settings_for(fake):
    return Settings(_env_file=None, tts_ws_url=fake.url, assemblyai_api_key="k", kavach_warning_voice_id="v")


async def test_speak_streams_audio_and_reports_ttfa(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    got = []

    async def on_audio(pcm):
        got.append(pcm)

    req = await s.speak("Papa, stop.", on_audio)
    await asyncio.wait_for(req.done.wait(), 3)
    assert len(got) == 60 and all(len(c) == 2560 for c in got)
    assert req.ttfa_ms is not None and req.ttfa_ms < 500
    assert [m["type"] for m in server.received[:2]] == ["Generate", "Flush"]
    assert s.resolved_voice_id == "uuid-1"
    await s.close()


async def test_cancel_drops_tail_audio_and_next_request_works(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    got = []

    async def on_audio(pcm):
        got.append(pcm)

    req = await s.speak("A long warning.", on_audio)
    while len(got) < 3:
        await asyncio.sleep(0.005)
    sent = await s.cancel()
    assert sent is not None and req.done.is_set()
    n_at_cancel = len(got)
    await asyncio.sleep(0.4)  # the server's tail frames + the rest must NOT be delivered
    assert len(got) <= n_at_cancel + 1  # at most one frame already past the cancel on the wire
    assert server.received[-1]["type"] == "Cancel"

    got2 = []

    async def on_audio2(pcm):
        got2.append(pcm)

    req2 = await s.speak("Second.", on_audio2)
    await asyncio.wait_for(req2.done.wait(), 3)
    assert len(got2) == 60  # new request after Cancelled is delivered in full
    await s.close()


async def test_cancel_with_nothing_in_flight_is_noop(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    assert await s.cancel() is None
    await s.close()


async def test_bad_voice_raises_tts_error():
    fake = FakeTtsServer(voice_ok=False)
    srv = await websockets.serve(fake.handler, "127.0.0.1", 0)
    fake.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/ws"
    s = TtsSession(settings_for(fake), "nope")
    with pytest.raises(TtsError) as e:
        await s.start()
    assert e.value.code == 3012 and e.value.error_type == "voice_not_found"
    srv.close()


def test_templates_pick_most_dangerous_stage_and_use_parent_name():
    stage, text = pick_template(["S1", "S2", "S6"], "Papa")
    assert stage == "S6" and text.startswith("Papa, stop") and "money" in text
    assert pick_template(["S1", "S7", "S5"], "Maa")[0] == "S7"
    assert pick_template(["S4"], "Papa")[0] == "default"
    for stage, text in TEMPLATES.items():
        body = text.format(p="Papa")
        assert body.count(".") + body.count("…") >= 3, stage
        assert not any(ch.isdigit() for ch in body), f"{stage}: write numbers as words"
        assert "[" not in body and "<" not in body  # brackets would be read aloud
    assert set(PRIORITY) - {"S4"} == set(TEMPLATES) - {"default"}


class FakeWs:
    def __init__(self):
        self.binary, self.text = [], []

    async def send_bytes(self, d):
        self.binary.append(d)

    async def send_text(self, d):
        self.text.append(json.loads(d))


class NoStt:
    model = None

    def __init__(self, ch, cb):
        pass

    async def start(self):
        pass

    async def send_audio(self, p):
        pass

    async def close(self):
        pass


class FakePool:
    def __init__(self, session):
        self.session = session

    async def get(self, voice, label="x"):
        return self.session


async def test_warner_sends_audio_to_receiver_only_and_barge_in_flushes(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    cfg = settings_for(server)
    warner = Warner(cfg, FakePool(s))
    room = CallRoom("w1", NoStt, Store(":memory:"))
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    w = CallWarning(warner, room)
    room.warning = w
    room.control_handlers["barge_in"] = w.on_browser_barge_in

    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while len(receiver.binary) < 3:
        await asyncio.sleep(0.01)
    assert caller.binary == []  # the scammer never hears the warning
    assert all(b[0] == SOURCE_WARNING for b in receiver.binary)

    await asyncio.sleep(Warner.ECHO_GUARD_S)  # past the echo guard
    await room.control_handlers["barge_in"](room, "receiver", {})
    await asyncio.wait_for(task, 3)
    n = len(receiver.binary)
    await asyncio.sleep(0.3)
    assert len(receiver.binary) == n  # nothing more after the cancel
    flush = [e for e in receiver.text if e["type"] == "flush_playback"]
    assert flush and flush[0]["source"] == SOURCE_WARNING
    types = [e["type"] for e in room.store.events("w1")]
    assert "warn_first_audio" in types and "barge_in" in types
    await s.close()


async def test_barge_in_inside_echo_guard_is_ignored(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    room = CallRoom("w2", NoStt, Store(":memory:"))
    await room.join("receiver", FakeWs())
    w = CallWarning(Warner(settings_for(server), FakePool(s)), room)
    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while w.first_audio_at is None:  # the guard protects against the warning leaking into the mic: audio must be playing
        await asyncio.sleep(0.005)
    await w.barge_in("browser_vad")  # immediately after audio started: likely the warning leaking into the mic
    assert any(e["type"] == "barge_in_ignored" for e in room.store.events("w2"))
    assert w.interrupted is False and w.active  # the warning was not cut off
    await asyncio.sleep(Warner.ECHO_GUARD_S)
    await w.barge_in("browser_vad")  # a real interruption after the guard window ends it
    await asyncio.wait_for(task, 3)
    await s.close()


async def test_barge_in_after_delivery_but_during_playback_still_flushes(server):
    """The server delivers audio far faster than real time; the warning is still audible after delivery ends."""
    s = TtsSession(settings_for(server), "v")
    await s.start()
    room = CallRoom("w3", NoStt, Store(":memory:"))
    receiver = FakeWs()
    await room.join("receiver", receiver)
    w = CallWarning(Warner(settings_for(server), FakePool(s)), room)
    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while not (w.request and w.request.done.is_set()):  # wait until the TTS server finished delivering (~1.2 s)
        await asyncio.sleep(0.02)
    assert w.delivering is False and w.active is True  # delivered, but 4.8 s of audio is still playing
    await w.barge_in("stt_speech_started")
    await asyncio.wait_for(task, 2)  # speak() ends early instead of waiting out the playback
    flush = [e for e in receiver.text if e["type"] == "flush_playback"]
    assert flush and flush[0]["source"] == SOURCE_WARNING
    ev = [e for e in room.store.events("w3") if e["type"] == "barge_in"]
    assert ev and ev[0]["payload"]["tts_still_generating"] is False
    assert w.active is False
    states = [e.get("state") for e in receiver.text if e["type"] == "warning"]
    assert states[-1] == "interrupted"
    await s.close()


async def _rearm_setup(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    room = CallRoom("rw", NoStt, Store(":memory:"))
    receiver = FakeWs()
    await room.join("receiver", receiver)
    w = CallWarning(Warner(settings_for(server), FakePool(s)), room)
    room.on_final_hooks.append(w.on_receiver_final)
    return s, room, receiver, w


def _final(i, ch="receiver"):
    return {"channel": ch, "text": "yes?", "idx": i, "turn_id": i + 1, "audio_end_ms": 1000}


async def test_warning_cut_off_before_it_was_heard_is_repeated_when_the_person_stops_talking(server):
    s, room, receiver, w = await _rearm_setup(server)
    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while w.first_audio_at is None:
        await asyncio.sleep(0.01)
    await asyncio.sleep(Warner.ECHO_GUARD_S)
    await w.barge_in("stt_speech_started")  # the person replied to the scammer: <3 s of the warning was heard
    await asyncio.wait_for(task, 3)
    assert w.rearm is not None and w.count == 1
    n_before = len(receiver.binary)
    await w.on_receiver_final(room, _final(1))  # they finished their sentence
    for _ in range(900):  # generous: this waits out the re-arm delay plus a full fake warning
        if w.count == 2 and w.request is not None and w.request.done.is_set():
            break
        await asyncio.sleep(0.01)
    assert w.count == 2 and len(receiver.binary) > n_before  # said again, audio delivered
    assert [e["type"] for e in room.store.events("rw")].count("warn_tts_sent") == 2
    assert any(e["type"] == "warn_rearmed" for e in room.store.events("rw"))
    await w.barge_in("browser_vad")
    await s.close()


async def test_warning_that_was_mostly_heard_is_not_repeated(server):
    s, room, receiver, w = await _rearm_setup(server)
    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while w.first_audio_at is None:
        await asyncio.sleep(0.01)
    w.first_audio_at -= 4.0  # pretend 4 s of it already played
    await asyncio.sleep(Warner.ECHO_GUARD_S)
    await w.barge_in("browser_vad")
    await asyncio.wait_for(task, 3)
    assert w.rearm is None
    await w.on_receiver_final(room, _final(1))
    await asyncio.sleep(1.2)
    assert w.count == 1
    await s.close()


async def test_rearm_is_capped_ignores_takeover_and_caller_turns(server):
    s, room, receiver, w = await _rearm_setup(server)
    w.count = Warner.MAX_WARNINGS  # already warned the maximum number of times
    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while w.first_audio_at is None:
        await asyncio.sleep(0.01)
    await asyncio.sleep(Warner.ECHO_GUARD_S)
    await w.barge_in("browser_vad")
    await asyncio.wait_for(task, 3)
    assert w.rearm is None  # capped
    w.rearm = ("S2", "x")
    await w.on_receiver_final(room, _final(2, ch="caller"))  # a caller turn never re-arms
    assert w.rearm is not None
    room.takeover = True  # the persona is in charge now
    await w.on_receiver_final(room, _final(3))
    await asyncio.sleep(1.2)
    assert w.count == Warner.MAX_WARNINGS + 1  # only the one warning this test spoke: no re-arm during takeover
    await s.close()


async def test_no_warning_is_spoken_over_the_persona_and_warned_at_means_audio_started(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    room = CallRoom("wt", NoStt, Store(":memory:"))
    receiver = FakeWs()
    await room.join("receiver", receiver)
    w = CallWarning(Warner(settings_for(server), FakePool(s)), room)
    room.takeover = True
    await w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None)
    assert receiver.binary == [] and any(e["type"] == "warn_skipped" for e in room.store.events("wt"))
    assert room.store.query("SELECT warned_at FROM calls WHERE id='wt'")[0]["warned_at"] is None  # nothing was played
    room.takeover = False
    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while w.first_audio_at is None:
        await asyncio.sleep(0.01)
    assert room.store.query("SELECT warned_at FROM calls WHERE id='wt'")[0]["warned_at"] is not None
    await asyncio.sleep(Warner.ECHO_GUARD_S)
    await w.barge_in("takeover")
    await asyncio.wait_for(task, 3)
    await s.close()


async def test_speech_before_any_warning_audio_cancels_it_and_a_takeover_click_always_does(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    room = CallRoom("wc", NoStt, Store(":memory:"))
    await room.join("receiver", FakeWs())
    w = CallWarning(Warner(settings_for(server), FakePool(s)), room)
    w.session, w.started_at, w.count = s, time.monotonic(), 1
    w.request = SimpleNamespace(done=asyncio.Event())  # generating, nothing played yet
    await w.barge_in("stt_speech_started")  # no audio yet: nothing can have leaked, so the person's reply counts
    assert w.interrupted
    w.interrupted, w.first_audio_at = False, time.monotonic()  # audio just started: echo guard applies...
    await w.barge_in("browser_vad")
    assert not w.interrupted
    await w.barge_in("takeover")  # ...but a deliberate hand-over is never an echo
    assert w.interrupted
    await s.close()


async def test_warning_is_not_spoken_after_the_call_ended_and_close_cancels_generation(server):
    s = TtsSession(settings_for(server), "v")
    await s.start()
    room = CallRoom("we", NoStt, Store(":memory:"))
    receiver = FakeWs()
    await room.join("receiver", receiver)
    w = CallWarning(Warner(settings_for(server), FakePool(s)), room)
    room.ended = True
    await w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None)
    assert receiver.binary == []
    room.ended = False
    task = asyncio.create_task(w.speak("Papa, stop.", "S2", trigger_at=0.0, turn_end_at=None))
    while w.first_audio_at is None:
        await asyncio.sleep(0.01)
    room.ended = True
    await w.close()
    await asyncio.wait_for(task, 3)
    n = len(receiver.binary)
    await asyncio.sleep(0.3)
    assert len(receiver.binary) == n  # nothing more reaches the receiver once the call is over
    await s.close()
