"""The rooming list: who sleeps where, which nights (docs/producer-documents-map.md
§1.5, §2.2). Pure — no database. The router fetches, this decides.

Away, per person (job_hires.away), the same "default plus exceptions" idea as
dates_override:
    None   away on every date they have — a traveller, the usual case
    []     local: never away, no nights
    spans  away only then ("local except the brand B leg")

A NIGHT is an away date that isn't the last of its run: someone away Oct 19–23
sleeps the nights of the 19th–22nd and checks out on the 23rd. A single away
day (in and out the same day) has no night — still per diem later, no room.

Hand edits (job_hires.room_overrides, {date: value}) cover what the rule
can't know: "night" adds one, "none" takes one away, "late" marks a late
check-out on that date.

Hotels (jobs.hotels) are stays with dates, so a hotel move mid-job is two
stays. A night belongs to the stay whose [check_in, check_out) holds it.

Extra rooms — rooms that aren't a person's, like the producer's merch room — live on
the stay they're booked at (hotel["rooms"]): a label, a note, a reservation,
the nights booked and any late check-out. They count as rooms a night; the
breakfast count is people only.

⚠️ This document goes to the HOTEL. Its rows carry a name, the room note and
the reservation number — never a phone, an email, a rate or per diem. Tests
assert it (test_rooming.py).
"""

import uuid
from datetime import date, timedelta

from services.holds import is_booked
from services.job_dates import DAY_TYPES, DatesError, _days, _iso, effective_dates, hire_base, validate_dates

OVERRIDES = ("night", "none", "late")
HOTEL_FIELDS = ("name", "address", "phone", "contact")
TEXT_MAX = 200


def _day(iso: str) -> date:
    return date.fromisoformat(iso)


def _next(iso: str) -> str:
    return (_day(iso) + timedelta(days=1)).isoformat()


# ── Shape ────────────────────────────────────────────────────────────────────

def validate_away(value):
    """None (away on all their dates), [] (local) or a list of spans."""
    if value is None:
        return None
    return validate_dates({"shoot": value})["shoot"] if value else []


def validate_overrides(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DatesError("Room edits must be an object keyed by date.")
    out = {}
    for key, v in value.items():
        d = _iso(key).isoformat()
        if v is None:
            continue
        if v not in OVERRIDES:
            raise DatesError(f"A room edit is one of {', '.join(OVERRIDES)}.")
        out[d] = v
    return out


def validate_hotels(value) -> list[dict]:
    """The job's stays, each {id, name, address, phone, contact, check_in,
    check_out}; a new one gets an id. Check-out must be after check-in."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise DatesError("Hotels must be a list.")
    out = []
    for h in value:
        if not isinstance(h, dict):
            raise DatesError("Each hotel must be an object.")
        a, b = _iso(h.get("check_in")), _iso(h.get("check_out"))
        if (b - a).days > 120:
            raise DatesError("A hotel stay can't run longer than 120 nights.")
        if b <= a:
            raise DatesError("A hotel's check-out must be after its check-in.")
        clean = {"id": str(h.get("id") or uuid.uuid4()), "check_in": a.isoformat(), "check_out": b.isoformat()}
        for f in HOTEL_FIELDS:
            v = h.get(f)
            if v is not None and not isinstance(v, str):
                raise DatesError(f"A hotel's {f} must be text.")
            v = " ".join((v or "").split())
            if len(v) > TEXT_MAX:
                raise DatesError(f"Keep a hotel's {f} under {TEXT_MAX} characters.")
            clean[f] = v or None
        clean["rooms"] = validate_rooms(h.get("rooms"), clean["check_in"], clean["check_out"])
        out.append(clean)
    return sorted(out, key=lambda h: (h["check_in"], h["check_out"]))


ROOMS_MAX = 20


def _text(value, what: str, limit: int = TEXT_MAX) -> str:
    if value is not None and not isinstance(value, str):
        raise DatesError(f"A room's {what} must be text.")
    v = " ".join((value or "").split())
    if len(v) > limit:
        raise DatesError(f"Keep a room's {what} under {limit} characters.")
    return v


def validate_rooms(value, check_in: str, check_out: str) -> list[dict]:
    """A stay's extra rooms, each {id, label, notes, reservation, nights,
    late}. Nights must fall in the stay — [check_in, check_out) — and a late
    check-out on a day after one of them, within the stay."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise DatesError("A hotel's rooms must be a list.")
    if len(value) > ROOMS_MAX:
        raise DatesError(f"That's more than {ROOMS_MAX} extra rooms at one hotel.")
    out = []
    for r in value:
        if not isinstance(r, dict):
            raise DatesError("Each room must be an object.")
        label = _text(r.get("label"), "name")
        if not label:
            raise DatesError("Give each extra room a name, like Merch room.")
        nights = sorted({_iso(d).isoformat() for d in (r.get("nights") or [])})
        if any(not (check_in <= d < check_out) for d in nights):
            raise DatesError(f"{label}'s nights must fall inside its hotel stay.")
        late = sorted({_iso(d).isoformat() for d in (r.get("late") or [])})
        if any(not (check_in < d <= check_out) for d in late):
            raise DatesError(f"{label}'s late check-out must fall inside its hotel stay.")
        out.append({"id": str(r.get("id") or uuid.uuid4()), "label": label,
                    "notes": _text(r.get("notes"), "note") or None,
                    "reservation": _text(r.get("reservation"), "reservation number", 80) or None,
                    "nights": nights, "late": late})
    return out


# ── Nights ───────────────────────────────────────────────────────────────────

def their_dates(crew_dates: dict | None, override: dict | None) -> list[str]:
    """Every date this person has, of any type, in order."""
    eff = effective_dates(crew_dates, override)
    return sorted({d.isoformat() for t in DAY_TYPES for d in _days(eff[t])})


def away_dates(crew_dates: dict | None, override: dict | None, away) -> list[str]:
    mine = their_dates(crew_dates, override)
    if away is None:
        return mine
    inside = {d.isoformat() for d in _days(away)}
    return [d for d in mine if d in inside]


def runs(dates: list[str]) -> list[list[str]]:
    """Consecutive dates grouped: [[19, 20, 21], [25, 26]]."""
    out: list[list[str]] = []
    for d in sorted(dates):
        if out and _next(out[-1][-1]) == d:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def nights(crew_dates: dict | None, override: dict | None, away, overrides: dict | None) -> tuple[list[str], set[str]]:
    """(the nights they sleep in a hotel, the dates marked late check-out).
    The rule first — every away date but the last of its run — then the
    producer's hand edits on top."""
    base = {d for run in runs(away_dates(crew_dates, override, away)) for d in run[:-1]}
    overrides = overrides or {}
    for d, v in overrides.items():
        if v == "night":
            base.add(d)
        elif v == "none":
            base.discard(d)
    late = {d for d, v in overrides.items() if v == "late"}
    return sorted(base), late


# ── The sheet ────────────────────────────────────────────────────────────────

def _span(a: str, b: str) -> list[str]:
    return [d.isoformat() for d in _days([[a, b]])]


def _header(job: dict, day: str) -> dict:
    crew = job.get("crew_dates") or {}
    types = [t for t in DAY_TYPES if any(a <= day <= b for a, b in crew.get(t, []))]
    return {"date": day, "types": types, "label": (job.get("day_labels") or {}).get(day)}


def _cells(nights: list[str], late: set[str], check_out: str) -> dict:
    """1 on each night, c/o the day after each run of them (inside the stay),
    late c/o where it was marked late."""
    cells = {n: "1" for n in nights}
    for run in runs(nights):
        out_day = _next(run[-1])
        if out_day <= check_out:
            cells[out_day] = "late c/o" if out_day in late else "c/o"
    return cells


def build_sheets(job: dict, hires: list[dict]) -> dict:
    """One sheet per hotel stay: its dates, a row per person with a night or a
    check-out in it, and the totals. Nights no stay covers come back as
    `unplaced` so the screen can say so. With no hotels yet, one sheet over the
    whole run of nights, with `hotel` None."""
    people = []
    for h in hires:
        if not is_booked(h):        # a hold or a release books no room
            continue
        ns, late = nights(hire_base(job, h), h.get("dates_override"), h.get("away"), h.get("room_overrides"))
        people.append((h, ns, late))
    hotels = job.get("hotels") or []
    every = sorted({n for _h, ns, _l in people for n in ns})

    if hotels:
        stays = [(s, s["check_in"], s["check_out"]) for s in hotels]
    elif every:
        stays = [(None, every[0], _next(every[-1]))]
    else:
        stays = []

    sheets, placed = [], set()
    for stay, ci, co in stays:
        cols = _span(ci, co)
        rows = []
        for h, ns, late in people:
            here = [n for n in ns if ci <= n < co]
            if not here:
                continue
            placed.update((h["id"], n) for n in here)
            rows.append({
                "kind": "person", "hire_id": h["id"], "room_id": None, "name": h.get("name"),
                "notes": h.get("room_notes") or "",
                "reservation": ((h.get("reservations") or {}).get(stay["id"]) if stay else None) or "",
                "cells": _cells(here, set(late), co), "total": len(here),
            })
        for room in (stay or {}).get("rooms") or []:
            here = [n for n in room.get("nights") or [] if ci <= n < co]
            rows.append({
                "kind": "room", "hire_id": None, "room_id": room["id"], "name": room["label"],
                "notes": room.get("notes") or "", "reservation": room.get("reservation") or "",
                "cells": _cells(here, set(room.get("late") or []), co), "total": len(here),
            })
        sheets.append({
            "hotel": stay,
            "dates": [_header(job, d) for d in cols],
            "rows": rows,
            # Rooms booked a night, extra rooms included...
            "totals": {d: sum(1 for r in rows if r["cells"].get(d) == "1") for d in cols},
            # ...and heads a night, the hotel's breakfast count: people only.
            "breakfasts": {d: sum(1 for r in rows if r["kind"] == "person" and r["cells"].get(d) == "1") for d in cols},
            "total": sum(r["total"] for r in rows),
        })

    unplaced = [{"hire_id": h["id"], "name": h.get("name"), "date": n}
                for h, ns, _l in people for n in ns if hotels and (h["id"], n) not in placed]
    return {"sheets": sheets, "unplaced": unplaced}
