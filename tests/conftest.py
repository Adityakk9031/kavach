"""Make the "offline" tests really offline: no real database, no real voice session, no Telegram.

Environment variables beat .env, so these are set before app.main is imported. The AssemblyAI API key is left alone
because the live transcript tests (tests/test_detector.py -k transcripts) need it.
"""

import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="kavach-test-"), "test.db")
os.environ["REPORTS_DIR"] = os.path.join(tempfile.mkdtemp(prefix="kavach-reports-"))
os.environ["KAVACH_WARNING_VOICE_ID"] = ""  # no cloned-voice TTS session opened by the app's startup
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
os.environ["KAVACH_ACCESS_KEY"] = ""  # a key in the local .env must not lock the tests out
os.environ["VOICES_DIR"] = os.path.join(tempfile.mkdtemp(prefix="kavach-voices-"))
os.environ["DATABASE_URL"] = os.environ.get("KAVACH_TEST_PG_APP", "")  # tests use SQLite; tests/test_supabase.py opts in with KAVACH_TEST_PG
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_ANON_KEY"] = ""
