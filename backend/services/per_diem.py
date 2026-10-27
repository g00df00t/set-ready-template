"""The per diem sheet: what cash each person gets, day by day, and how it was
paid (docs/producer-documents-map.md §1.6). Pure — no database.

It's the rooming list's grid with a different cell rule, and it reads the
same "who's away" setting (job_hires.away, services/rooming.py):

- Every AWAY date is paid — the last one too (unlike a hotel night), so a
  one-day booking still gets its per diem. A local gets nothing.
- A HOTEL NIGHT always counts as away (Patrick, 2026-10-02), and so does the
  check-out morning after it: a night added by hand on Rooming — someone kept
  over a day off — is paid here without being entered twice.
- The amount is the job's: per_diem_shoot on any date they shoot,
  per_diem_other on every other away date — travel, check-in, prep, down day,
  wrap, travel out (the producer, 2026-10-01: $50 shoot / $70 non-shoot, prep
  included).
- Hand edits (job_hires.per_diem_overrides, {date: amount}) replace a day's
  amount; 0 takes a day off.
- Paid (job_hires.per_diem_paid) is her "Initials" column: how and when —
  cash, Venmo, Zelle — or a signature line when it's cash in hand.

Internal: a receipt for the producer and the reconciliation, signed by crew.
It shows per diem, so it never goes to a hotel — and it carries no rates,
phones or emails all the same (test_per_diem.py).
"""

from datetime import date

from services.job_dates import DatesError, _days, _iso, effective_dates, hire_base
from services.holds import is_booked
from services.job_rates import _num, money
from services.rooming import _header, _next, away_dates, nights, runs

PAID_METHODS = ("cash", "venmo", "zelle", "check", "other")
METHOD_LABELS = {"cash": "cash", "venmo": "Venmo", "zelle": "Zelle", "check": "check", "other": ""}
AMOUNT_MAX = 10_000


def validate_overrides(value) -> dict:
    """{ISO date: amount ≥ 0}; 0 means not paid that day."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DatesError("Per diem edits must be an object keyed by date.")
    out = {}
    for key, amount in value.items():
        d = _iso(key).isoformat()
        if amount is None:
            continue
        n = _num(amount)
        if n is None or n > AMOUNT_MAX:
            raise DatesError(f"A day's per diem must be between $0 and ${AMOUNT_MAX:,}.")
        out[d] = n
    return out


def validate_paid(value) -> dict | None:
    """{method, date, note} or None (not paid yet)."""
    if not value:
        return None
    if not isinstance(value, dict):
        raise DatesError("Paid must be an object.")
    method = value.get("method")
    if method not in PAID_METHODS:
        raise DatesError(f"Paid by one of: {', '.join(PAID_METHODS)}.")
    when = _iso(value["date"]).isoformat() if value.get("date") else None
    note = value.get("note")
    if note is not None and not isinstance(note, str):
        raise DatesError("A payment note must be text.")
    note = " ".join((note or "").split())[:120] or None
    return {"method": method, "date": when, "note": note}


def paid_text(paid: dict | None) -> str:
    """Her Initials column: "paid Venmo 10/24", "paid cash 8/7"."""
    if not paid:
        return ""
    parts = ["paid", METHOD_LABELS.get(paid.get("method"), "")]
    if paid.get("date"):
        d = date.fromisoformat(paid["date"])
        parts.append(f"{d.month}/{d.day}")
    if paid.get("note"):
        parts.append(f"– {paid['note']}")
    return " ".join(p for p in parts if p)


def days_owed(job: dict, hire: dict) -> dict[str, float]:
    """{date: amount} for one person: the rule, then their hand edits on top.
    Days that come to 0 are left out — not owed, not printed."""
    shoot, other = _num(job.get("per_diem_shoot")), _num(job.get("per_diem_other"))
    eff = effective_dates(hire_base(job, hire), hire.get("dates_override"))
    shooting = {d.isoformat() for d in _days(eff["shoot"])}
    base, override = hire_base(job, hire), hire.get("dates_override")
    away = set(away_dates(base, override, hire.get("away")))
    hotel, _ = nights(base, override, hire.get("away"), hire.get("room_overrides"))
    for run in runs(hotel):
        away.update(run)
        away.add(_next(run[-1]))            # the check-out morning
    out = {}
    for d in sorted(away):
        amount = shoot if d in shooting else other
        if amount is not None:
            out[d] = amount
    for d, amount in (hire.get("per_diem_overrides") or {}).items():
        out[d] = amount
    return {d: a for d, a in sorted(out.items()) if a}


def build_sheet(job: dict, hires: list[dict]) -> dict:
    """One sheet for the job: a column per date anyone is owed, a row per
    person owed anything, totals per day and overall. `missing_amounts` is
    true when the job has no per diem amounts set yet — the screen says so
    instead of showing an empty sheet."""
    rows = []
    for h in hires:
        if not is_booked(h):        # a hold isn't owed per diem until booked
            continue
        if h.get("kind") == "talent":   # talent's per diem runs through the agency deal
            continue
        owed = days_owed(job, h)
        if not owed:
            continue
        rows.append({
            "hire_id": h["id"], "name": h.get("name"),
            "notes": h.get("per_diem_note") or "",
            "cells": owed, "total": sum(owed.values()),
            "paid": h.get("per_diem_paid"), "paid_text": paid_text(h.get("per_diem_paid")),
        })
    dates = sorted({d for r in rows for d in r["cells"]})
    if dates:
        # Every date in the run, so a day nobody's owed still shows as a column.
        dates = [d.isoformat() for d in _days([[dates[0], dates[-1]]])]
    return {
        "dates": [_header(job, d) for d in dates],
        "rows": rows,
        "totals": {d: sum(r["cells"].get(d, 0) for r in rows) for d in dates},
        "total": sum(r["total"] for r in rows),
        "missing_amounts": _num(job.get("per_diem_shoot")) is None and _num(job.get("per_diem_other")) is None,
        "rates": {"shoot": money(job.get("per_diem_shoot")), "other": money(job.get("per_diem_other"))},
    }

