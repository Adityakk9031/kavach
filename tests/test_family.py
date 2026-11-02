"""The son's side: a Telegram voice note plays on Papa's phone (even after the call was cut); End-the-call button."""

import io
import json
import math
import time
from types import SimpleNamespace

import av
import numpy as np
import pytest

from app.alerts import Alerter, CallAlerts, control_keyboard
from app.call_room import SOURCE_FAMILY, CallRoom, RoomRegistry
from app.config import Settings
from app.family import FamilyDesk, decode_voice_note
from app.store import Store
from tests.test_call_room import FakeStt, FakeWs, chunk
from tests.test_tts_warner import NoStt
import httpx


def voice_note(seconds: float = 1.5, hz: int = 440) -> bytes:
    """A real OGG/Opus file, the format Telegram voice notes use."""
    rate, size = 48000, 960
    n = int(rate * seconds) // size * size
    samples = (9000 * np.sin(2 * math.pi * hz * np.arange(n) / rate)).astype("int16")
    buf = io.BytesIO()
    out = av.open(buf, "w", format="ogg")
    st = out.add_stream("libopus", rate=rate)
    st.layout = "mono"
    for i in range(0, n, size):
        f = av.AudioFrame.from_ndarray(samples[i:i + size].reshape(1, -1), format="s16", layout="mono")
        f.sample_rate = rate
        for p in st.encode(f):
            out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


# ---- decoding ---------------------------------------------------------------------------------------------------

def test_a_real_opus_voice_note_decodes_to_the_right_length_at_16k_mono():
    pcm = decode_voice_note(voice_note(1.5))
    assert len(pcm) % 2 == 0
    assert 1.4 <= len(pcm) / 2 / 16000 <= 1.7  # 1.5 s in, about 1.5 s out (Opus adds a few ms of padding)
    assert np.abs(np.frombuffer(pcm, dtype="int16")).max() > 3000  # it carries sound, not silence


def test_things_that_are_not_playable_are_refused_with_a_reason():
    with pytest.raises(ValueError, match="not a playable"):
        decode_voice_note(b"this is not audio at all")
    with pytest.raises(ValueError, match="longer than 1 seconds"):
        decode_voice_note(voice_note(3.0), max_seconds=1)
    with pytest.raises(ValueError, match="too short"):
        decode_voice_note(voice_note(0.1))


# ---- playing it in Papa's phone ------------------------------------------------------------------------------

@pytest.fixture
def room():
    FakeStt.instances.clear()
    return CallRoom("f1", FakeStt, Store(":memory:"))


async def test_a_family_voice_note_goes_to_papas_phone_only_even_after_the_call_ended(room):
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    await room.end()  # the son cut the call
    caller.binary.clear(), caller.text.clear()
    receiver.binary.clear(), receiver.text.clear()
    pcm = chunk(ms=2500)  # 2.5 s
    assert await room.play_family(pcm) is True
    assert len(receiver.binary) == 3 and all(b[0] == SOURCE_FAMILY for b in receiver.binary)  # one frame per second
    assert b"".join(b[1:] for b in receiver.binary) == pcm
    assert [e["type"] for e in receiver.text] == ["family"] and receiver.text[0]["seconds"] == 2.5
    assert caller.binary == [] and caller.text == []  # the scammer learns nothing and hears nothing
    assert any(e["type"] == "family_voice" and e["payload"]["call_ended"] for e in room.store.events("f1"))


async def test_persons_microphone_stays_off_the_caller_while_the_voice_note_plays_then_returns(room):
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    await room.play_family(chunk(ms=1000))
    await room.on_audio("receiver", chunk())
    assert [b for b in caller.binary] == []  # muted toward the scammer
    assert bytes(FakeStt.instances["receiver"].audio) == chunk()  # but still transcribed
    room.family_until = time.monotonic() - 1  # the voice note has finished
    await room.on_audio("receiver", chunk())
    assert len(caller.binary) == 1


async def test_no_app_connected_means_nothing_is_played(room):
    await room.join("caller", FakeWs())
    assert await room.play_family(chunk(ms=1000)) is False


def test_family_target_prefers_a_running_call_then_a_recently_ended_one_with_the_app_still_connected():
    reg = RoomRegistry(NoStt, Store(":memory:"), 16000)
    now = time.time()

    def mk(cid, parties, ended=False, started=0.0, ended_ago=None):
        r = SimpleNamespace(parties=parties, ended=ended, started_wall=now - started,
                            ended_wall=None if ended_ago is None else now - ended_ago)
        reg.rooms[cid] = r
        return r

    assert reg.family_target() is None
    mk("ended-long-ago", {"receiver": 1}, ended=True, started=5000, ended_ago=2000)
    assert reg.family_target() is None  # past the 15 minute grace
    recent = mk("just-cut", {"receiver": 1}, ended=True, started=300, ended_ago=20)
    mk("no-app", {"caller": 1}, started=10)  # nobody on the person's side
    assert reg.family_target() is recent  # the call that was just cut, so the son can speak to Papa
    running = mk("running", {"receiver": 1, "caller": 1}, started=60)
    assert reg.family_target() is running  # a live call wins over a finished one


# ---- Telegram: voice notes and the End button ----------------------------------------------------------------

class FakeAlerter:
    def __init__(self, audio: bytes = b""):
        self.audio, self.said, self.answers, self.downloads = audio, [], [], []

    async def send_message(self, text, reply_markup=None):
        self.said.append(text)

    async def answer_callback(self, cid, text):
        self.answers.append(text)

    async def download_file(self, file_id):
        self.downloads.append(file_id)
        return self.audio


class FakeRoom:
    def __init__(self, delivered=True, warning_active=False):
        self.played, self.ended, self.delivered, self.events = [], False, delivered, []
        self.barged = []
        self.warning = SimpleNamespace(active=warning_active, barge_in=self._barge)

    async def _barge(self, source):
        self.barged.append(source)

    async def play_family(self, pcm):
        self.played.append(pcm)
        return self.delivered

    def log_event(self, *a, **k):
        self.events.append(a)

    async def end(self):
        self.ended = True


def desk_for(room, audio=b"", chat="999"):
    st = Store(":memory:")
    reg = SimpleNamespace(rooms={"live1": room} if room else {}, family_target=lambda: room)
    cfg = Settings(_env_file=None, telegram_chat_id=chat)
    alerter = FakeAlerter(audio)
    return FamilyDesk(alerter, st, reg, cfg), alerter, st


def voice_update(chat=999, duration=2):
    return {"update_id": 1, "message": {"chat": {"id": chat}, "voice": {"file_id": "AgADxyz", "duration": duration}}}


async def test_the_sons_voice_note_is_downloaded_decoded_played_and_confirmed():
    room = FakeRoom()
    desk, alerter, _ = desk_for(room, audio=voice_note(2.0))
    await desk.handle_message(voice_update())
    assert alerter.downloads == ["AgADxyz"] and len(room.played) == 1
    assert 1.9 <= len(room.played[0]) / 2 / 16000 <= 2.2
    assert alerter.said == ["▶️ Playing on Papa's phone now (2 s)."]


async def test_a_voice_note_stops_a_warning_that_is_still_playing_first():
    room = FakeRoom(warning_active=True)
    desk, _, _ = desk_for(room, audio=voice_note(1.0))
    await desk.handle_message(voice_update())
    assert room.barged == ["family"] and len(room.played) == 1


async def test_strangers_and_non_voice_messages_are_ignored_and_problems_are_explained():
    room = FakeRoom()
    desk, alerter, _ = desk_for(room, audio=voice_note(1.0))
    await desk.handle_message(voice_update(chat=4242))  # not the family chat
    await desk.handle_message({"update_id": 2, "message": {"chat": {"id": 999}, "text": "hello"}})
    assert room.played == [] and alerter.said == [] and alerter.downloads == []

    desk2, alerter2, _ = desk_for(None)  # no call and no app connected
    await desk2.handle_message(voice_update())
    assert "No call to send this to" in alerter2.said[-1]

    desk3, alerter3, _ = desk_for(FakeRoom(), audio=b"garbage")
    await desk3.handle_message(voice_update())
    assert "could not play that" in alerter3.said[-1]
    desk4, alerter4, _ = desk_for(FakeRoom(), audio=voice_note(1.0))
    await desk4.handle_message(voice_update(duration=900))
    assert "too long" in alerter4.said[-1] and alerter4.downloads == []  # refused before downloading
    desk5, alerter5, _ = desk_for(FakeRoom(delivered=False), audio=voice_note(1.0))
    await desk5.handle_message(voice_update())
    assert "not connected" in alerter5.said[-1]


def control_press(token, chat=999):
    return {"update_id": 5, "callback_query": {"id": "k1", "data": f"c:{token}:e",
                                               "message": {"message_id": 5, "chat": {"id": chat}}}}


async def test_the_end_button_ends_the_call_and_invites_a_voice_note():
    room = FakeRoom()
    desk, alerter, st = desk_for(room)
    token = st.make_answer_token("live1")
    await desk.handle_control(control_press(token))
    assert room.ended and alerter.answers == ["Ending the call."]
    assert "Send a voice note now" in alerter.said[-1]
    assert ("ended_from_telegram", {}) in room.events


async def test_the_end_button_ignores_strangers_and_calls_that_are_already_over():
    room = FakeRoom()
    desk, alerter, st = desk_for(room)
    token = st.make_answer_token("live1")
    await desk.handle_control(control_press(token, chat=4242))
    assert not room.ended and alerter.answers == []
    room.ended = True
    await desk.handle_control(control_press(token))
    assert alerter.answers == ["That call has already ended."]
    await desk.handle_control(control_press("unknowntk"))
    assert alerter.answers[-1] == "That call has already ended."


# ---- the alerts carry the End button -----------------------------------------------------------------------

async def test_warning_and_takeover_alerts_carry_the_end_button_with_one_token_per_call():
    sent = []

    def handler(req: httpx.Request):
        if req.url.path.endswith("sendMessage"):
            sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent), "chat": {"id": 999}}})

    room = CallRoom("ctl1", NoStt, Store(":memory:"))
    cfg = Settings(_env_file=None, telegram_bot_token="123:abc", telegram_chat_id="999")
    alerter = Alerter(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    pipeline = SimpleNamespace(on_trigger=[], on_new_stage=[], triggered=True, max_risk=80.0)
    persona = SimpleNamespace(on_takeover_hooks=[])
    ca = CallAlerts(alerter, room, pipeline, persona, 3)
    decision = SimpleNamespace(stages_all=["S1", "S2", "S3"], new_stages=[], risk_cum=87.2)
    await pipeline.on_trigger[0](pipeline, decision, {})
    await persona.on_takeover_hooks[0](persona)
    await ca.drain()
    buttons = [b for m in sent for row in m["reply_markup"]["inline_keyboard"] for b in row]
    tokens = {b["callback_data"].split(":")[1] for b in buttons}
    assert len(sent) == 2 and all(b["callback_data"].endswith(":e") for b in buttons) and len(tokens) == 1
    assert room.store.call_for_token(tokens.pop()) == "ctl1"
    assert "voice note" in sent[0]["text"]
    assert control_keyboard("abc")["inline_keyboard"][0][0]["callback_data"] == "c:abc:e"
