"""The app finds the phone's background call and sends it commands, without being a party on it."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main


def fake_room(call_id, started=1.0):
    room = SimpleNamespace(call_id=call_id, ended=False, started_wall=started, takeover=False, control_handlers={})

    async def takeover(r, role, msg):
        r.takeover = True

    async def takeback(r, role, msg):
        r.takeover = False

    room.control_handlers.update(takeover=takeover, takeback=takeback)
    return room


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.rooms, "rooms", {})
    with TestClient(main.app) as c:
        yield c


def test_live_call_finds_the_newest_running_listener_call_only(client):
    old, new = fake_room("apk-old", 1.0), fake_room("apk-new", 2.0)
    main.rooms.rooms.update({"apk-old": old, "apk-new": new, "app-web": fake_room("app-web", 3.0)})
    assert client.get("/api/calls/live").json()["call_id"] == "apk-new"
    new.ended = True
    assert client.get("/api/calls/live").json()["call_id"] == "apk-old"
    old.ended = True
    assert client.get("/api/calls/live").json()["call_id"] is None


def test_control_runs_takeover_and_refuses_the_rest(client):
    room = fake_room("apk-1")
    main.rooms.rooms["apk-1"] = room
    assert client.post("/api/calls/apk-1/control", json={"type": "takeover"}).status_code == 200
    assert room.takeover is True
    assert client.post("/api/calls/apk-1/control", json={"type": "takeback"}).status_code == 200
    assert room.takeover is False
    assert client.post("/api/calls/apk-1/control", json={"type": "other"}).status_code == 400
    assert client.post("/api/calls/nope/control", json={"type": "takeover"}).status_code == 404


def test_takeover_check_reports_the_latest_listener_call(client):
    call_id = f"apk-check-{time.time_ns()}"
    main.store.start_call(call_id)
    main.store.add_event(call_id, "takeover", 1.0, {"by": "receiver"})
    main.store.add_event(call_id, "persona_sent", 2.0, {"bytes": 64000, "seconds": 2.0, "text": "Hello?"})
    main.store.add_event(call_id, "client_voice_route", 3.0, {"route": "yes telephony>18"})
    body = client.get("/api/calls/takeover-check").json()
    assert body["call_id"] == call_id
    assert body["running"] is False
    assert body["seconds_sent_to_caller"] == 2.0
    assert body["persona_sent"][0]["text"] == "Hello?"
    assert body["client_voice_route"][0]["route"] == "yes telephony>18"


def test_the_phones_always_on_link_is_held_and_confirms_a_voice_note(monkeypatch):
    monkeypatch.setattr(main.settings, "kavach_access_key", "k")
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/phone?key=k") as ws:
            main.rooms.phone_heard.clear()
            ws.send_text('{"type":"note_received"}')
            ws.send_text('{"type":"other"}')
            deadline = time.time() + 3
            while not main.rooms.phone_heard.is_set() and time.time() < deadline:
                time.sleep(0.01)
            assert main.rooms.phone is not None and main.rooms.phone_heard.is_set()
        deadline = time.time() + 3
        while main.rooms.phone is not None and time.time() < deadline:
            time.sleep(0.01)
        assert main.rooms.phone is None  # gone with the socket, so a voice note is not sent into nothing
