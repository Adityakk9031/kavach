"""The Twilio demo call: it rings only the owner's number, listens to their voice, and answers in character."""

import asyncio
import base64
import json
import math
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from app.config import Settings
from app.twilio_call import FRAME, OPENING, TwilioDesk, TwilioError, mulaw8k_to_pcm16k, pcm16k_to_mulaw8k


def tone(seconds=1.0, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    return (9000 * np.sin(2 * math.pi * 300 * t)).astype("int16").tobytes()


def settings(**kw):
    base = dict(_env_file=None, twilio_account_sid="ACtest", twilio_auth_token="tok", twilio_from_number="+15550001111",
                twilio_target_number="+919800000000", scammer_voice_id="aai-michael")
    base.update(kw)
    return Settings(**base)


def test_audio_converts_between_twilio_and_speech_formats():
    mu, _ = pcm16k_to_mulaw8k(tone(1.0))
    assert len(mu) == 8000  # one second at 8 kHz, one byte per sample
    pcm, _ = mulaw8k_to_pcm16k(mu)
    assert abs(len(pcm) - 32000) < 400
    assert np.abs(np.frombuffer(pcm, dtype="int16")).max() > 6000  # the sound survived the round trip


# ---- placing the call -------------------------------------------------------------------------------------------

def desk_with_http(handler, **kw):
    return TwilioDesk(settings(**kw), None, None, None, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_the_call_goes_only_to_the_configured_number_with_a_stream_back_to_us():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        seen["form"] = dict(x.split("=", 1) for x in req.content.decode().split("&"))
        return httpx.Response(201, json={"sid": "CA123"})

    desk = desk_with_http(handler)
    out = await desk.start_call("https://kavach.example.com")
    assert out == {"call_sid": "CA123", "to": "+919800000000"}
    assert seen["url"].endswith("/Accounts/ACtest/Calls.json") and seen["auth"].startswith("Basic ")
    assert seen["form"]["To"] == "%2B919800000000" and seen["form"]["From"] == "%2B15550001111"
    decoded = req_decode(seen["form"]["Twiml"])
    token = decoded.split("/twilio/stream/")[1].split('"')[0]
    assert 'wss://kavach.example.com/twilio/stream/' in decoded and "<Hangup/>" in decoded
    assert desk.accept_token(token) is True and desk.accept_token(token) is False  # one use only


def req_decode(s: str) -> str:
    from urllib.parse import unquote_plus
    return unquote_plus(s)


async def test_the_call_is_refused_when_not_set_up_busy_insecure_or_rejected_by_twilio():
    ok = lambda r: httpx.Response(201, json={"sid": "CA1"})  # noqa: E731
    with pytest.raises(TwilioError, match="not set up"):
        await desk_with_http(ok, twilio_target_number="").start_call("https://x.example.com")
    with pytest.raises(TwilioError, match="https"):
        await desk_with_http(ok).start_call("http://x.example.com")
    busy = desk_with_http(ok)
    busy.active = object()
    with pytest.raises(TwilioError, match="already in progress"):
        await busy.start_call("https://x.example.com")
    bad = desk_with_http(lambda r: httpx.Response(400, json={"message": "The number is unverified"}))
    with pytest.raises(TwilioError, match="unverified"):
        await bad.start_call("https://x.example.com")
    assert bad.pending == {}  # a failed call leaves no usable token behind


# ---- the conversation ------------------------------------------------------------------------------------------

class FakeWs:
    def __init__(self):
        self.incoming, self.sent, self.accepted, self.closed = asyncio.Queue(), [], False, None

    async def accept(self): self.accepted = True
    async def receive_text(self): return await self.incoming.get()
    async def send_text(self, t): self.sent.append(json.loads(t))
    async def close(self, code=1000): self.closed = code

    def feed(self, obj): self.incoming.put_nowait(json.dumps(obj))
    def kinds(self): return [m["event"] for m in self.sent]


class FakeStt:
    def __init__(self, on_event): self.on_event, self.audio = on_event, bytearray()
    async def start(self): pass
    async def send_audio(self, pcm): self.audio += pcm
    async def close(self): pass


class FakeTts:
    def __init__(self): self.spoken, self.cancels = [], 0

    async def speak(self, text, on_audio):
        self.spoken.append(text)
        req = SimpleNamespace(done=asyncio.Event())
        await on_audio(tone(0.4))
        req.done.set()
        return req

    async def cancel(self): self.cancels += 1


class FakeLlm:
    def __init__(self): self.calls = []

    async def chat(self, model, messages, **kw):
        self.calls.append(messages)
        return "You must pay the deposit, sir, within one hour.", 5


def build():
    llm, tts, stts = FakeLlm(), FakeTts(), []
    pool = SimpleNamespace(get=lambda voice, label="": _async(tts))

    def stt_factory(channel, on_event):
        stts.append(FakeStt(on_event))
        return stts[-1]

    desk = TwilioDesk(settings(), llm, pool, stt_factory, httpx.AsyncClient())
    desk.pending["tok1"] = __import__("time").monotonic()
    return desk, llm, tts, stts


async def _async(v): return v


async def settle(n=40):
    for _ in range(n):
        await asyncio.sleep(0.02)


async def test_it_opens_listens_answers_what_you_said_and_stops_when_you_talk_over_it():
    desk, llm, tts, stts = build()
    ws = FakeWs()
    runner = asyncio.create_task(desk.run(ws, "tok1"))
    await settle(5)
    assert ws.accepted and desk.active is not None
    ws.feed({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}})
    await settle()
    assert tts.spoken == [OPENING]  # it speaks first, like a real scam call
    media = [m for m in ws.sent if m["event"] == "media"]
    assert media and all(m["streamSid"] == "MZ1" for m in media)
    assert all(len(base64.b64decode(m["media"]["payload"])) == FRAME for m in media)  # 20 ms frames

    mu, _ = pcm16k_to_mulaw8k(tone(0.5))
    ws.feed({"event": "media", "media": {"track": "inbound", "payload": base64.b64encode(mu).decode()}})
    await settle(5)
    assert len(stts[0].audio) > 12000  # your voice reached speech recognition at 16 kHz

    n_before = len(media)
    await stts[0].on_event({"type": "final", "text": "Who is this? I am scared."})
    await settle(60)
    assert llm.calls and llm.calls[-1][-1] == {"role": "user", "content": "Who is this? I am scared."}
    assert tts.spoken[-1].startswith("You must pay the deposit")
    assert len([m for m in ws.sent if m["event"] == "media"]) > n_before

    desk.active.speaking = True  # it is mid-sentence when you interrupt
    desk.active.request = SimpleNamespace(done=asyncio.Event())
    await stts[0].on_event({"type": "speech_started", "audio_ms": 1})
    await settle(5)
    assert {"event": "clear", "streamSid": "MZ1"} in ws.sent and tts.cancels >= 1

    ws.feed({"event": "stop"})
    await asyncio.wait_for(runner, 3)
    assert desk.active is None
    assert [t["who"] for t in desk.last["transcript"]] == ["scammer", "you", "scammer"]


async def test_a_wrong_or_reused_token_and_a_second_call_are_turned_away():
    desk, *_ = build()
    ws = FakeWs()
    await desk.run(ws, "not-the-token")
    assert ws.closed == 4401 and not ws.accepted
    first = FakeWs()
    t = asyncio.create_task(desk.run(first, "tok1"))
    await settle(5)
    desk.pending["tok2"] = __import__("time").monotonic()
    second = FakeWs()
    await desk.run(second, "tok2")
    assert second.closed == 4401  # only one demo call at a time
    first.feed({"event": "stop"})
    await asyncio.wait_for(t, 3)
