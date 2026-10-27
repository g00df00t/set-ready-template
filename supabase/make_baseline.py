#!/usr/bin/env python3
"""Build migrations/0001_baseline.sql from schema_dump.sql.

    python3 supabase/make_baseline.py

The baseline is what turns an EMPTY Supabase project into a Set Ready database
in one run — a producer's own copy (docs/own-copy-plan.md). It is the
production dump with the parts a live Supabase project refuses taken out, the
three dead tables left off, and three things added that the dump can't carry:

  - the storage buckets, as rows in storage.buckets (buckets aren't schema)
  - explicit GRANTs, because the dump is taken --no-privileges and a project
    with "expose new tables" off would otherwise have every table invisible
    to PostgREST, with an error that looks nothing like the cause
  - public.schema_migrations, so a copy can say which migrations it has.
    The backend only ever READS it (/health reports drift); it never applies
    DDL, and every later file in migrations/ ends by inserting its own name

Re-run after any schema change, after dump-schema.sh. Only re-generates;
never applies anything. No dependencies beyond Python.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DUMP = HERE / "schema_dump.sql"
OUT = HERE / "migrations" / "0001_baseline.sql"

# Zero rows, nothing reads them (CLAUDE.md, "Three exist but no code touches
# them"). A new copy shouldn't carry a scrapped lunch feature.
DEAD_TABLES = ("lunch_orders", "lunch_sessions", "productions")

# Supabase's own "auto-enable RLS" function, present in new projects already;
# CREATE FUNCTION on it fails with "already exists". The baseline enables RLS
# on every table explicitly, so nothing needs it.
SUPABASE_OWNED = ("rls_auto_enable",)

# Whole lines the dump has that a live Supabase target refuses — the same
# list apply-schema.sh strips, and why.
DROP_LINES = (
    re.compile(r"^\\restrict "),
    re.compile(r"^\\unrestrict "),
    re.compile(r"^CREATE SCHEMA public;$"),
    re.compile(r"^ALTER SCHEMA public "),
    re.compile(r"^COMMENT ON SCHEMA public "),
    re.compile(r"^SET transaction_timeout = "),
)

HEADER = re.compile(r"^-- Name: (?P<name>.*?); Type: (?P<type>[^;]+); Schema: (?P<schema>[^;]*);", re.M)

TAIL = """
--
-- Set Ready additions. Everything above is the production schema; everything
-- below is what a dump can't carry (supabase/make_baseline.py).
--

--
-- Storage buckets. Buckets are rows, not schema. Two are private — downloads
-- go through the backend, which checks ownership first — and brand-assets is
-- public because the people who see a title card (crew on a confirm page,
-- a client on a wrap report) have no account to authenticate against.
--

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
    ('call-sheet-attachments', 'call-sheet-attachments', false, 26214400, NULL),
    ('brand-assets',           'brand-assets',           true,   8388608, ARRAY['image/jpeg', 'image/png', 'image/webp']),
    ('receipts',               'receipts',               false, 15728640, NULL)
ON CONFLICT (id) DO NOTHING;

--
-- Grants. The dump is taken --no-privileges, so without these a project whose
-- "Automatically expose new tables" setting is off has every table invisible
-- to the API. These are the privileges a Supabase project applies by default.
--

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;

--
-- Which migrations this database has. RLS on with no policies: only the
-- service role (the backend) can read it, and nothing writes it but the
-- migration files themselves, each ending with its own INSERT.
--

CREATE TABLE public.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;

INSERT INTO public.schema_migrations (version) VALUES ('0001_baseline');
"""


def blocks(text):
    """The dump as pg_dump wrote it: a preamble, then one block per object,
    each introduced by a '-- Name: …; Type: …' header."""
    starts = [m.start() for m in HEADER.finditer(text)]
    if not starts:
        sys.exit("schema_dump.sql has no '-- Name:' headers — is it a pg_dump?")
    yield "preamble", None, text[: starts[0]]
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        m = HEADER.match(text, s)
        yield m.group("name"), m.group("type"), text[s:e]


def mentions_dead(name, body):
    low = f"{name}\n{body}".lower()
    return any(re.search(rf"\b{t}\b", low) for t in DEAD_TABLES)


def main():
    text = DUMP.read_text()
    kept, dropped = [], []
    for name, kind, body in blocks(text):
        if name != "preamble" and (mentions_dead(name, body) or any(f in name for f in SUPABASE_OWNED)):
            dropped.append(f"{kind}: {name}")
            continue
        lines = [ln for ln in body.splitlines() if not any(p.match(ln) for p in DROP_LINES)]
        kept.append("\n".join(lines))
    out = "\n".join(kept).rstrip()
    # pg_dump's closing banner belongs at the very end, after our additions.
    out = out.replace("--\n-- PostgreSQL database dump complete\n--", "").rstrip()
    out = out.replace(
        "-- PostgreSQL database dump\n--",
        "-- PostgreSQL database dump — Set Ready baseline, generated by\n"
        "-- supabase/make_baseline.py from schema_dump.sql. Do not edit; re-run.\n--",
        1,
    )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(out + "\n" + TAIL)
    tables = len(re.findall(r"^CREATE TABLE ", out, re.M)) + 1
    policies = len(re.findall(r"^CREATE POLICY ", out, re.M))
    print(f"wrote {OUT.relative_to(HERE.parent)}: {tables} tables, {policies} policies, 3 buckets")
    print("left out:")
    for d in dropped:
        print(f"  {d}")


if __name__ == "__main__":
    main()
