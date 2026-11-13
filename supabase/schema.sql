-- Kavach database for Supabase (Postgres). Made by scripts/supabase_schema.py from the server's own schema:
-- do not edit by hand. Safe to run more than once.
--
-- Row-level security is on for every table and no policy is added on purpose: Supabase serves the public
-- schema over its web API with the anon key that ships inside the app, so the tables must stay closed to it.
-- The Kavach server connects with the database owner's connection string, which row-level security does not limit.

-- Tables
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'live', script_id TEXT, caller_number TEXT,
  started_at DOUBLE PRECISION, ended_at DOUBLE PRECISION, label TEXT, scam_type TEXT, max_risk DOUBLE PRECISION,
  warned_at DOUBLE PRECISION, takeover_at DOUBLE PRECISION, money_shared INTEGER, otp_shared INTEGER,
  report_md_path TEXT, report_pdf_path TEXT, family_id TEXT
);
CREATE TABLE IF NOT EXISTS turns (
  id BIGSERIAL PRIMARY KEY, call_id TEXT NOT NULL, channel TEXT NOT NULL, idx INTEGER,
  text TEXT, audio_start_ms INTEGER, audio_end_ms INTEGER, final_at_mono DOUBLE PRECISION, stt_latency_ms DOUBLE PRECISION,
  is_decoy INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS detections (
  id BIGSERIAL PRIMARY KEY, call_id TEXT NOT NULL, turn_id BIGINT, stages TEXT,
  evidence_quotes TEXT, risk_llm INTEGER, risk_cum DOUBLE PRECISION, rationale TEXT, triggered INTEGER,
  llm_ms INTEGER, model TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
  id BIGSERIAL PRIMARY KEY, call_id TEXT NOT NULL, turn_id BIGINT, type TEXT,
  value TEXT, normalized TEXT, quote TEXT, ts_ms INTEGER, valid INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY, call_id TEXT NOT NULL, ts_mono DOUBLE PRECISION, ts_wall DOUBLE PRECISION,
  type TEXT NOT NULL, payload TEXT
);
CREATE TABLE IF NOT EXISTS answer_tokens (token TEXT PRIMARY KEY, call_id TEXT NOT NULL, created DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS families (
  id TEXT PRIMARY KEY, name TEXT, language TEXT NOT NULL DEFAULT 'en', timezone TEXT NOT NULL DEFAULT 'UTC',
  parent_address TEXT NOT NULL DEFAULT 'Mom', son_name TEXT NOT NULL DEFAULT '',
  report_hint TEXT NOT NULL DEFAULT 'your local police or national fraud reporting service',
  son_voice_id TEXT, papa_voice_id TEXT, son_voice_expires DOUBLE PRECISION, papa_voice_expires DOUBLE PRECISION, voice_notes TEXT, created DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, family_id TEXT NOT NULL, created DOUBLE PRECISION, auth_id TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
  hash TEXT PRIMARY KEY, family_id TEXT NOT NULL, role TEXT NOT NULL, user_id INTEGER, created DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS pair_codes (code TEXT PRIMARY KEY, family_id TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tg_links (hash TEXT PRIMARY KEY, family_id TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS tg_chats (chat_id TEXT PRIMARY KEY, family_id TEXT NOT NULL, linked DOUBLE PRECISION);

-- Added after the first release
ALTER TABLE calls ADD COLUMN IF NOT EXISTS family_id TEXT;
CREATE INDEX IF NOT EXISTS calls_family ON calls(family_id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_id TEXT;
CREATE INDEX IF NOT EXISTS users_auth ON users(auth_id);
ALTER TABLE families ADD COLUMN IF NOT EXISTS person_gender TEXT;
ALTER TABLE families ADD COLUMN IF NOT EXISTS person_age TEXT;
ALTER TABLE families ADD COLUMN IF NOT EXISTS style_note TEXT;
ALTER TABLE families ADD COLUMN IF NOT EXISTS learn_style INTEGER;
ALTER TABLE families ADD COLUMN IF NOT EXISTS speech_style TEXT;
ALTER TABLE detections ALTER COLUMN turn_id TYPE BIGINT;
ALTER TABLE evidence ALTER COLUMN turn_id TYPE BIGINT;

-- Indexes
CREATE INDEX IF NOT EXISTS events_call ON events(call_id, ts_mono);
CREATE INDEX IF NOT EXISTS turns_call ON turns(call_id, idx);
CREATE INDEX IF NOT EXISTS detections_call ON detections(call_id);
CREATE INDEX IF NOT EXISTS evidence_call ON evidence(call_id);
CREATE INDEX IF NOT EXISTS tg_chats_family ON tg_chats(family_id);

-- Closed to Supabase's public web API
ALTER TABLE calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE detections ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE families ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE pair_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE tg_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE tg_chats ENABLE ROW LEVEL SECURITY;
