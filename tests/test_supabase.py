"""Supabase: sign-in is vouched for by Supabase Auth, and the same store code runs on Postgres.

The Postgres tests need a real server: set KAVACH_TEST_PG to a connection string (a throwaway database). They are skipped
without it. The sign-in tests replace the one call to Supabase with a stand-in, so they run offline.
"""

import os
import secrets
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.accounts import AccountError, Accounts
from app.config import Settings
from app.store import Store, _pg

PG = os.environ.get("KAVACH_TEST_PG", "")
needs_pg = pytest.mark.skipif(not PG, reason="set KAVACH_TEST_PG to run against Postgres")


def test_sqlite_style_sql_becomes_postgres_sql():
    assert _pg("SELECT 1 FROM calls WHERE id=? AND x LIKE 'apk-%'") == "SELECT 1 FROM calls WHERE id=%s AND x LIKE 'apk-%%'"
    assert "BIGSERIAL PRIMARY KEY" in _pg("id INTEGER PRIMARY KEY AUTOINCREMENT") and "DOUBLE PRECISION" in _pg("created REAL")


# ---- sign-in through Supabase ---------------------------------------------------------------------------------

@pytest.fixture
def supa(monkeypatch):
    """The server with Supabase switched on, and Supabase's answer to "whose token is this?" under the test's control."""
    users = {}
    monkeypatch.setattr(main.settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(main.settings, "supabase_anon_key", "anon-public-key")

    async def fake_user(token):
        return users.get(token)
    monkeypatch.setattr(main, "supabase_user", fake_user)
    return users


def test_app_learns_where_to_sign_in_and_never_gets_a_secret(supa):
    with TestClient(main.app) as c:
        cfg = c.get("/api/auth-config").json()
    assert cfg == {"supabase": True, "url": "https://example.supabase.co", "anon_key": "anon-public-key"}


def test_supabase_token_becomes_a_kavach_token_and_the_same_person_gets_the_same_family(supa):
    mail = f"{secrets.token_hex(4)}@example.com"
    supa["good"] = {"id": "uuid-" + mail, "email": mail, "email_confirmed_at": "2026-11-11T00:00:00Z"}
    with TestClient(main.app) as c:
        first = c.post("/api/account/session", json={"access_token": "good", "language": "de", "parent_address": "Oma"}).json()
        assert first["new"] is True and first["family"]["language"] == "de" and first["family"]["parent_address"] == "Oma"
        me = c.get("/api/me", headers={"x-kavach-key": first["token"]}).json()
        assert me["role"] == "son" and me["family"]["id"] == first["family"]["id"]
        again = c.post("/api/account/session", json={"access_token": "good", "language": "fr"}).json()
        assert again["new"] is False and again["family"]["id"] == first["family"]["id"] and again["family"]["language"] == "de"


def test_bad_expired_or_unconfirmed_sign_ins_get_nothing(supa):
    supa["unconfirmed"] = {"id": "u2", "email": "new@example.com", "email_confirmed_at": None}
    with TestClient(main.app) as c:
        assert c.post("/api/account/session", json={"access_token": "made-up"}).status_code == 401
        r = c.post("/api/account/session", json={"access_token": "unconfirmed"})
        assert r.status_code == 400 and "confirm" in r.json()["detail"] and "token" not in r.json()
        # the built-in passwords are off once Supabase is on: there is one way in
        assert c.post("/api/account/signup", json={"email": "a@example.com", "password": "long enough pw"}).status_code == 400
        assert c.post("/api/account/login", json={"email": "a@example.com", "password": "long enough pw"}).status_code == 400


def test_supabase_sign_in_is_refused_when_the_server_does_not_use_it():
    with TestClient(main.app) as c:
        assert c.get("/api/auth-config").json() == {"supabase": False}
        assert c.post("/api/account/session", json={"access_token": "x"}).status_code == 400


def test_an_older_password_account_is_joined_to_its_supabase_sign_in_and_blank_passwords_never_log_in():
    a = Accounts(Store(":memory:"), Settings(_env_file=None))
    fam, _ = a.signup("old@example.com", "long enough pw")
    same, token, new = a.supabase_session("uuid-1", "Old@Example.com")
    assert same.id == fam.id and new is False and a.identify(token).family_id == fam.id
    other, _, new = a.supabase_session("uuid-2", "fresh@example.com", language="it")
    assert new is True and other.language == "it" and other.id != fam.id
    with pytest.raises(AccountError):
        a.login("fresh@example.com", "")


# ---- the same store on Postgres -------------------------------------------------------------------------------

@needs_pg
def test_postgres_store_keeps_calls_turns_events_and_accounts():
    st = Store("", PG)
    cid = "pg-" + secrets.token_hex(4)
    st.start_call(cid, caller_number=None)
    st.start_call(cid, caller_number="+1 555 0100")  # the second start fills in the number, it does not fail
    st.update_call(cid, family_id="fam1", max_risk=72.5)
    t1 = st.add_turn(cid, "caller", 0, "hello", 0, 900, 1.0, 120.0)
    t2 = st.add_turn(cid, "caller", 1, "send money", 900, 1800, 2.0, None, is_decoy=True)
    assert t2 > t1
    for i in range(50):
        st.add_event(cid, "tick", float(i), {"i": i})
    row = st.query("SELECT * FROM calls WHERE id=?", (cid,))[0]  # a read sees every background write before it
    assert row["caller_number"] == "+1 555 0100" and row["family_id"] == "fam1" and row["max_risk"] == 72.5
    assert abs(row["started_at"] - time.time()) < 60  # 8-byte floats: a 4-byte one would be minutes off
    assert [e["payload"]["i"] for e in st.events(cid)] == list(range(50))
    assert [t["text"] for t in st.turns(cid)] == ["hello", "send money"]
    assert st.query("SELECT id FROM calls WHERE id LIKE 'pg-%' ORDER BY started_at DESC LIMIT 1")
    token = st.make_answer_token(cid)
    assert st.call_for_token(token) == cid

    a = Accounts(st, Settings(_env_file=None))
    mail = f"{secrets.token_hex(4)}@example.com"
    fam, tok = a.signup(mail, "long enough pw", "fr", "Europe/Paris", "Mamie", "Léa")
    assert a.identify(tok).family_id == fam.id and a.login(mail, "long enough pw")[0].id == fam.id
    code = a.new_pair_code(fam.id)["code"]
    assert a.redeem_pair_code(code, "c1")[0].id == fam.id
    with pytest.raises(AccountError):
        a.redeem_pair_code(code, "c1")
    link = a.new_telegram_link(fam.id)
    chat = "chat-" + secrets.token_hex(3)
    assert a.link_chat(link, chat).id == fam.id and a.family_for_chat(chat).id == fam.id
    other, _, _ = a.supabase_session("uuid-" + mail, "x" + mail)
    a.link_chat(a.new_telegram_link(other.id), chat)  # the chat moves to the other family, no duplicate-key error
    assert a.family_for_chat(chat).id == other.id
    a.set_voice(fam.id, "son", "voice-1", time.time() + 86400)
    assert a.voice_state(fam.id)["son"]["cloned"] is True


@needs_pg
def test_postgres_tables_are_closed_to_supabases_public_api():
    st = Store("", PG)
    Accounts(st, Settings(_env_file=None))
    rows = st.query("SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('calls','turns','events','users','tokens','families')")
    assert len(rows) == 6 and all(r["relrowsecurity"] for r in rows)


@needs_pg
def test_postgres_store_reconnects_after_the_connection_drops():
    st = Store("", PG)
    st._db.close()
    assert st.query("SELECT 1 AS one")[0]["one"] == 1


# ---- supabase/schema.sql ---------------------------------------------------------------------------------------

def test_supabase_schema_file_matches_the_servers_own_schema():
    """The file is made from the server's code; if a table changes and the file is not re-made, this fails."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("supabase_schema", root / "scripts" / "supabase_schema.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (root / "supabase" / "schema.sql").read_text() == gen.build(), "run: uv run python scripts/supabase_schema.py"


@needs_pg
def test_supabase_schema_file_runs_twice_and_the_server_starts_on_it():
    import psycopg
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "supabase" / "schema.sql").read_text()
    schema = "schema_file_" + secrets.token_hex(4)  # a fresh, empty place, so the file has to create everything itself
    with psycopg.connect(PG, autocommit=True) as db:
        db.execute(f"CREATE SCHEMA {schema}")
        try:
            db.execute(f"SET search_path TO {schema}")
            db.execute(sql)
            db.execute(sql)  # safe to run more than once
            tables = db.execute("SELECT relname, relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                "WHERE n.nspname=%s AND c.relkind='r'", (schema,)).fetchall()
            assert len(tables) == 12 and all(rls for _, rls in tables)
            indexes = {r[0] for r in db.execute("SELECT indexname FROM pg_indexes WHERE schemaname=%s", (schema,)).fetchall()}
            assert {"users_auth", "tg_chats_family", "calls_family", "evidence_call", "detections_call"} <= indexes
            # The server starts on the tables the file made, and works
            sep = "&" if "?" in PG else "?"
            st = Store("", f"{PG}{sep}options=-csearch_path%3D{schema}")
            acc = Accounts(st, Settings(_env_file=None))
            fam, token = acc.signup(f"schema-{secrets.token_hex(3)}@example.com", "a-long-password", "de")
            assert acc.identify(token).family_id == fam.id
            other, _, _ = acc.supabase_session("uuid-" + secrets.token_hex(4), f"s-{secrets.token_hex(3)}@example.com")
            assert other.id != fam.id
            st.start_call("c-schema", caller_number=None)
            st.update_call("c-schema", family_id=fam.id)
            assert st.query("SELECT family_id FROM calls WHERE id=?", ("c-schema",))[0]["family_id"] == fam.id
        finally:
            db.execute(f"DROP SCHEMA {schema} CASCADE")
