"""Rates on a hire, per diem on a job (docs/producer-documents-map.md §3–§4).

Pure: no database. The router fetches, this decides.

Where each lives, after the producer's answers of 2026-10-01:
- A hire carries the agreed deal: shoot, travel and prep/scout day rates plus
  a note. It's filled in when someone is hired — from their last job for the
  SAME CLIENT (rates change by client), else from the Master Roster — and from
  then on it belongs to the hire. Nothing rewrites it, so a sent memo can be
  regenerated exactly.
- A down day is always ½ the shoot rate, so it's a rule, not a field.
- The job carries per diem: one amount for shoot days, one for every other day
  (prep included), and how it's paid.

Rates are producer-only. They print on the deal memo and nowhere else — the
call sheet, its email and the confirm page never read job_hires' rate columns.
"""

import re

RATE_FIELDS = ("rate_shoot", "rate_travel", "rate_prep")

# Used when an account has never set its own (the producer's numbers).
DEFAULT_PER_DIEM = {"per_diem_shoot": 50, "per_diem_other": 70, "per_diem_paid_by": None}

_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")


def _num(value) -> float | None:
    """A stored amount as a number. PostgREST hands numeric back as a number
    or a string depending on the path; either is fine. Anything else is None."""
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def money(value) -> str:
    """$1,200 — cents only when there are any."""
    n = _num(value)
    if n is None:
        return ""
    return f"${n:,.2f}" if n != int(n) else f"${int(n):,}"


def has_rates(hire: dict) -> bool:
    return any(_num(hire.get(f)) is not None for f in RATE_FIELDS)


def _amount_after(text: str, words: str) -> float | None:
    m = re.search(rf"(?:{words})[^$\d]{{0,30}}" + _MONEY.pattern, text, re.IGNORECASE)
    if not m:
        return None
    whole, cents = m.group(1), m.group(2)
    return float(whole.replace(",", "") + (f".{cents}" if cents else ""))


def roster_rates(roster: dict | None) -> dict:
    """What the Master Roster's free-text rate says, as numbers.

    The Roster's day_rate is whatever the producer typed: "$650/day", "650",
    or the producer's "Shoot day rate = $1,200, Travel day rate = $600". So: an amount
    named for travel or prep is that; an amount named for shoot — or failing
    that the first amount at all — is the shoot rate. Prep defaults to the
    shoot rate (the producer: some get the full rate for prep, some half; full is the
    one that never underpays). Nothing readable → {}.
    """
    if not roster:
        return {}
    text = " ".join(t for t in (roster.get("day_rate"), roster.get("rate_note")) if t)
    if not text:
        return {}
    travel = _amount_after(text, "travel")
    prep = _amount_after(text, "prep|scout")
    shoot = _amount_after(text, "shoot")
    if shoot is None:
        first = _MONEY.search(roster.get("day_rate") or "")
        shoot = float(first.group(1).replace(",", "") + (f".{first.group(2)}" if first.group(2) else "")) if first else None
    out = {}
    if shoot is not None:
        out["rate_shoot"] = shoot
        out["rate_prep"] = prep if prep is not None else shoot
    elif prep is not None:
        out["rate_prep"] = prep
    if travel is not None:
        out["rate_travel"] = travel
    return out


def _same_client(a, b) -> bool:
    a, b = (a or "").strip().casefold(), (b or "").strip().casefold()
    return bool(a) and a == b


def suggest_rates(job: dict, roster: dict | None, past: list[tuple[dict, dict]]) -> dict | None:
    """What to fill a new hire's rates in with.

    `past` is (hire, job) pairs for the same person on the account's OTHER
    jobs. The most recent one for the same client that has a rate wins, note
    and all. Otherwise the Roster. None when neither has anything.
    """
    matches = [(h, j) for h, j in past
               if j.get("id") != job.get("id") and _same_client(j.get("client_name"), job.get("client_name"))
               and has_rates(h)]
    if matches:
        h, j = max(matches, key=lambda hj: (hj[1].get("created_at") or "", hj[0].get("created_at") or ""))
        out = {f: _num(h.get(f)) for f in RATE_FIELDS}
        out.update({"rate_note": h.get("rate_note"), "rate_source": "job",
                    "rate_source_job_id": j["id"], "rate_source_job_name": j.get("name")})
        return out
    from_roster = roster_rates(roster)
    if from_roster:
        return {**{f: from_roster.get(f) for f in RATE_FIELDS}, "rate_note": None,
                "rate_source": "roster", "rate_source_job_id": None}
    return None


def memo_rate_lines(hire: dict) -> str:
    """The deal memo's Rate block from the hire's own rates: only the ones that
    are set, no totals (doc §3.3). Then the note."""
    lines = [f"{label} day rate = {money(hire.get(f))}"
             for f, label in (("rate_shoot", "Shoot"), ("rate_travel", "Travel"), ("rate_prep", "Prep/Scout"))
             if _num(hire.get(f)) is not None]
    note = (hire.get("rate_note") or "").strip()
    return "\n".join(lines + ([note] if note else []))


def per_diem_text(job: dict) -> str:
    """The memo's Per Diem line, in the producer's own wording: "$70/non shoot day and
    $50/shoot day - paid via Venmo or cash". A job with no amounts set keeps
    its free-text line."""
    other, shoot = _num(job.get("per_diem_other")), _num(job.get("per_diem_shoot"))
    parts = []
    if other is not None:
        parts.append(f"{money(other)}/non shoot day")
    if shoot is not None:
        parts.append(f"{money(shoot)}/shoot day")
    if not parts:
        return (job.get("per_diem_line") or "").strip()
    paid = (job.get("per_diem_paid_by") or "").strip()
    return " and ".join(parts) + (f" - paid via {paid}" if paid else "")


def clean_defaults(meta_value) -> dict:
    """An account's job defaults, from user_metadata — which the browser can
    write, so every value is re-checked before it lands in a jobs row."""
    raw = meta_value if isinstance(meta_value, dict) else {}
    out = dict(DEFAULT_PER_DIEM)
    for f in ("per_diem_shoot", "per_diem_other"):
        if f in raw:
            n = _num(raw[f])
            out[f] = n if n is not None and n <= 100_000 else None
    if "per_diem_paid_by" in raw:
        paid = raw["per_diem_paid_by"]
        out["per_diem_paid_by"] = paid.strip()[:200] or None if isinstance(paid, str) else None
    return out
