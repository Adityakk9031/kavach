"""The takeover voice plays the kind of person whose phone it is, and talks the way they really talk."""

import asyncio
import time

import pytest

from app import lang, style
from app.accounts import AccountError, Accounts
from app.config import Settings
from app.llm import LLMError
from app.persona import Character, character_of, guard, pack_prompt, style_lines
from app.store import Store


def make_accounts():
    return Accounts(Store(":memory:"), Settings(_env_file=None))


def test_an_unset_family_gets_the_older_person_it_always_had():
    p = pack_prompt(lang.EN)
    assert "72-year-old retired person" in p and "Harold Peterson" in p and "slightly slow way of a 70-year-old" in p
    assert p == pack_prompt(lang.EN, Character())


def test_the_character_follows_who_the_phone_belongs_to():
    mother = pack_prompt(lang.EN, Character(gender="woman", age="senior"))
    assert "72-year-old retired woman" in mother and "Helen Peterson" in mother and "Harold" not in mother
    young = pack_prompt(lang.ES, Character(gender="man", age="young"))
    assert "a man in your late twenties" in young and "70-year-old" not in young and "retired" not in young and "ONLY Spanish" in young
    middle = pack_prompt(lang.DE, Character(gender="woman", age="middle"))
    assert "woman in your fifties" in middle and "Helga Krüger" in middle
    for p in (mother, young, middle):  # the safety rules never change with the character
        assert "Never give a code, PIN" in p and "All of these are fake" in p


def test_the_learned_manner_goes_in_the_prompt_without_digits_or_addresses():
    c = Character(note="Calls everyone dear. Phone 98200 12345, mail a@b.com",
                  style={"summary": "Polite and slow, greets warmly.", "phrases": ["okay okay", "tell me", "pin 4321"], "words_per_turn": 7})
    text = style_lines(c)
    assert "Calls everyone dear" in text and "okay okay" in text and "about 7 words" in text
    assert "98200" not in text and "4321" not in text and "@" not in text
    assert style_lines(Character()) == ""
    assert "Copy the manner only" in pack_prompt(lang.EN, c)


def test_a_family_chooses_who_is_protected_and_bad_values_are_refused():
    acc = make_accounts()
    fam, _ = acc.signup("a@example.com", "password1")
    assert (fam.person_gender, fam.person_age, fam.learn_style, fam.speech_style) == ("", "senior", True, None)
    fam = acc.update_family(fam.id, person_gender="woman", person_age="middle", style_note="Says  okay\nokay, age 54")
    assert (fam.person_gender, fam.person_age) == ("woman", "middle") and fam.style_note == "Says okay okay, age"
    assert character_of(fam) == Character(gender="woman", age="middle", note="Says okay okay, age", style=None)
    with pytest.raises(AccountError):
        acc.update_family(fam.id, person_gender="robot")
    with pytest.raises(AccountError):
        acc.update_family(fam.id, person_age="ancient")


def test_switching_learning_off_forgets_what_was_learned():
    acc = make_accounts()
    fam, _ = acc.signup("b@example.com", "password1")
    acc.set_style(fam.id, {"turns": 12, "summary": "Short and polite.", "phrases": ["one minute"], "words_per_turn": 5})
    fam = acc.family(fam.id)
    assert fam.speech_style["phrases"] == ["one minute"] and character_of(fam).style == fam.speech_style
    fam = acc.update_family(fam.id, learn_style=False)
    assert fam.learn_style is False and fam.speech_style is None and character_of(fam).style is None


def test_only_the_persons_own_words_in_their_own_familys_real_calls_are_studied():
    acc = make_accounts()
    fam, _ = acc.signup("c@example.com", "password1")
    other, _ = acc.signup("d@example.com", "password1")
    st = acc.store
    for call, family, mode in (("c1", fam.id, "live"), ("c2", other.id, "live"), ("c3", fam.id, "eval")):
        st.start_call(call)
        st.update_call(call, family_id=family, mode=mode)
        st.add_turn(call, "caller", 0, f"caller in {call}", 0, 1, time.monotonic(), None)
        st.add_turn(call, "receiver", 1, f"mine in {call}", 0, 1, time.monotonic(), None)
        st.add_turn(call, "persona", 2, f"kavach in {call}", 0, 1, time.monotonic(), None, is_decoy=True)
    assert acc.own_lines(fam.id) == ["mine in c1"]


def test_turn_ids_are_made_without_asking_the_database_and_always_rise():
    st = Store(":memory:")
    st.start_call("t1")
    ids = [st.add_turn("t1", "caller", i, "x", 0, 1, 0.0, None) for i in range(200)]
    assert ids == sorted(set(ids)) and ids[0] > 10 ** 15
    assert [t["id"] for t in st.turns("t1")] == ids


def test_a_sign_in_token_is_looked_up_once_then_remembered():
    acc = make_accounts()
    _, token = acc.signup("e@example.com", "password1")
    first = acc.identify(token)
    asked = []
    real = acc.store.query
    acc.store.query = lambda *a, **k: asked.append(a) or real(*a, **k)
    assert acc.identify(token) == first and asked == []
    assert acc._token_identity("not-a-token") is None and len(asked) == 1  # a wrong one is always checked


class FakeLLM:
    def __init__(self, card=None, fail=False):
        self.card, self.fail, self.calls = card, fail, []

    async def chat_json(self, schema, messages, **kw):
        self.calls.append(messages)
        if self.fail:
            raise LLMError("down")
        return schema.model_validate(self.card), 10, "m"


LINES = ["Okay okay, tell me what happened.", "One minute, I am listening.", "Okay okay, but who are you?",
         "Tell me slowly please, I did not follow.", "One minute, let me sit down.", "Okay okay, I will check and tell you.",
         "Tell me your name once more please."]


def test_a_style_is_learned_only_from_phrases_really_said_more_than_once():
    llm = FakeLLM({"summary": "Polite, unhurried, asks people to repeat.",
                   "phrases": ["okay okay", "tell me", "one minute", "my son Rahul", "call 98200", "I am listening"]})
    card = asyncio.run(style.learn(llm, "m", LINES))
    assert card["phrases"] == ["okay okay", "tell me", "one minute"]  # invented, numbered and said-once phrases are dropped
    assert card["turns"] == 7 and card["words_per_turn"] == 6 and card["summary"].startswith("Polite")
    assert "98200" not in llm.calls[0][1]["content"]


def test_too_little_speech_or_a_failed_model_learns_nothing():
    llm = FakeLLM({"summary": "x", "phrases": []})
    assert asyncio.run(style.learn(llm, "m", ["Hello?", "Who is this?"])) is None and llm.calls == []
    assert asyncio.run(style.learn(FakeLLM(fail=True), "m", LINES)) is None
    numbered = FakeLLM({"summary": "She lives at 12 Park Road.", "phrases": []})
    assert asyncio.run(style.learn(numbered, "m", LINES))["summary"] == ""


def test_the_guard_still_blocks_numbers_whatever_the_character_is():
    assert guard("My PIN is four three two one", lang.EN.decoy_phone, lang.EN)[1] == "number-run"


async def test_on_a_phone_call_the_persons_own_voice_is_transcribed_but_not_played_to_the_caller():
    from app.call_room import CallRoom
    from tests.test_call_room import FakeStt, FakeWs, chunk
    FakeStt.instances.clear()
    room = CallRoom("apk-123", FakeStt, Store(":memory:"))
    caller, receiver = FakeWs(), FakeWs()
    await room.join("caller", caller)
    await room.join("receiver", receiver)
    await room.on_audio("receiver", chunk())
    assert len(FakeStt.instances["receiver"].audio) == len(chunk()) and caller.binary == []
    await room.on_audio("caller", chunk())
    assert len(receiver.binary) == 1  # the caller's side still reaches the app as before


def test_the_phone_is_asked_for_the_persons_own_voice_only_when_the_family_allows_learning(monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main.settings, "kavach_access_key", "admin-key")
    with TestClient(main.app) as c:
        import secrets
        r = c.post("/api/account/signup", json={"email": f"{secrets.token_hex(4)}@example.com", "password": "password1"}).json()
        token = r["token"]

        def first_events(call):
            with c.websocket_connect(f"/ws/call/{call}/receiver?mode=live&key={token}") as ws:
                ws.send_json({"type": "end_call"})
                seen = []
                while "call_ended" not in seen:
                    seen.append(ws.receive_json()["type"])
                return seen

        assert "own_voice" in first_events("apk-900001")
        assert c.put("/api/family", json={"learn_style": False}, headers={"x-kavach-key": token}).status_code == 200
        assert "own_voice" not in first_events("apk-900002")
