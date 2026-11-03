"""With an access key set, nothing that returns or changes data is reachable without it; pages and /health stay open."""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(main.settings, "kavach_access_key", "s3cret-key")
    with TestClient(main.app) as client:
        yield client


def test_api_and_audio_need_the_key(locked):
    assert locked.get("/api/config").status_code == 401
    assert locked.get("/api/eval/latest").status_code == 401
    assert locked.get("/eval-audio/anything.wav").status_code == 401
    assert locked.post("/api/calls/x/report", json={}).status_code == 401
    assert locked.get("/api/config?key=wrong").status_code == 401
    assert locked.get("/api/config?key=s3cret-key").status_code == 200
    assert locked.get("/api/config", headers={"x-kavach-key": "s3cret-key"}).status_code == 200


def test_pages_and_health_stay_open_and_hold_no_data(locked):
    assert locked.get("/health").status_code == 200
    for page in ("receiver.html", "caller.html", "speaker.html", "scoreboard.html"):
        assert locked.get(f"/web/{page}").status_code == 200, page


def test_websockets_are_refused_without_the_key_and_work_with_it(locked, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    cid = f"key-{uuid.uuid4().hex[:8]}"
    with pytest.raises(WebSocketDisconnect) as e:
        with locked.websocket_connect(f"/ws/call/{cid}/caller"):
            pass
    assert e.value.code == 4403
    with pytest.raises(WebSocketDisconnect):
        with locked.websocket_connect(f"/ws/events/{cid}?key=nope"):
            pass
    with locked.websocket_connect(f"/ws/events/{cid}?key=s3cret-key") as ok:
        ok.close()


def test_no_key_configured_means_open_as_before(monkeypatch):
    monkeypatch.setattr(main.settings, "kavach_access_key", "")
    with TestClient(main.app) as client:
        assert client.get("/api/config").status_code == 200


def test_a_browser_app_on_another_origin_can_ask_but_still_needs_the_key(locked):
    pre = locked.options("/api/voices", headers={"Origin": "http://localhost:8081", "Access-Control-Request-Method": "GET",
                                                 "Access-Control-Request-Headers": "x-kavach-key"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "*"
    r = locked.get("/api/voices", headers={"Origin": "http://localhost:8081"})
    assert r.status_code == 401
    ok = locked.get("/api/voices", headers={"Origin": "http://localhost:8081", "x-kavach-key": "s3cret-key"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "*"
