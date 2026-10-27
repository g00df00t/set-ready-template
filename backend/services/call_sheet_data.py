"""Assemble the call sheet's data. No rendering, no model, no side effects.

The boundary between what the database returns and what the renderer consumes.
Everything here is a pure function of its arguments, which is what lets
tests/fixtures.py hand the renderer thirteen hand-built shapes — including the
ones a real project rarely produces — without touching a database or an account.

Two rules are enforced here rather than downstream, and both are deliberate:
hidden contacts have their phone and email *removed* from the dict, and agency
details are stripped unconditionally. A value the renderer never receives is one
it cannot print, whatever a template edit does later. That mattered when a model
wrote the markup and it still matters now — the generated HTML is stored once and
reused by the preview, the email, the PDF and the public /confirm page, so this
is the single place that covers all four.

Lived in claude_service.py until the template replaced the prompt; moved out so
deleting the model path didn't take the data preparation with it.
"""

from time_utils import to_display_time

_HEADER_TIME_FIELDS = (
    ("first_call_time", "FIRST CALL"),
    ("first_shot_time", "FIRST SHOT"),
    ("lunch_time", "LUNCH"),
    ("est_wrap_time", "EST. WRAP"),
)
# general_call_time is a dead column kept only so the migration can seed from it.
# It joins the four real ones here so build_project_data withholds all five from
# the project dict — the header pills are the only place any of them belong.
_HEADER_TIME_KEYS = {f for f, _ in _HEADER_TIME_FIELDS} | {"general_call_time"}


def _header_times(project: dict) -> list[dict]:
    """Build the header pills from the producer's own times.

    A time that isn't set produces no pill, rather than a pill reading "—".
    """
    pills = []
    for field, label in _HEADER_TIME_FIELDS:
        display = to_display_time(project.get(field))
        if display:
            pills.append({"label": label, "time": display})
    return pills


# Meals in the order a shoot day runs. A meal with nothing filled in is dropped
# entirely rather than printed empty — same rule as the header pills.
_MEALS = (("breakfast", "BREAKFAST"), ("lunch", "LUNCH"))


def _meal_plan(meals: dict | None) -> list[dict]:
    """Build the meal rows, times already formatted for print."""
    if not meals:
        return []
    rows = []
    for key, label in _MEALS:
        start = to_display_time(meals.get(f"{key}_start"))
        end = to_display_time(meals.get(f"{key}_end"))
        notes = (meals.get(f"{key}_notes") or "").strip()
        # A meal with only notes still belongs on the sheet — "lunch is walk-away"
        # is worth saying even without a time on it.
        if start or end or notes:
            rows.append({"label": label, "start": start, "end": end, "notes": notes or None})
    return rows


def _resolve_talent_locations(
    talent: list,
    location: dict | None,
    company_moves: list,
) -> list:
    """Turn each talent's location_assignment id into the name they'll read."""
    move_map = {m["id"]: m for m in company_moves}
    primary_name = (location or {}).get("location_name") or "Primary Location"
    result = []
    for t in talent:
        assignment = t.get("location_assignment")
        if assignment == "primary":
            label = primary_name
        elif assignment and assignment in move_map:
            m = move_map[assignment]
            label = m.get("label") or m.get("location_name") or "Company Move"
        else:
            label = None
        result.append({**t, "location_label": label})
    return result


_CONTACT_FIELDS = ("email", "phone")


def _strip_contact_fields(person: dict) -> dict:
    return {k: v for k, v in person.items() if k not in _CONTACT_FIELDS}


def _redact_hidden(people: list) -> list:
    """Drop email/phone for anyone flagged hide_contact.

    Removing the values, rather than asking the renderer not to print them, is
    the point: this holds even if a column is added to the crew table later.

    Delivery is unaffected — send_call_sheet_emails reads addresses straight
    from the database, so hidden people still receive their call sheet.
    """
    cleaned = [_strip_contact_fields(p) if p.get("hide_contact") else p for p in people]
    # The flag itself is bookkeeping, not sheet content.
    return [{k: v for k, v in p.items() if k != "hide_contact"} for p in cleaned]


def _resolve_call_times(rows: list) -> list:
    """Collapse call_time / call_time_note into the single value the sheet shows.

    Each person arrives with one resolved field, so a named call ("Own Call",
    "TBD") lands in the call-time column exactly like a clock time and the
    template needs to know nothing about the second column. The renderer's
    display_time filter passes through anything it can't parse as a time, which
    is what makes that work. Rows arrive pre-sorted by sort_order, so nothing
    downstream tries to sort on this.
    """
    out = []
    for row in rows or []:
        item = {k: v for k, v in row.items() if k != "call_time_note"}
        if row.get("call_time_note"):
            item["call_time"] = row["call_time_note"]
        out.append(item)
    return out


def build_project_data(
    project: dict,
    crew: list,
    schedule: list,
    location: dict | None,
    contacts: list | None = None,
    talent: list | None = None,
    weather: dict | None = None,
    hospital: dict | None = None,
    company_moves: list | None = None,
    accommodation: dict | None = None,
    meals: dict | None = None,
) -> dict:
    """The renderer's entire input. Every key here is a section of the sheet."""
    # The raw time columns are withheld and passed only as `header_times` below,
    # so there is exactly one representation of a project time on the sheet.
    project_for_sheet = {
        k: v for k, v in project.items()
        if k != "notes" and k not in _HEADER_TIME_KEYS
    }
    resolved_moves = company_moves or []
    resolved_talent = _resolve_talent_locations(talent or [], location, resolved_moves)
    return {
        "project": project_for_sheet,
        "header_times": _header_times(project),
        "crew": _resolve_call_times(_redact_hidden(crew)),
        "schedule": schedule,
        "location": location,
        "company_moves": resolved_moves,
        # Agency/client phone and email are never printed on the sheet, so they
        # are stripped unconditionally rather than left in and skipped.
        "agency_and_client_contacts": _resolve_call_times([_strip_contact_fields(c) for c in (contacts or [])]),
        "talent": _resolve_call_times(_redact_hidden(resolved_talent)),
        "weather": weather,
        "nearest_hospital": hospital,
        "meal_plan": _meal_plan(meals),
        "accommodation": accommodation,
    }
