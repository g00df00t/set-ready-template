"""Vendor bookings: the business side of everything a job books — the hotel,
each day's location, permits, the motorhome, caterers, rentals — with the producer's
four-step checklist (docs/producer-documents-map.md §1.9, §2.5). Pure: the router
fetches, this decides.

Stored on the job (jobs.vendors), one entry per booking:

    {id, kind, name, hotel_id, day_id, contact_name, contact_phone,
     contact_email, website, fee, fee_note, steps, notes}

LINK, DON'T COPY (Patrick, 2026-10-02). A hotel booking points at a Rooming
stay (hotel_id) and a location booking at a day (day_id); their name, address
and dates are read from those every time, so renaming the hotel on Rooming
renames it here. `name` is only for what stands on its own — a permit, the
motorhome, a caterer.

The checklist is a DATE per step (done = has a date), with an amount on the
two payments — what reconciliation will read later. The final bill is the
BALANCE after the deposit (Patrick, 2026-10-02): the PC log puts each payment
on its own line, so a whole-bill figure here would count the deposit twice:

    steps = {coi: {date}, agreement: {date}, deposit: {date, amount},
             final_bill: {date, amount}}

Caterers have no checklist on her sheet, so they get none here.
"""

import uuid
from datetime import date

from services.job_dates import DatesError, _iso

KINDS = {
    "hotel": "Hotel",
    "location": "Location",
    "permit": "Permit",
    "motorhome": "Motorhome",
    "caterer": "Caterer",
    "rentals": "Rentals",
    "other": "Other",
}
NO_CHECKLIST = ("caterer",)
STEPS = {"coi": "COI requested", "agreement": "Signed agreement", "deposit": "Deposit", "final_bill": "Final bill (balance)"}
MONEY_STEPS = ("deposit", "final_bill")
TEXT_FIELDS = {"name": 120, "contact_name": 120, "contact_phone": 40, "contact_email": 160,
               "website": 300, "fee_note": 200}
NOTES_MAX = 2000
VENDORS_MAX = 60


# ── Shape ────────────────────────────────────────────────────────────────────

def _text(value, what: str, limit: int) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DatesError(f"The {what} must be text.")
    v = " ".join((value or "").split())
    if len(v) > limit:
        raise DatesError(f"Keep the {what} under {limit} characters.")
    return v or None


def _amount(value, what: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise DatesError(f"The {what} must be a number.")
    if n < 0 or n > 10_000_000:
        raise DatesError(f"The {what} must be between 0 and 10,000,000.")
    return round(n, 2)


def _notes(value) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DatesError("Notes must be text.")
    lines = [" ".join(line.split()) for line in (value or "").splitlines()]
    v = "\n".join(lines).strip()
    if len(v) > NOTES_MAX:
        raise DatesError(f"Keep the notes under {NOTES_MAX} characters.")
    return v or None


def _website(value) -> str | None:
    """Only a web address — it renders as a link."""
    v = _text(value, "website", TEXT_FIELDS["website"])
    if v and not v.lower().startswith(("http://", "https://")):
        v = "https://" + v
    return v


def validate_steps(value, kind: str) -> dict:
    if kind in NO_CHECKLIST or not value:
        return {}
    if not isinstance(value, dict):
        raise DatesError("The checklist must be an object.")
    out = {}
    for key, step in value.items():
        if key not in STEPS:
            raise DatesError(f"{key!r} isn't a checklist step.")
        if not step:
            continue
        if not isinstance(step, dict):
            raise DatesError("Each checklist step must be an object.")
        clean = {"date": _iso(step.get("date")).isoformat() if step.get("date") else None}
        if key in MONEY_STEPS:
            clean["amount"] = _amount(step.get("amount"), STEPS[key].lower())
        if clean["date"] or clean.get("amount") is not None:
            out[key] = clean
    return out


def validate_vendor(value, hotel_ids: set[str], day_ids: set[str]) -> dict:
    """One booking, normalised, or DatesError. A hotel booking must point at
    one of the job's stays; a location booking at one of its days."""
    if not isinstance(value, dict):
        raise DatesError("A booking must be an object.")
    kind = value.get("kind")
    if kind not in KINDS:
        raise DatesError("Pick what kind of booking this is.")
    hotel_id = str(value["hotel_id"]) if value.get("hotel_id") else None
    day_id = str(value["day_id"]) if value.get("day_id") else None
    if kind == "hotel":
        if hotel_id not in hotel_ids:
            raise DatesError("Pick one of this job's hotels (add it on Rooming first).")
        day_id = None
    elif kind == "location":
        if day_id not in day_ids:
            raise DatesError("Pick the day this location is for.")
        hotel_id = None
    else:
        hotel_id = day_id = None
    out = {"id": str(value.get("id") or uuid.uuid4()), "kind": kind, "hotel_id": hotel_id, "day_id": day_id}
    for field, limit in TEXT_FIELDS.items():
        if field == "website":
            continue
        out[field] = _text(value.get(field), field.replace("_", " "), limit)
    if kind not in ("hotel", "location") and not out["name"]:
        raise DatesError(f"Give the {KINDS[kind].lower()} a name.")
    out["website"] = _website(value.get("website"))
    out["fee"] = _amount(value.get("fee"), "fee")
    out["steps"] = validate_steps(value.get("steps"), kind)
    out["notes"] = _notes(value.get("notes"))
    return out


# ── Reading a booking ────────────────────────────────────────────────────────

def _day_name(day: dict, location: dict | None) -> str:
    where = (location or {}).get("location_name") or (location or {}).get("address") or day.get("name") or "Day"
    return where


def resolve(job: dict, vendors: list[dict], days: list[dict], locations: dict) -> list[dict]:
    """Each booking with what it links to filled in: `title` (what it's
    called), `subtitle` (dates, address), and `missing` (checklist steps not
    done). `broken` when the stay or day it pointed at is gone."""
    hotels = {h["id"]: h for h in job.get("hotels") or []}
    by_day = {d["id"]: d for d in days}
    out = []
    for v in vendors:
        title, subtitle, broken = v.get("name") or "", "", False
        if v["kind"] == "hotel":
            h = hotels.get(v.get("hotel_id") or "")
            if h:
                title = h.get("name") or "Hotel"
                subtitle = " · ".join(x for x in (f"{_short(h['check_in'])} – {_short(h['check_out'])}", h.get("address")) if x)
            else:
                broken = True
        elif v["kind"] == "location":
            d = by_day.get(v.get("day_id") or "")
            if d:
                loc = locations.get(d["id"])
                title = _day_name(d, loc)
                bits = [_short(d["shoot_date"]) if d.get("shoot_date") else "No date", (loc or {}).get("address")]
                subtitle = " · ".join(x for x in bits if x)
            else:
                broken = True
        missing = [] if v["kind"] in NO_CHECKLIST else [k for k in STEPS if not (v.get("steps") or {}).get(k, {}).get("date")]
        out.append({**v, "title": title or KINDS[v["kind"]], "subtitle": subtitle, "broken": broken,
                    "missing": missing, "kind_label": KINDS[v["kind"]]})
    order = list(KINDS)
    return sorted(out, key=lambda v: (order.index(v["kind"]), v["subtitle"] if v["kind"] == "location" else "", v["title"].lower()))


def _short(iso: str) -> str:
    d = date.fromisoformat(str(iso))
    return f"{d.strftime('%b')} {d.day}"


def open_items(resolved: list[dict]) -> list[dict]:
    """What's still to do across the job: [{vendor_id, title, missing labels}]."""
    return [{"vendor_id": v["id"], "title": v["title"], "kind": v["kind_label"],
             "missing": [STEPS[k] for k in v["missing"]]}
            for v in resolved if v["missing"] and not v["broken"]]


def unbooked(job: dict, vendors: list[dict], days: list[dict], locations: dict) -> dict:
    """Stays and days with a location that have no booking yet — offered as
    one-click adds, so the hotel and each day's location don't get forgotten."""
    booked_hotels = {v.get("hotel_id") for v in vendors if v["kind"] == "hotel"}
    booked_days = {v.get("day_id") for v in vendors if v["kind"] == "location"}
    hotels = [{"hotel_id": h["id"], "title": h.get("name") or "Hotel",
               "subtitle": f"{_short(h['check_in'])} – {_short(h['check_out'])}"}
              for h in job.get("hotels") or [] if h["id"] not in booked_hotels]
    day_rows = []
    for d in days:
        loc = locations.get(d["id"])
        if d["id"] in booked_days or not loc or not (loc.get("location_name") or loc.get("address")):
            continue
        day_rows.append({"day_id": d["id"], "title": _day_name(d, loc),
                         "subtitle": _short(d["shoot_date"]) if d.get("shoot_date") else "No date"})
    return {"hotels": hotels, "days": day_rows}


# ── Usage dates ──────────────────────────────────────────────────────────────

USAGE = {"first_use": "Date of first use", "launch": "Launch date",
         "print_expiry": "Print expiration", "web_expiry": "Web expiration"}


def validate_usage(value) -> dict:
    """The job's four usage dates — the producer's reference only, printed
    on no document (the producer, Q11). Unknown keys refused; blanks dropped."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DatesError("Usage dates must be an object.")
    out = {}
    for k, v in value.items():
        if k not in USAGE:
            raise DatesError(f"{k!r} isn't a usage date.")
        if v:
            out[k] = _iso(v).isoformat()
    return out
