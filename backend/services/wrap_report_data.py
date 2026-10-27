"""The figures behind a wrap report. No rendering, no database, no model.

Pure functions of their arguments, so the arithmetic — spans, groupings, the
timeline scale — can be tested without a browser or a project. That matters more
here than it did for the call sheet: a call sheet mostly relays what a producer
typed, while this computes things nobody typed, and computed numbers are where
the bugs live.

⚠️ One rule from the plan, and it is a product rule rather than a technical one:
prefer the figure that changes what a producer does tomorrow over the figure that
flatters the tool. Median time-to-confirm was the first draft's centrepiece and
was cut for being trivia — *who did not confirm* replaced it, because that is a
text message someone can send. Resist adding averages back.

Contact details are deliberately absent. The Roster holds those and keeps them
current; a wrap report freezes whatever was true that week, so copying them here
would create a stale second address book.
"""

from datetime import date

from services.call_sheet_data import _meal_plan  # one definition of "what meals were on the day"
from time_utils import display_call_time, to_display_time

#: Anything shorter reads as a rounding artefact rather than a day.
_MIN_DAY_MINUTES = 30


def _minutes(value) -> int | None:
    """Postgres time (or 'HH:MM') to minutes past midnight."""
    if not value:
        return None
    parts = str(value).split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


def _span(minutes: int | None) -> str | None:
    """135 -> '2h 15m'. Whole hours drop the minutes."""
    if minutes is None or minutes < 0:
        return None
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def _group_by_department(crew: list) -> list[dict]:
    """Departments in the order the producer arranged them, undepartmented last.

    Same rule as the call sheet: first-appearance order, because the array is
    already in the order they chose and that order is the point.
    """
    groups: dict = {}
    loose: list = []
    for member in crew:
        label = (member.get("department") or "").strip()
        (groups.setdefault(label, []) if label else loose).append(member)
    out = [{"label": label, "people": people} for label, people in groups.items()]
    if loose:
        out.append({"label": None, "people": loose})
    return out


def _person(row: dict, confirmable: bool = True) -> dict:
    """What the report shows about someone. Name, role, call, confirmed — and
    deliberately no phone or email; see the module docstring.

    `confirmable` is False for talent, and it is not a detail. Only
    crew_members carries a confirmation_token; the talent table has no
    confirmed_at column, so talent are never asked and can never answer.
    Without this they rendered as a dash beside everyone who ignored the
    sheet, and landed in the "never confirmed" callout — accusing three people
    of missing a message nobody sent them.
    """
    return {
        "name": (row.get("name") or "").strip(),
        "role": (row.get("role") or "").strip() or None,
        "department": (row.get("department") or "").strip() or None,
        "call": display_call_time(row.get("call_time"), row.get("call_time_note")),
        "confirmable": confirmable,
        "confirmed": bool(row.get("confirmed_at")) if confirmable else False,
    }


def _timeline(schedule: list, moves: list, meals: dict | None,
              day_start: int | None, day_end: int | None) -> dict | None:
    """The day drawn to a real time axis.

    Positions come back as percentages rather than pixels so the template can lay
    it out with CSS and stay responsive — the mockup used a fixed SVG viewBox,
    which meant recomputing coordinates for every width.

    Returns None when there is no span to draw. A timeline of one block is not a
    shape, and an axis with nothing on it is worse than no axis.
    """
    if day_start is None or day_end is None or day_end - day_start < _MIN_DAY_MINUTES:
        return None
    total = day_end - day_start

    def pct(minute: int) -> float:
        return round((minute - day_start) / total * 100, 3)

    blocks = []
    for item in schedule:
        start = _minutes(item.get("start_time"))
        if start is None:
            continue
        end = _minutes(item.get("end_time"))
        # A block with no end still deserves a mark: give it a hairline rather
        # than dropping the producer's own schedule line off the picture.
        end = end if end is not None and end > start else start + 5
        start, end = max(start, day_start), min(end, day_end)
        if end <= start:
            continue
        blocks.append({
            "label": (item.get("description") or "").strip() or "Scheduled",
            "left": pct(start), "width": round(pct(end) - pct(start), 3),
            "start": to_display_time(item.get("start_time")),
            "kind": "meal" if "lunch" in (item.get("description") or "").lower()
                    or "breakfast" in (item.get("description") or "").lower() else "shoot",
        })

    markers = []
    for move in moves:
        at = _minutes(move.get("move_time"))
        if at is not None and day_start <= at <= day_end:
            markers.append({
                "label": (move.get("label") or move.get("location_name") or "Company move").strip(),
                "left": pct(at), "kind": "move",
                "at": to_display_time(move.get("move_time")),
            })

    # Hour ticks, on the hour, inside the span.
    ticks = []
    hour = (day_start // 60 + 1) * 60
    while hour < day_end:
        h = (hour // 60) % 24
        ticks.append({"left": pct(hour),
                      "label": f"{(h % 12) or 12}{'a' if h < 12 else 'p'}"})
        hour += 60

    return {"blocks": blocks, "markers": markers, "ticks": ticks,
            "start": to_display_time(f"{day_start // 60:02d}:{day_start % 60:02d}"),
            "end": to_display_time(f"{day_end // 60:02d}:{day_end % 60:02d}")}


def build_wrap_data(project: dict, crew: list, talent: list, schedule: list,
                    location: dict | None, moves: list, meals: dict | None,
                    accommodation: dict | None, call_sheet: dict | None,
                    attachments: list) -> dict:
    """Everything the wrap report template renders."""
    crew = crew or []
    talent = talent or []
    # An accommodation row can exist with every field blank — saving the form and
    # then clearing it leaves one behind — so presence isn't enough to print it.
    # Same rule as the call sheet, resolved here so the template can just ask
    # whether there is a hotel.
    if accommodation and not (accommodation.get("hotel_name") or accommodation.get("address")):
        accommodation = None
    people = [_person(r) for r in crew]
    talent_people = [_person(r, confirmable=False) for r in talent]
    everyone = people + talent_people

    # Confirmations are a crew-only story — see _person.
    confirmed = [p for p in people if p["confirmed"]]
    unconfirmed = [p for p in people if not p["confirmed"]]

    call_minutes = [m for m in (_minutes(r.get("call_time")) for r in crew + talent) if m is not None]
    first_call = _minutes(project.get("first_call_time")) or (min(call_minutes) if call_minutes else None)
    est_wrap = _minutes(project.get("est_wrap_time"))

    sched_starts = [m for m in (_minutes(s.get("start_time")) for s in schedule or []) if m is not None]
    sched_ends = [m for m in (_minutes(s.get("end_time")) for s in schedule or []) if m is not None]

    day_start = min([m for m in [first_call] + sched_starts + call_minutes if m is not None], default=None)
    day_end = max([m for m in [est_wrap] + sched_ends if m is not None], default=None)

    return {
        "project": {
            "name": (project.get("name") or "").strip(),
            "shoot_date": project.get("shoot_date"),
            "first_call": to_display_time(project.get("first_call_time")),
            "first_shot": to_display_time(project.get("first_shot_time")),
            "est_wrap": to_display_time(project.get("est_wrap_time")),
            "day_length": _span(day_end - day_start) if (day_start is not None and day_end is not None) else None,
        },
        "headcount": {
            "crew": len(people),
            "talent": len(talent_people),
            "departments": len([g for g in _group_by_department(crew) if g["label"]]),
            "on_call_sheet": len(everyone),
        },
        "confirmations": {
            "confirmed": len(confirmed),
            "total": len(people),
            # The actionable half, and the only part of this block that earns its
            # place. Named, so it is a text a producer can send.
            "missing": [{"name": p["name"], "role": p["role"], "department": p["department"]}
                        for p in unconfirmed],
            "sent_at": (call_sheet or {}).get("sent_at"),
        },
        "call_spread": _span(max(call_minutes) - min(call_minutes)) if len(call_minutes) > 1 else None,
        "earliest_call": to_display_time(f"{min(call_minutes) // 60:02d}:{min(call_minutes) % 60:02d}") if call_minutes else None,
        "latest_call": to_display_time(f"{max(call_minutes) // 60:02d}:{max(call_minutes) % 60:02d}") if call_minutes else None,
        "departments": [
            {"label": g["label"], "count": len(g["people"]),
             "people": [_person(r) for r in g["people"]]}
            for g in _group_by_department(crew)
        ],
        "talent": talent_people,
        "timeline": _timeline(schedule or [], moves or [], meals, day_start, day_end),
        "location": location,
        "moves": moves or [],
        "meal_plan": _meal_plan(meals),
        "accommodation": accommodation,
        "attachments": [{"filename": a.get("filename")} for a in (attachments or [])],
        "wants_pdf": sum(1 for r in crew if r.get("wants_pdf")),
    }


def is_wrapped(project: dict, today: date | None = None) -> bool:
    """Has this shoot happened? A project with no date has not.

    Same definition roster_sync uses for the opposite purpose, and deliberately
    so — there should be one answer in the codebase to "is this job over".
    """
    shoot = project.get("shoot_date")
    if not shoot:
        return False
    return str(shoot)[:10] < (today or date.today()).isoformat()
