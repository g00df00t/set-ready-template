"""The per-talent call sheet for agents (docs/producer-documents-map.md §1.8): the
minimum one talent needs, on one page, sent to their agent before travel.
Pure — the router fetches the job, the hire, their days and the weather; this
lays it out.

One sheet per talent per JOB, covering every day they have (Patrick,
2026-10-02): their dates as the deal memo's date lines, their flights, the
hotel nights they're booked for, and a block for each shoot day they're on with
call time, location, meals and weather. Most talent have one day, so it reads
like the producer's single-day sheet.

Who to call: the producer, always, with the job's producer number — then only
the crew the producer ticked for this job (jobs.talent_sheet.contacts). Nobody
else's number reaches an agency. ⚠️ No rate, fee or per diem ever goes on it:
it's read by the talent's agent, and test_talent_call_sheet.py asserts that.
"""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.holds import is_booked
from services.job_dates import DatesError, dates_block, hire_base
from services.rooming import nights
from services.travel import lands_on, plan_text
from time_utils import to_display_time

TEXT_MAX = 600
CONTACTS_MAX = 12
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _text(value, what: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DatesError(f"The {what} must be text.")
    # Keep line breaks — a prep list is usually one item a line — but tidy each.
    lines = [" ".join(line.split()) for line in (value or "").splitlines()]
    v = "\n".join(line for line in lines if line).strip()
    if len(v) > TEXT_MAX:
        raise DatesError(f"Keep the {what} under {TEXT_MAX} characters.")
    return v or None


def validate_settings(value, hire_ids: set[str]) -> dict:
    """{contacts, hotel_note, prep_note, notes}. A contact must be a crew hire
    on this job; duplicates collapse, order is kept."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DatesError("Talent sheet settings must be an object.")
    contacts = []
    for c in value.get("contacts") or []:
        c = str(c)
        if c not in hire_ids:
            raise DatesError("A contact must be someone hired on this job.")
        if c not in contacts:
            contacts.append(c)
    if len(contacts) > CONTACTS_MAX:
        raise DatesError(f"Pick at most {CONTACTS_MAX} people to call.")
    return {"contacts": contacts,
            "hotel_note": _text(value.get("hotel_note"), "hotel note"),
            "prep_note": _text(value.get("prep_note"), "talent prep note"),
            "notes": _text(value.get("notes"), "other info")}


def settings_of(job: dict) -> dict:
    s = job.get("talent_sheet") or {}
    return {"contacts": list(s.get("contacts") or []), "hotel_note": s.get("hotel_note"),
            "prep_note": s.get("prep_note"), "notes": s.get("notes")}


def talent_hires(hires: list[dict]) -> list[dict]:
    """Who gets a sheet: booked talent. A hold gets one once confirmed."""
    return [h for h in hires if h.get("kind") == "talent" and is_booked(h)]


# ── Pieces ───────────────────────────────────────────────────────────────────

def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{_WEEKDAYS[d.weekday()]}, {d.strftime('%b')} {d.day}"


def _t(hhmm) -> str:
    return to_display_time(hhmm) or ""


def leg_line(leg: dict, names: dict[str, str]) -> str:
    """"Arrives Tue, Oct 13 — Delta DL 401, PDX 7:00 AM to EWR 3:20 PM. Car service".
    "to", not an arrow: this prints through the server's PDF fonts, which
    dropped ✓ — plain words can't go blank."""
    arriving = leg["direction"] == "in"
    when = _day(lands_on(leg) if arriving else leg["date"])
    flight = " ".join(x for x in (leg.get("carrier"), leg.get("flight")) if x)
    a = " ".join(x for x in (leg.get("from_airport"), _t(leg.get("depart_time"))) if x)
    b = " ".join(x for x in (leg.get("to_airport"), _t(leg.get("arrive_time"))) if x)
    route = f"{a} to {b}" if a and b else (f"from {a}" if a else (f"to {b}" if b else ""))
    detail = ", ".join(x for x in (flight, route) if x)
    line = f"{'Arrives' if arriving else 'Leaves'} {when}"
    if detail:
        line += f" — {detail}"
    how = plan_text(leg, names)
    return f"{line}. {how}" if how else line


def hotel_stays(job: dict, hire: dict) -> list[dict]:
    """The job's hotels this person has nights at, with their own in/out dates."""
    ns, _late = nights(hire_base(job, hire), hire.get("dates_override"), hire.get("away"), hire.get("room_overrides"))
    out = []
    for stay in job.get("hotels") or []:
        here = [n for n in ns if stay["check_in"] <= n < stay["check_out"]]
        if not here:
            continue
        last = date.fromisoformat(here[-1]).toordinal() + 1
        out.append({"name": stay.get("name") or "Hotel", "address": stay.get("address") or "",
                    "phone": stay.get("phone") or "", "check_in": _day(here[0]),
                    "check_out": _day(date.fromordinal(last).isoformat()), "nights": len(here)})
    return out


def call_text(talent_row: dict | None) -> str:
    """Their call time and the note beside it ("meet at basecamp"); a named
    call ("TBD") with no time reads on its own."""
    if not talent_row:
        return ""
    t = _t(talent_row.get("call_time"))
    note = (talent_row.get("call_time_note") or "").strip()
    return " — ".join(x for x in (t, note) if x)


def meals_text(meals: dict | None) -> str:
    if not meals:
        return ""
    out = []
    for key, label in (("breakfast", "Breakfast"), ("lunch", "Lunch")):
        a, b = _t(meals.get(f"{key}_start")), _t(meals.get(f"{key}_end"))
        when = f"{a}–{b}" if a and b else (a or b)
        note = (meals.get(f"{key}_notes") or "").strip()
        if when or note:
            out.append(" ".join(x for x in (label, when, f"({note})" if note else "") if x))
    return " · ".join(out)


def weather_text(w: dict | None) -> str:
    if not w:
        return ""
    bits = [w.get("condition") or ""]
    if isinstance(w.get("high_f"), (int, float)) and isinstance(w.get("low_f"), (int, float)):
        bits.append(f"High {w['high_f']}°F / Low {w['low_f']}°F")
    if w.get("precipitation_chance"):
        bits.append(f"{w['precipitation_chance']}% chance of rain")
    if w.get("sunrise"):
        bits.append(f"Sunrise {w['sunrise']}")
    return " · ".join(b for b in bits if b)


def contacts(job: dict, hires: list[dict], producer: dict) -> list[dict]:
    """The producer first, then the ticked crew in the order ticked. A ticked
    person who was released, put back on hold, or removed, drops off: an
    agent is only ever given the number of someone actually on the job."""
    by_id = {h["id"]: h for h in hires}
    out = [{"name": producer.get("name") or "Producer", "role": "Producer",
            "phone": (job.get("producer_phone") or "").strip(), "email": producer.get("email") or ""}]
    for hid in settings_of(job)["contacts"]:
        h = by_id.get(hid)
        if not h or not is_booked(h):
            continue
        out.append({"name": h.get("name") or "", "role": h.get("role") or "",
                    "phone": (h.get("phone") or "").strip(), "email": ""})
    return out


# ── The sheet ────────────────────────────────────────────────────────────────

def build_sheet(job: dict, hire: dict, *, roster: dict | None, hires: list[dict],
                days: list[dict], producer: dict) -> dict:
    """`days`: the shoot days this talent is on, each {project, location,
    talent_row, meals, weather}, in date order."""
    roster = roster or {}
    s = settings_of(job)
    names = {h["id"]: h.get("name") or "" for h in hires}
    lines = dates_block(hire_base(job, hire), hire.get("dates_override"),
                        job.get("day_labels"), hire.get("day_notes"), "talent")
    shoot_days = []
    for d in days:
        p, loc = d["project"], d.get("location") or {}
        shoot_days.append({
            "date": _day(p["shoot_date"]) if p.get("shoot_date") else "Date to come",
            "label": (job.get("day_labels") or {}).get(p.get("shoot_date") or "") or "",
            "call": call_text(d.get("talent_row")),
            "location": loc.get("location_name") or "",
            "address": loc.get("address") or "",
            "parking": loc.get("parking_notes") or "",
            "meals": meals_text(d.get("meals")),
            "weather": weather_text(d.get("weather")),
        })
    return {
        "title": f"{hire.get('name') or 'Talent'} - {job.get('name') or 'Job'}",
        "talent": hire.get("name") or "",
        "agency": roster.get("agency") or "",
        "agent": roster.get("agent_name") or "",
        "job": job.get("name") or "",
        "client": job.get("client_name") or "",
        "bill_to": job.get("payroll_provider") or "",
        "dates": [line for line in lines.split("\n") if line],
        "travel": [leg_line(leg, names) for leg in hire.get("travel_legs") or []],
        "hotels": hotel_stays(job, hire),
        "hotel_note": s["hotel_note"] or "",
        "shoot_days": shoot_days,
        "contacts": contacts(job, hires, producer),
        "prep_note": s["prep_note"] or "",
        "notes": s["notes"] or "",
    }


def gaps(job: dict, hire: dict, days: list[dict]) -> list[str]:
    """What's still missing from this talent's sheet, for the screen. Never a
    reason to refuse a download."""
    out = []
    if not days:
        out.append("Not on any shoot day's talent list yet")
    elif any(not call_text(d.get("talent_row")) for d in days):
        out.append("No call time on a shoot day")
    if not (hire.get("travel_legs") or []) and hire.get("away") != []:
        out.append("No flights")
    if not (job.get("producer_phone") or "").strip():
        out.append("No producer number (set it on Travel)")
    return out


# ── Rendering ────────────────────────────────────────────────────────────────
# PDF only, so a <style> block is fine here — unlike the emailed call sheet.

_env: Environment | None = None


def to_html(sheet: dict) -> str:
    global _env
    if _env is None:
        _env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                           autoescape=select_autoescape(["html", "j2", "html.j2"], default=True),
                           trim_blocks=True, lstrip_blocks=True)
    return _env.get_template("talent_call_sheet.html.j2").render(s=sheet)
