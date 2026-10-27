"""Render a call sheet from project data. No model involved.

Replaces the 192-line system prompt in claude_service.py, which specified 31
exact hex colours and spent 20 of its lines saying EXACTLY / do NOT / never /
verbatim. Nothing in it was a decision — it was a deterministic template written
in English and interpreted at 59 tokens per second, once per generation.

Input is the `project_data` dict services/call_sheet_data.py assembles — that
module resolves call times, redacts hidden contacts, strips agency details and
normalises meals before anything reaches here.

Output must stay email-safe: inline styles only, no <style> block, table layout.
Three things consume it — SendGrid, WeasyPrint for the PDF, and the public
/confirm page.

Decisions that need branching (which columns exist, how rows group) are made
here rather than in the template, so they can be tested without parsing HTML.
"""

from datetime import date
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from time_utils import to_display_time

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_env: Environment | None = None


def _environment() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(_TEMPLATE_DIR),
            # Autoescape is the security story here. The old path let a model
            # write markup around free-text crew names and cleaned up afterwards
            # with nh3; escaping at the insertion point is correct by
            # construction rather than by cleanup.
            autoescape=select_autoescape(["html", "j2", "html.j2"], default=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _env.filters["display_time"] = display_time
        _env.filters["maps"] = maps_url
        _env.filters["nl2br"] = nl2br
        _env.filters["display_date"] = display_date
    return _env


def display_time(value) -> str | None:
    """Format a stored time as '8:00 AM', or pass a note through unchanged.

    `_resolve_call_times` collapses call_time_note into call_time, so this field
    holds either a Postgres time or a producer's own words ("Own Call", "TBD").
    to_display_time returns None for anything it can't parse, which is the
    signal that we're looking at the second kind and should print it verbatim.
    """
    if value in (None, ""):
        return None
    return to_display_time(str(value)) or str(value)


def time_range(start, end) -> str | None:
    """'8:00 AM – 9:00 AM', or just the start when there's no end."""
    s, e = display_time(start), display_time(end)
    if s and e:
        return f"{s} – {e}"
    return s or e


def maps_url(address: str, provider: str = "apple") -> str:
    enc = quote(address)
    if provider == "google":
        return f"https://www.google.com/maps/search/?api=1&query={enc}"
    return f"https://maps.apple.com/?q={enc}"


def nl2br(value) -> Markup:
    """Producer free text keeps its line breaks, and nothing else.

    Escapes FIRST, then substitutes the breaks, then marks the result safe — in
    that order, and it matters. Returning a plain string for the template to
    mark `| safe` is what the first version did, and it turned off autoescaping
    for exactly the fields a producer types by hand: parking notes, meal notes,
    hotel amenities. A test fixture containing `<b>only</b>` came through live.

    These land on the public /confirm page that crew open from an email, so this
    is the one filter in the file that must not be convenient.
    """
    # str() before replace, and it is load-bearing: escape() returns Markup, and
    # Markup.replace escapes its arguments — so replacing on the Markup turns the
    # <br> itself into &lt;br&gt; and line breaks render as visible text. Escape,
    # drop back to a plain string, substitute, then mark the whole thing safe.
    return Markup(str(escape(value or "")).replace("\n", "<br>"))


def display_date(value) -> str | None:
    """'Monday, September 14, 2026' from a stored date.

    The old prompt asked the model for "shoot date and day of week"; nothing
    else formats this, so without it the sheet prints a bare 2026-09-14. The day
    name earns its place — a producer scanning a sheet checks the weekday before
    the number.
    """
    if not value:
        return None
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{d:%A, %B} {d.day}, {d.year}"


def _group_by(rows: list, key: str) -> list[dict]:
    """Group rows by `key`, ordered by where each value first appears, with
    unkeyed rows last under no heading.

    First-appearance order rather than alphabetical because the array is already
    in the order the producer arranged, and that order is the point.
    """
    groups: dict = {}
    ungrouped: list = []
    for row in rows:
        label = row.get(key)
        if label:
            groups.setdefault(label, []).append(row)
        else:
            ungrouped.append(row)
    out = [{"label": label, "rows": rs} for label, rs in groups.items()]
    if ungrouped:
        out.append({"label": None, "rows": ungrouped})
    return out


def _people_block(rows: list, group_key: str | None) -> dict:
    """Everything a crew or talent table needs to render itself.

    Columns are dropped when no row has a value, so a shoot where nobody has a
    phone number doesn't carry an empty column across the whole sheet.
    """
    rows = rows or []
    grouped = _group_by(rows, group_key) if group_key else []
    return {
        "rows": rows,
        # Only group when at least one row actually carries the key. A single
        # group holding everything is just a flat table with a spurious heading.
        "groups": grouped if any(r.get(group_key) for r in rows) else [],
        "show_phone": any((r.get("phone") or "").strip() for r in rows),
        "show_email": any((r.get("email") or "").strip() for r in rows),
    }


def _build_context(data: dict) -> dict:
    crew = data.get("crew") or []
    talent = data.get("talent") or []
    contacts = data.get("agency_and_client_contacts") or []
    accommodation = data.get("accommodation") or None

    # An accommodation row can exist with every field blank — saving and then
    # clearing the form leaves one behind — so presence isn't enough.
    if accommodation and not (accommodation.get("hotel_name") or accommodation.get("address")):
        accommodation = None

    return {
        "project": data.get("project") or {},
        "header_times": data.get("header_times") or [],
        "weather": data.get("weather"),
        "location": data.get("location"),
        "company_moves": data.get("company_moves") or [],
        "hospital": data.get("nearest_hospital"),
        "crew": _people_block(crew, "department"),
        "contacts": {
            "rows": contacts,
            "show_call_time": any(c.get("call_time") for c in contacts),
        },
        "talent": _people_block(talent, "location_label"),
        "meal_plan": data.get("meal_plan") or [],
        "schedule": data.get("schedule") or [],
        "accommodation": accommodation,
        "time_range": time_range,
    }


def render_call_sheet(data: dict) -> str:
    """project_data in, one inline-CSS HTML document out."""
    return _environment().get_template("call_sheet.html.j2").render(**_build_context(data))
