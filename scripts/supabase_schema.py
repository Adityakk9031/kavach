"""Writes supabase/schema.sql: Kavach's whole database for Supabase (Postgres), made from the server's own schema so the
two can never disagree. Run it after changing a table:  uv run python scripts/supabase_schema.py

You do not have to run the file by hand: the server creates the same tables itself when it starts with DATABASE_URL set.
It is here to read, to keep in git, and to paste into Supabase's SQL editor if you want the tables before the first deploy.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import accounts, store  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "supabase" / "schema.sql"

# Columns added after the first release, and the indexes that need them (the server adds both at start-up too)
LATER = [
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS family_id TEXT",
    "CREATE INDEX IF NOT EXISTS calls_family ON calls(family_id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_id TEXT",
    "CREATE INDEX IF NOT EXISTS users_auth ON users(auth_id)",
    # who the protected person is and how they talk, for the takeover voice
    *[f"ALTER TABLE families ADD COLUMN IF NOT EXISTS {c} {store._pg(k)}" for c, k in accounts.PERSON_COLUMNS],
    # turn ids are made by the server (microseconds), too big for a 4-byte column
    "ALTER TABLE detections ALTER COLUMN turn_id TYPE BIGINT",
    "ALTER TABLE evidence ALTER COLUMN turn_id TYPE BIGINT",
]


def statements(schema: str) -> list[str]:
    return [store._pg(s.strip()).replace("%%", "%") for s in schema.split(";") if s.strip()]


def build() -> str:
    parts = statements(store.SCHEMA) + statements(accounts.SCHEMA)
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", store.SCHEMA + accounts.SCHEMA)
    out = [
        "-- Kavach database for Supabase (Postgres). Made by scripts/supabase_schema.py from the server's own schema:",
        "-- do not edit by hand. Safe to run more than once.",
        "--",
        "-- Row-level security is on for every table and no policy is added on purpose: Supabase serves the public",
        "-- schema over its web API with the anon key that ships inside the app, so the tables must stay closed to it.",
        "-- The Kavach server connects with the database owner's connection string, which row-level security does not limit.",
        "",
        "-- Tables",
    ]
    out += [p + ";" for p in parts if p.startswith("CREATE TABLE")]
    out += ["", "-- Added after the first release"] + [s + ";" for s in LATER]
    out += ["", "-- Indexes"] + [p + ";" for p in parts if p.startswith("CREATE INDEX")]
    out += ["", "-- Closed to Supabase's public web API"] + [f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;" for t in tables]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(build())
    print(f"wrote {OUT}")
