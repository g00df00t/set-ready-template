"""Travel: each person's flights in and out, and the two views built from them
(docs/producer-documents-map.md §1.7). Pure — no database. The router fetches,
this decides.

A LEG is one journey, an arrival ("in") or a departure ("out"), stored on the
hire (job_hires.travel_legs). A connection is still one leg: the car service
only cares where they finally land, so both flight numbers go in one field.
Anyone can have any number — a mid-job fly-in for brand B is just a second
pair. Not a booking tool: nothing here buys or checks a flight.

Three things are built from the legs, booked people only (holds.is_booked):
    the travel doc     her sheet: ARRIVALS, then DEPARTURES. No phones
    the manifest       legs planned as car service, both directions, WITH a
                       phone — the person's own, or the producer's for anyone
                       switched to it (Q9). Talent default to the producer's,
                       crew to their own, the same split hide_contact makes
    arrival groups     who lands at the same airport within WINDOW_MINUTES of
                       the first of them, so people renting cars can give
                       rides. On screen only

A leg's date is also checked against the person's away dates (Rooming): an
arrival should land on the first day of a run of them, a departure leave on
the last. Those are notes on screen, never a refusal — people fly in the night
before.
"""

import uuid
from datetime import date, datetime

from services.holds import is_booked
from services.job_dates import DatesError, _iso, hire_base
from services.rooming import away_dates, runs
from time_utils import to_display_time

DIRECTIONS = ("in", "out")
PLANS = {"car_service": "Car service", "rental": "Rental car", "ride": "Ride", "own": "Own way"}
LEGS_MAX = 10
TEXT_MAX = 200
SHORT_MAX = 40
WINDOW_MINUTES = 60

_TIME_FORMATS = ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M:%S", "%H:%M")


# ── Shape ────────────────────────────────────────────────────────────────────

def _time(value, what: str) -> str | None:
    """"8:05 PM", "20:05" or "" → "20:05" or None."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise DatesError(f"The {what} must be text like 8:05 PM.")
    cleaned = " ".join(value.replace(".", "").upper().split())
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise DatesError(f'"{value}" isn\'t a time. Try 8:05 PM or 20:05.')


def _text(value, what: str, limit: int) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DatesError(f"The {what} must be text.")
    v = " ".join((value or "").split())
    if len(v) > limit:
        raise DatesError(f"Keep the {what} under {limit} characters.")
    return v or None


def _code(value, what: str) -> str | None:
    """An airport: "ewr" → "EWR"; a name ("Newark") is left as typed."""
    v = _text(value, what, SHORT_MAX)
    return v.upper() if v and len(v) <= 4 and v.isalpha() else v


def validate_legs(value, hire_ids: set[str] | None = None, own_id: str | None = None) -> list[dict]:
    """A person's legs, normalised and in travel order. `hire_ids` (the job's
    hires) is what "ride with" may point at; a ride with yourself is refused."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise DatesError("Travel must be a list of legs.")
    if len(value) > LEGS_MAX:
        raise DatesError(f"That's more than {LEGS_MAX} legs for one person.")
    out = []
    for leg in value:
        if not isinstance(leg, dict):
            raise DatesError("Each leg must be an object.")
        direction = leg.get("direction")
        if direction not in DIRECTIONS:
            raise DatesError("A leg is an arrival or a departure.")
        day = _iso(leg.get("date")).isoformat()
        arrive_date = leg.get("arrive_date")
        arrive_date = _iso(arrive_date).isoformat() if arrive_date else None
        if arrive_date and arrive_date < day:
            raise DatesError("A flight can't land before the day it leaves.")
        if arrive_date and (date.fromisoformat(arrive_date) - date.fromisoformat(day)).days > 2:
            raise DatesError("A flight's landing date is more than two days after it leaves.")
        plan = leg.get("plan") or None
        if plan is not None and plan not in PLANS:
            raise DatesError("Transportation is car service, rental car, a ride or their own way.")
        ride_with = leg.get("ride_with") or None
        if plan != "ride":
            ride_with = None
        elif ride_with is not None:
            ride_with = str(ride_with)
            if ride_with == own_id:
                raise DatesError("Someone can't ride with themselves.")
            if hire_ids is not None and ride_with not in hire_ids:
                raise DatesError("That ride is with someone who isn't on this job.")
        clean = {
            "id": str(leg.get("id") or uuid.uuid4()),
            "direction": direction,
            "date": day,
            "carrier": _text(leg.get("carrier"), "airline", SHORT_MAX),
            "flight": _text(leg.get("flight"), "flight number", SHORT_MAX),
            "from_airport": _code(leg.get("from_airport"), "departure airport"),
            "depart_time": _time(leg.get("depart_time"), "departure time"),
            "arrive_date": None if arrive_date == day else arrive_date,
            "to_airport": _code(leg.get("to_airport"), "arrival airport"),
            "arrive_time": _time(leg.get("arrive_time"), "arrival time"),
            "plan": plan,
            "ride_with": ride_with,
            "note": _text(leg.get("note"), "note", TEXT_MAX),
        }
        out.append(clean)
    return sorted(out, key=lambda leg: (leg["date"], leg["depart_time"] or "", leg["direction"]))


# ── Reading a leg ────────────────────────────────────────────────────────────

def lands_on(leg: dict) -> str:
    return leg.get("arrive_date") or leg["date"]


def uses_producer_phone(hire: dict) -> bool:
    """The car service gets the producer's number for this person: their own
    choice if they made one, else talent yes and crew no."""
    chosen = hire.get("car_service_producer_phone")
    if chosen is not None:
        return bool(chosen)
    return (hire.get("kind") or "crew") == "talent"


def plan_text(leg: dict, names: dict[str, str]) -> str:
    """"Car service", "Ride with Sam Ortiz", "Rental car — picks up Dee", …"""
    plan = leg.get("plan")
    if not plan:
        text = ""
    elif plan == "ride":
        other = names.get(leg.get("ride_with") or "")
        text = f"Ride with {other}" if other else "Ride"
    else:
        text = PLANS[plan]
    note = leg.get("note") or ""
    return f"{text} — {note}" if text and note else (text or note)


def _airport(value: str | None) -> str:
    return " ".join((value or "").upper().split())


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


# ── Checks ───────────────────────────────────────────────────────────────────

def _fmt(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"


def leg_warning(job: dict, hire: dict, leg: dict) -> str | None:
    """A quiet note when a flight's date doesn't meet the person's away dates.
    Away dates come from Rooming: an arrival should land on the first day of
    a run of them, a departure leave on the last."""
    away = away_dates(hire_base(job, hire), hire.get("dates_override"), hire.get("away"))
    if not away:
        if hire.get("away") == []:
            return "Set as local on Rooming, so no travel days to match."
        return "No dates on this job yet."
    spans = runs(away)
    if leg["direction"] == "in":
        day, ends = lands_on(leg), [r[0] for r in spans]
        if day in ends:
            return None
        return f"Lands {_fmt(day)}; their first day away is {_fmt(min(ends, key=lambda e: abs((date.fromisoformat(e) - date.fromisoformat(day)).days)))}."
    day, ends = leg["date"], [r[-1] for r in spans]
    if day in ends:
        return None
    return f"Leaves {_fmt(day)}; their last day away is {_fmt(min(ends, key=lambda e: abs((date.fromisoformat(e) - date.fromisoformat(day)).days)))}."


# ── The views ────────────────────────────────────────────────────────────────

def _row(job: dict, hire: dict, leg: dict, names: dict[str, str]) -> dict:
    return {
        "hire_id": hire["id"], "leg_id": leg["id"], "name": hire.get("name") or "",
        "role": hire.get("role") or "", "kind": hire.get("kind") or "crew",
        "direction": leg["direction"], "date": leg["date"], "carrier": leg.get("carrier") or "",
        "flight": leg.get("flight") or "", "from_airport": leg.get("from_airport") or "",
        "depart_time": leg.get("depart_time"), "arrive_date": lands_on(leg),
        "to_airport": leg.get("to_airport") or "", "arrive_time": leg.get("arrive_time"),
        "plan": leg.get("plan"), "plan_text": plan_text(leg, names),
        "warning": leg_warning(job, hire, leg),
    }


def build(job: dict, hires: list[dict]) -> dict:
    """Everything the tab and the documents read: arrivals and departures in
    time order, the car-service manifest, and arrival groups."""
    names = {h["id"]: h.get("name") or "" for h in hires}
    booked = [h for h in hires if is_booked(h)]
    rows = [_row(job, h, leg, names) for h in booked for leg in (h.get("travel_legs") or [])]

    arrivals = sorted((r for r in rows if r["direction"] == "in"),
                      key=lambda r: (r["arrive_date"], r["arrive_time"] or "99", r["name"]))
    departures = sorted((r for r in rows if r["direction"] == "out"),
                        key=lambda r: (r["date"], r["depart_time"] or "99", r["name"]))

    producer_phone = (job.get("producer_phone") or "").strip()
    by_id = {h["id"]: h for h in booked}
    manifest, missing_phone = [], []
    for r in arrivals + departures:
        if r["plan"] != "car_service":
            continue
        h = by_id[r["hire_id"]]
        producer = uses_producer_phone(h)
        phone = producer_phone if producer else (h.get("phone") or "").strip()
        if not phone and r["name"] not in missing_phone:
            missing_phone.append(r["name"])
        manifest.append({**r, "phone": phone, "phone_is_producer": producer})

    return {
        "arrivals": arrivals, "departures": departures,
        "manifest": manifest, "missing_phone": missing_phone,
        "groups": arrival_groups(arrivals),
        "producer_phone": producer_phone or None,
    }


def arrival_groups(arrivals: list[dict]) -> list[dict]:
    """Arrivals by airport and day, then split wherever a landing is more than
    WINDOW_MINUTES after the first one in its group. Landings with no time set
    gather in their own group at the end of that airport's day."""
    buckets: dict[tuple[str, str], list[dict]] = {}
    for r in arrivals:
        buckets.setdefault((r["arrive_date"], _airport(r["to_airport"])), []).append(r)
    groups = []
    for (day, airport), legs in sorted(buckets.items()):
        timed = sorted((r for r in legs if r["arrive_time"]), key=lambda r: r["arrive_time"])
        current: list[dict] = []
        for r in timed:
            if current and _minutes(r["arrive_time"]) - _minutes(current[0]["arrive_time"]) > WINDOW_MINUTES:
                groups.append(_group(day, airport, current))
                current = []
            current.append(r)
        if current:
            groups.append(_group(day, airport, current))
        untimed = [r for r in legs if not r["arrive_time"]]
        if untimed:
            groups.append(_group(day, airport, untimed))
    return groups


def _group(day: str, airport: str, legs: list[dict]) -> dict:
    times = [r["arrive_time"] for r in legs if r["arrive_time"]]
    return {
        "date": day, "airport": airport or None,
        "first": times[0] if times else None, "last": times[-1] if times else None,
        "people": [{"hire_id": r["hire_id"], "name": r["name"], "arrive_time": r["arrive_time"],
                    "flight": " ".join(x for x in (r["carrier"], r["flight"]) if x),
                    "plan": r["plan"], "plan_text": r["plan_text"]} for r in legs],
    }


def display_time(hhmm: str | None) -> str:
    return to_display_time(hhmm) or ""
