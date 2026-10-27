"""Operator usage aggregation — how much is the product being used, per account.

Read-only, and deliberately blind: counts, timestamps and account emails only.
No crew names, phone numbers, project names, locations, or anything else a
customer typed about a shoot is read here. This answers "is this account active
and what is it costing me", not "what is this customer shooting".

Shared by two callers so they can't drift apart:
  - scripts/usage_report.py   — the terminal report
  - routers/admin.py          — the Master Access page

Two families of number, because two different things are knowable:

  ACTIVITY  comes from usage_events, the append-only log written on every
            generate/send/remind. Accurate, but only back to when that table
            went live (2026-08-31) — there is no history before it. AI imports
            are logged there too, with their token counts, but only once
            supabase/usage_import_events.sql has run.

  TOTALS    comes from current state, and is a floor rather than a count.
            Generating a call sheet DELETES the project's prior call_sheets row
            (routers/call_sheet.py), and last_sent_at is overwritten on each
            send, so "recipients" counts people whose most recent send landed in
            the window, not send events.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

GENERATED = "call_sheet_generated"
SENT = "call_sheet_sent"
REMINDED = "call_sheet_reminded"

# Rough marginal cost of one Claude call-sheet generation, in USD.
#
# An ASSUMPTION, not a measurement. Per-generation token counts aren't recorded,
# so this is a flat rate applied to a count. Every surface that shows a total
# derived from it must show the rate too, so the number is never mistaken for a
# bill. Email is excluded on purpose: SendGrid is a flat monthly plan here, so an
# extra recipient costs nothing at the margin.
COST_PER_GENERATION_USD = 0.05

# AI imports — paste-a-list and call sheet uploads. Unlike the figure above,
# these are MEASURED: each import records the token counts the model reported
# (usage.record_import), and spend is those tokens at the model's published
# per-token price. Needs supabase/usage_import_events.sql; before it runs there
# are no import events and every import figure reads zero.
IMPORT_LABELS = {
    "import_roster_paste": "Roster paste",
    "import_roster_call_sheet": "Roster call sheet PDF",
    "import_crew_paste": "Crew paste",
    "import_talent_paste": "Talent paste",
    "import_contacts_paste": "Contacts paste",
    "import_receipt": "PC log receipt",
    "import_estimate": "Budget estimate",
}

# Anthropic's published first-party API price per million tokens, USD. Checked
# 2026-09-28. A model missing from here is still counted, and its tokens shown,
# but it adds nothing to the spend and is reported as unpriced — a guessed
# price would make a measured figure look more exact than it is.
PRICE_PER_MTOK_USD = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

PAGE = 1000


def fetch_all(client, table, columns, optional=False):
    """Page past PostgREST's default 1000-row cap."""
    rows, start = [], 0
    while True:
        try:
            page = client.table(table).select(columns).range(start, start + PAGE - 1).execute().data
        except Exception:
            if optional:
                return None
            raise
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        start += PAGE


def list_all_users(client):
    """Every auth user.

    `list_users()` with no arguments takes GoTrue's default page size (50), so
    calling it bare silently truncates the moment there are more accounts than
    that — and the truncation looks exactly like "we have 50 accounts". Page it.
    """
    users, page, per_page = [], 1, 200
    while True:
        batch = client.auth.admin.list_users(page=page, per_page=per_page)
        users.extend(batch)
        if len(batch) < per_page:
            return users
        page += 1


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(dt):
    return dt.isoformat() if dt else None


def _blank_account():
    return {
        "projects": 0, "new_projects": 0, "sheets_stored": 0, "sheets_sent": 0,
        "recipients": 0, "recipients_window": 0, "confirms": 0, "confirms_window": 0,
        "generates": 0, "sends": 0, "reminders": 0, "emails": 0,
        "imports": 0, "import_cost_usd": 0.0,
        "last_activity": None,
    }


def import_cost_usd(model, input_tokens, output_tokens):
    """Measured spend of one import, or None when the model has no known price."""
    price = PRICE_PER_MTOK_USD.get(model or "")
    if price is None:
        return None
    return ((input_tokens or 0) * price["input"] + (output_tokens or 0) * price["output"]) / 1_000_000


def collect(client, days=7):
    """Aggregate usage across every account. Returns JSON-serializable data.

    Timestamps come back as ISO strings and every value is a plain int/str, so
    the router can hand the result straight to FastAPI.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    users = list_all_users(client)
    projects = fetch_all(client, "projects", "id,owner_id,created_at")
    sheets = fetch_all(client, "call_sheets", "project_id,generated_at,sent_at")
    crew = fetch_all(client, "crew_members", "project_id,last_sent_at,confirmed_at")
    contacts = fetch_all(client, "project_contacts", "project_id,last_sent_at")
    # The token columns only exist once supabase/usage_import_events.sql has
    # run. Asking for them before that fails the whole select, which must not
    # take the generate/send log down with it — so fall back to the old shape.
    events = fetch_all(client, "usage_events",
                       "user_id,event_type,recipient_count,created_at,model,input_tokens,output_tokens",
                       optional=True)
    if events is None:
        events = fetch_all(client, "usage_events", "user_id,event_type,recipient_count,created_at",
                           optional=True)

    owner_of = {p["id"]: p["owner_id"] for p in projects}
    stats = defaultdict(_blank_account)

    def touch(owner, ts):
        if ts and (stats[owner]["last_activity"] is None or ts > stats[owner]["last_activity"]):
            stats[owner]["last_activity"] = ts

    for p in projects:
        s = stats[p["owner_id"]]
        s["projects"] += 1
        created = parse_ts(p.get("created_at"))
        if created and created >= cutoff:
            s["new_projects"] += 1
        touch(p["owner_id"], created)

    for sheet in sheets:
        owner = owner_of.get(sheet["project_id"])
        if not owner:
            continue
        stats[owner]["sheets_stored"] += 1
        if sheet.get("sent_at"):
            stats[owner]["sheets_sent"] += 1
        touch(owner, parse_ts(sheet.get("generated_at")))
        touch(owner, parse_ts(sheet.get("sent_at")))

    for row in crew + contacts:
        owner = owner_of.get(row["project_id"])
        if not owner:
            continue
        s = stats[owner]
        sent = parse_ts(row.get("last_sent_at"))
        if sent:
            s["recipients"] += 1
            if sent >= cutoff:
                s["recipients_window"] += 1
            touch(owner, sent)
        confirmed = parse_ts(row.get("confirmed_at"))
        if confirmed:
            s["confirms"] += 1
            if confirmed >= cutoff:
                s["confirms_window"] += 1
            touch(owner, confirmed)

    # One bucket per day in the window, pre-seeded so a quiet day plots as zero
    # rather than vanishing and hiding the gap between two busy days.
    daily = {
        (cutoff + timedelta(days=i)).date().isoformat():
            {"generates": 0, "sends": 0, "reminders": 0, "emails": 0, "imports": 0}
        for i in range(days + 1)
    }

    by_source = {kind: {"label": label, "count": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
                 for kind, label in IMPORT_LABELS.items()}
    unpriced_imports = 0
    models_seen = set()

    log_since = None
    for e in events or []:
        created = parse_ts(e.get("created_at"))
        if created and (log_since is None or created < log_since):
            log_since = created
        touch(e["user_id"], created)
        if not created or created < cutoff:
            continue
        s = stats[e["user_id"]]
        recipients = e.get("recipient_count") or 0
        bucket = daily.get(created.date().isoformat())
        if e["event_type"] == GENERATED:
            s["generates"] += 1
            if bucket:
                bucket["generates"] += 1
        elif e["event_type"] == REMINDED:
            s["reminders"] += 1
            s["emails"] += recipients
            if bucket:
                bucket["reminders"] += 1
                bucket["emails"] += recipients
        elif e["event_type"] == SENT:
            s["sends"] += 1
            s["emails"] += recipients
            if bucket:
                bucket["sends"] += 1
                bucket["emails"] += recipients
        elif e["event_type"] in IMPORT_LABELS:
            src = by_source[e["event_type"]]
            src["count"] += 1
            s["imports"] += 1
            if bucket:
                bucket["imports"] += 1
            tokens_in, tokens_out = e.get("input_tokens") or 0, e.get("output_tokens") or 0
            src["input_tokens"] += tokens_in
            src["output_tokens"] += tokens_out
            if e.get("model"):
                models_seen.add(e["model"])
            cost = import_cost_usd(e.get("model"), tokens_in, tokens_out)
            if cost is None:
                unpriced_imports += 1
            else:
                src["cost_usd"] += cost
                s["import_cost_usd"] += cost
        # Anything else is counted as activity (touch, above) but not as a send.
        # This was an `else`, which meant any event type added later silently
        # inflated the send and email totals on the Master Access page.

    accounts = []
    for u in users:
        s = stats[u.id]
        accounts.append({
            "email": u.email or "(no email)",
            "signed_up_at": _iso(parse_ts(getattr(u, "created_at", None))),
            "last_sign_in_at": _iso(parse_ts(getattr(u, "last_sign_in_at", None))),
            "last_activity": _iso(s["last_activity"]),
            **{k: v for k, v in s.items() if k not in ("last_activity", "import_cost_usd")},
            "import_cost_usd": round(s["import_cost_usd"], 4),
        })

    floor = datetime.min.replace(tzinfo=timezone.utc)
    accounts.sort(key=lambda a: parse_ts(a["last_activity"]) or floor, reverse=True)

    def total(field):
        return sum(a[field] for a in accounts)

    generates = total("generates")
    return {
        "generated_at": _iso(now),
        "window_days": days,
        "event_log": {
            "available": events is not None,
            "since": _iso(log_since),
            "total": len(events) if events is not None else 0,
        },
        "totals": {
            "accounts": len(accounts),
            "active_accounts": sum(
                1 for a in accounts
                if a["last_activity"] and parse_ts(a["last_activity"]) >= cutoff
            ),
            "projects": len(projects),
            "call_sheets_stored": len(sheets),
            "generates": generates,
            "sends": total("sends"),
            "reminders": total("reminders"),
            "emails": total("emails"),
            "confirms": total("confirms"),
            "confirms_window": total("confirms_window"),
            # ASSUMED: a flat rate times a count (see COST_PER_GENERATION_USD).
            "estimated_cost_usd": round(generates * COST_PER_GENERATION_USD, 2),
            "cost_rate_usd": COST_PER_GENERATION_USD,
            # MEASURED: recorded tokens at the published prices listed beside it.
            "imports": sum(src["count"] for src in by_source.values()),
            "import_input_tokens": sum(src["input_tokens"] for src in by_source.values()),
            "import_output_tokens": sum(src["output_tokens"] for src in by_source.values()),
            "import_cost_usd": round(sum(src["cost_usd"] for src in by_source.values()), 4),
            "import_unpriced": unpriced_imports,
            "import_by_source": [
                {"event_type": kind, **{k: (round(v, 4) if k == "cost_usd" else v) for k, v in src.items()}}
                for kind, src in by_source.items()
            ],
            # Every rate the measured figure could have used, so a surface can
            # always print the rate next to the total.
            "import_prices": [
                {"model": model, "input_per_mtok_usd": p["input"], "output_per_mtok_usd": p["output"]}
                for model, p in sorted(PRICE_PER_MTOK_USD.items())
            ],
            "import_models_unpriced": sorted(m for m in models_seen if m not in PRICE_PER_MTOK_USD),
        },
        "daily": [{"date": d, **v} for d, v in sorted(daily.items())],
        "accounts": accounts,
    }
