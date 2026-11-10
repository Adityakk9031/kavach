"""Many families on one server: sign-up, pairing, Telegram linking, isolation between families, languages, voice cloning."""

import secrets
import wave
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import lang, voices
from app.accounts import AccountError, Accounts
from app.config import Settings
from app.family import FamilyDesk
from app.persona import guard, system_prompt
from app.store import Store
from app.warner import pick_template


def make_accounts():
    return Accounts(Store(":memory:"), Settings(_env_file=None))


def email():
    return f"{secrets.token_hex(4)}@example.com"


def pcm(seconds: float, amp: int = 8000, rate: int = 16000) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * 180 * t)).astype("int16").tobytes()


# ---- accounts -------------------------------------------------------------------------------------------------

def test_signup_login_and_tokens_work_and_passwords_are_never_stored_plain():
    a = make_accounts()
    fam, token = a.signup("Anna@Example.com", "correct horse", "es", "Europe/Madrid", "Mamá", "Anna")
    assert fam.language == "es" and fam.parent_address == "Mamá" and fam.timezone == "Europe/Madrid"
    assert a.identify(token).family_id == fam.id and a.identify(token).role == "son"
    stored = a.store.query("SELECT pw FROM users")[0]["pw"]
    assert "correct horse" not in stored and "$" in stored
    assert a.store.query("SELECT hash FROM tokens")[0]["hash"] != token  # only a hash of the token is kept
    assert a.login("anna@example.com", "correct horse")[0].id == fam.id
    with pytest.raises(AccountError, match="wrong"):
        a.login("anna@example.com", "nope nope nope")
    with pytest.raises(AccountError, match="already"):
        a.signup("anna@example.com", "another password")
    with pytest.raises(AccountError, match="8 characters"):
        a.signup(email(), "short")
    with pytest.raises(AccountError, match="not available"):
        a.signup(email(), "long enough pw", language="xx")


def test_too_many_wrong_passwords_lock_the_account_for_a_while():
    a = make_accounts()
    a.signup("lock@example.com", "right password")
    for _ in range(8):
        with pytest.raises(AccountError):
            a.login("lock@example.com", "wrong password")
    with pytest.raises(AccountError, match="Too many"):
        a.login("lock@example.com", "right password")


def test_a_pairing_code_works_once_and_gives_the_parent_phone_its_own_token():
    a = make_accounts()
    fam, _ = a.signup(email(), "long enough pw")
    code = a.new_pair_code(fam.id)["code"]
    assert len(code) == 6 and code.isdigit()
    f2, parent_token = a.redeem_pair_code(code, "1.2.3.4")
    assert f2.id == fam.id and a.identify(parent_token).role == "parent"
    with pytest.raises(AccountError):
        a.redeem_pair_code(code, "1.2.3.4")  # single use
    for _ in range(8):
        with pytest.raises(AccountError):
            a.redeem_pair_code("000000", "9.9.9.9")
    with pytest.raises(AccountError, match="Too many"):
        a.redeem_pair_code(a.new_pair_code(fam.id)["code"], "9.9.9.9")  # that client is slowed down, even with a good code


def test_a_telegram_link_connects_one_chat_to_one_family_once():
    a = make_accounts()
    fam, _ = a.signup(email(), "long enough pw")
    token = a.new_telegram_link(fam.id)
    assert a.link_chat(token, 555).id == fam.id
    assert a.family_for_chat(555).id == fam.id and a.family(fam.id).chat_ids == ["555"]
    assert a.link_chat(token, 777) is None and a.family_for_chat(777) is None  # used up


def test_the_original_household_still_works_with_the_shared_key():
    a = Accounts(Store(":memory:"), Settings(_env_file=None, kavach_access_key="shared", telegram_chat_id="42"))
    assert a.identify("shared").family_id == "default" and a.identify("shared").role == "admin"
    assert a.identify("wrong") is None and a.identify(None) is None
    assert a.family_for_chat(42).id == "default"


# ---- the server: families cannot see each other --------------------------------------------------------------

def test_signup_is_open_but_everything_else_needs_a_token_and_families_are_isolated(monkeypatch):
    monkeypatch.setattr(main.settings, "kavach_access_key", "admin-key")
    with TestClient(main.app) as c:
        assert c.get("/api/me").status_code == 401
        ua = c.post("/api/account/signup", json={"email": email(), "password": "long enough pw", "language": "pt"}).json()
        ub = c.post("/api/account/signup", json={"email": email(), "password": "long enough pw"}).json()
        ha, hb = {"x-kavach-key": ua["token"]}, {"x-kavach-key": ub["token"]}
        me = c.get("/api/me", headers=ha).json()
        assert me["role"] == "son" and me["family"]["language"] == "pt" and me["phone_connected"] is False
        # a call that belongs to family A
        main.store.start_call("apk-isolation-1")
        main.store.update_call("apk-isolation-1", family_id=ua["family"]["id"])
        assert c.get("/api/calls/apk-isolation-1/events", headers=ha).status_code == 200
        assert c.get("/api/calls/apk-isolation-1/events", headers=hb).status_code == 404
        assert c.get("/api/calls/apk-isolation-1/events", headers={"x-kavach-key": "admin-key"}).status_code == 200
        assert c.get("/api/calls/takeover-check", headers=ha).status_code == 403
        # pairing: the son makes a code, the parent phone redeems it and cannot do son things
        code = c.post("/api/family/pair-code", headers=ha).json()["code"]
        parent = c.post("/api/pair", json={"code": code}).json()
        assert parent["role"] == "parent" and parent["family"]["id"] == ua["family"]["id"]
        hp = {"x-kavach-key": parent["token"]}
        assert c.post("/api/family/pair-code", headers=hp).status_code == 403
        assert c.put("/api/family", json={"language": "es"}, headers=hp).status_code == 403
        assert c.put("/api/family", json={"language": "es", "parent_address": "Abuela"}, headers=ha).json()["language"] == "es"
        assert c.put("/api/family", json={"language": "xx"}, headers=ha).status_code == 400
        langs = c.get("/api/languages").json()
        assert [x["code"] for x in langs["languages"]] == ["en", "es", "pt"] and "hi" in langs["coming"]


def test_a_parent_phone_link_is_kept_per_family(monkeypatch):
    monkeypatch.setattr(main.settings, "kavach_access_key", "admin-key")
    with TestClient(main.app) as c:
        ua = c.post("/api/account/signup", json={"email": email(), "password": "long enough pw"}).json()
        fid = ua["family"]["id"]
        with c.websocket_connect(f"/ws/phone?key={ua['token']}"):
            assert fid in main.rooms.phones and main.rooms.phone is None  # the default household is untouched
            assert c.get("/api/phone", headers={"x-kavach-key": ua["token"]}).json() == {"connected": True}
        with pytest.raises(Exception):
            with c.websocket_connect("/ws/phone?key=bad"):
                pass


# ---- Telegram: one bot, many families ------------------------------------------------------------------------

class FakeAlerter:
    def __init__(self):
        self.sent = []

    async def send_message(self, text, reply_markup=None, chat_id=None):
        self.sent.append((chat_id, text))
        return {"result": {"message_id": 1}}


async def test_start_with_a_token_links_the_chat_and_answers_in_the_familys_language():
    a = make_accounts()
    fam, _ = a.signup(email(), "long enough pw", language="es", parent_address="Mamá")
    alerter = FakeAlerter()
    desk = FamilyDesk(alerter, a.store, SimpleNamespace(rooms={}), Settings(_env_file=None), a)
    await desk.handle_message({"message": {"chat": {"id": 900}, "text": f"/start {a.new_telegram_link(fam.id)}"}})
    assert a.family_for_chat(900).id == fam.id
    assert alerter.sent[-1][0] == 900 and "Conectado" in alerter.sent[-1][1] and "Mamá" in alerter.sent[-1][1]
    await desk.handle_message({"message": {"chat": {"id": 901}, "text": "/start not-a-real-token"}})
    assert "expired" in alerter.sent[-1][1] and a.family_for_chat(901) is None
    await desk.handle_message({"message": {"chat": {"id": 902}, "text": "/start"}})
    assert "Connect Telegram" in alerter.sent[-1][1]


# ---- languages -------------------------------------------------------------------------------------------------

def test_every_language_has_every_warning_and_every_telegram_text():
    en = lang.EN
    for pack in lang.PACKS.values():
        assert set(pack.warnings) == set(en.warnings), pack.code
        assert set(pack.t) == set(en.t), pack.code
        assert set(pack.t["stages"]) == set(en.t["stages"]) and len(pack.stalls) == 3
        for text in pack.warnings.values():
            assert "{p}" in text
        for key, text in pack.t.items():
            if isinstance(text, str):  # the same placeholders as English, so .format never fails in a call
                import string
                names = lambda s: {f[1] for f in string.Formatter().parse(s) if f[1]}  # noqa: E731
                assert names(text) == names(en.t[key]), (pack.code, key)


def test_the_warning_is_spoken_in_the_familys_language_to_the_parent_by_name():
    stage, text = pick_template(["S6", "S1"], "Mamá", lang.ES)
    assert stage == "S6" and text.startswith("Mamá, para…") and "dinero" in text
    assert pick_template([], "Mãe", lang.PT)[1].startswith("Mãe, pare…")
    assert pick_template(["S3"], "Mom")[1].startswith("Mom, stop…")  # no pack: the original English


def test_the_takeover_voice_speaks_the_language_and_never_says_real_numbers_in_it():
    es = system_prompt(Settings(_env_file=None), lang.ES)
    assert "ONLY Spanish" in es and "Manuel Ortega" in es and "Ay, Dios mío" in es and "Ramesh" not in es
    pt = system_prompt(Settings(_env_file=None), lang.PT)
    assert "ONLY Portuguese" in pt and "Campinas" in pt
    out, why = guard("Es el uno dos tres cuatro, señor", lang.ES.decoy_phone, lang.ES)
    assert why == "number-run" and out in lang.ES.stalls
    assert guard("Ay, no encuentro mis gafas… ¿me repite el banco, por favor?", lang.ES.decoy_phone, lang.ES)[1] is None
    assert guard("Meu número é cinco cinco cinco, zero um zero zero", lang.PT.decoy_phone, lang.PT)[1] is None  # the made-up number may be said
    assert guard("O código é três quatro cinco", lang.PT.decoy_phone, lang.PT)[1] == "number-run"
    assert guard("It is 4471", lang.EN.decoy_phone, lang.EN)[1] == "digits"


# ---- voices: several takes, then a clone ----------------------------------------------------------------------

def test_three_takes_are_joined_into_one_clearer_sample_capped_at_30_seconds(tmp_path):
    voices.save_sample(tmp_path, "papa", "Papa", pcm(12), consent=True, take=1)
    voices.save_sample(tmp_path, "papa", "Papa", pcm(9), consent=True, take=2)
    rec = voices.save_sample(tmp_path, "papa", "Papa", pcm(9), consent=True, take=3)
    assert rec["takes"] == 3 and rec["seconds"] == 30.0
    with wave.open(str(tmp_path / "papa.wav")) as w:
        assert w.getnframes() == 30 * 16000
    with pytest.raises(ValueError, match="too short"):
        voices.save_sample(tmp_path, "son", "S", pcm(3), consent=True, take=2)
    voices.save_sample(tmp_path, "papa", "Papa", pcm(11), consent=True, take=1)  # starting over forgets the old takes
    assert not list(tmp_path.glob("papa.t*.wav"))


async def test_cloning_sends_the_consented_sample_the_way_the_voices_endpoint_expects(tmp_path):
    voices.save_sample(tmp_path, "son", "Anna", pcm(12), consent=True)
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            body = req.content
            seen.update(path=req.url.path, key=req.headers["authorization"], idem=bool(req.headers.get("idempotency-key")),
                        has_file=b'name="file"' in body and b"RIFF" in body, consent=b'name="consent_attested"' in body and b"true" in body,
                        language=b"spanish" in body)
            return httpx.Response(201, json={"id": "uuid-1", "slug": "kavach-x-son-abc", "ready_models": ["assemblyai-tts-1"]})
        return httpx.Response(200, json={"id": "uuid-1", "ready_models": ["assemblyai-tts-1"]})

    s = Settings(_env_file=None, assemblyai_api_key="k")
    made = await voices.clone_voice(s, tmp_path / "son.wav", "fam-son", "spanish", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert made["voice_id"] == "kavach-x-son-abc" and made["expires"] > 0
    assert seen == {"path": "/v1/voices", "key": "k", "idem": True, "has_file": True, "consent": True, "language": True}

    refuse = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"message": "biometric terms not accepted"})))
    with pytest.raises(RuntimeError, match="biometric"):
        await voices.clone_voice(s, tmp_path / "son.wav", "fam-son", "spanish", refuse)


def test_the_clone_endpoint_records_the_voice_for_that_family_only(tmp_path, monkeypatch):
    monkeypatch.setattr(main.get_settings(), "voices_dir", str(tmp_path))
    monkeypatch.setattr(main.settings, "assemblyai_api_key", "k")

    async def fake_clone(settings, wav, label, language, client=None):
        assert language == "portuguese" and wav.name == "son.wav"
        return {"voice_id": "clone-son-1", "expires": 123.0}

    monkeypatch.setattr(main.voices_mod, "clone_voice", fake_clone)
    with TestClient(main.app) as c:
        u = c.post("/api/account/signup", json={"email": email(), "password": "long enough pw", "language": "pt"}).json()
        h = {"x-kavach-key": u["token"]}
        assert c.post("/api/voices/son/clone", headers=h).status_code == 400  # nothing recorded yet
        up = c.post("/api/voices/son?name=Ana", content=pcm(12), headers={**h, "x-kavach-consent": "yes"})
        assert up.status_code == 200
        c.post("/api/voices/son/clone", headers=h)
        for _ in range(50):
            state = c.get("/api/voices", headers=h).json()
            if state["jobs"].get("son", {}).get("state") != "working":
                break
        assert state["jobs"]["son"]["state"] == "ready" and state["state"]["son"]["cloned"] is True
        assert main.accounts.family(u["family"]["id"]).son_voice_id == "clone-son-1"
        other = c.post("/api/account/signup", json={"email": email(), "password": "long enough pw"}).json()
        assert c.get("/api/voices", headers={"x-kavach-key": other["token"]}).json()["samples"] == {}  # nobody else sees it
