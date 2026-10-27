"""Reading the people off an old call sheet PDF, for the Roster's Quick Import.

A producer's best record of who they work with is usually last month's call
sheet. This takes that PDF and returns the people on it — crew, talent and
client contacts, each typed — in the same shape the paste import produces, so
the Roster page's existing preview and /roster/import/confirm do the rest.

Three jobs, in order:

1. `check_pdf` — refuse anything that isn't a small, readable PDF *before* it
   costs a model call. The magic bytes decide, not the filename or the
   Content-Type the browser claimed.
2. `claude_service.parse_call_sheet_pdf` — the model reads the PDF itself.
3. `clean_people` — trust nothing about the shape that comes back. Only the
   fields a Roster import carries survive, whatever else the model returned, and
   nothing that looks like pay gets through even inside an allowed field. A day
   rate is producer-only information (see models/roster.py) and an import is
   not how it should arrive.

The PDF is never stored: it lives in memory for the length of one request.
Nothing here logs a name, email or phone number.
"""

import re

from services import claude_service
from services.attachment_service import human_size

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 10

TYPES = ("crew", "talent", "client")

#: Everything a Roster import row can carry — RosterImportMember's fields.
#: Anything else the model sends is dropped here, which is the real guarantee
#: that no rate, fee or call time rides in on an import.
_FIELDS = ("name", "role", "email", "phone", "department", "organization")

_MAX_FIELD = 200

# "$650", "£400", "650/day", "per hour", "day rate", "1,200 USD" — a value that
# reads like money is dropped rather than trimmed, since there is no reliable
# way to cut the pay out of "Gaffer $650/10" and leave a clean title.
_PAY = re.compile(
    r"[$£€]\s*\d"
    r"|\d\s*(?:usd|gbp|eur)\b"
    r"|\d\s*/\s*(?:day|hr|hour|week|wk)\b"
    r"|\bper\s+(?:day|hour|week)\b"
    r"|\b(?:day|hourly|weekly)\s+rate\b"
    r"|\bflat\s+(?:fee|rate)\b",
    re.IGNORECASE,
)


class Rejected(ValueError):
    """An upload refused with a message meant for the producer, plus the HTTP
    status the router should answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_pdf(data: bytes) -> int:
    """Refuse anything but a small, openable, unlocked PDF. Returns its page count."""
    if not data:
        raise Rejected("That file came through empty.")
    if len(data) > MAX_BYTES:
        raise Rejected(
            f"That file is {human_size(len(data))}. Call sheets can be up to "
            f"{human_size(MAX_BYTES)}.",
            status=413,
        )
    # Every PDF starts with this header. A renamed .docx or a screenshot saved
    # as "callsheet.pdf" doesn't, and would otherwise cost a model call to fail.
    if not data.startswith(b"%PDF-"):
        raise Rejected(
            "That doesn't look like a PDF. Export or print the call sheet to PDF and try again.",
            status=415,
        )

    try:
        import pymupdf
    except ImportError:  # older installs only ship the legacy module name
        import fitz as pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise Rejected("That PDF couldn't be opened — it may be damaged. Try exporting it again.")
    with doc:
        # The model can't read an encrypted PDF either, so say so now rather
        # than after a slow, paid round trip.
        if doc.needs_pass:
            raise Rejected("That PDF is password-protected. Remove the password and try again.")
        pages = doc.page_count
    if pages < 1:
        raise Rejected("That PDF has no pages in it.")
    if pages > MAX_PAGES:
        raise Rejected(
            f"That PDF is {pages} pages long. A call sheet can be up to {MAX_PAGES} pages — "
            f"upload just the pages with the crew, talent and client lists."
        )
    return pages


def _text(value) -> str | None:
    """One line, bounded, or nothing. Numbers are allowed through as text
    because a phone number sometimes comes back as one."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned or cleaned.lower() in ("null", "none", "n/a", "tbd"):
        return None
    return cleaned[:_MAX_FIELD]


def clean_people(raw) -> list[dict]:
    """The model's answer reduced to Roster import rows, each with a valid type.

    Raises ValueError if the answer isn't a list at all — that is a failed read,
    not an empty call sheet, and the producer should hear the difference.
    """
    if not isinstance(raw, list):
        raise ValueError("expected a JSON array of people")

    people = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        person = {field: _text(item.get(field)) for field in _FIELDS}
        for field, value in person.items():
            if value and _PAY.search(value):
                person[field] = None
        if not person["name"]:
            continue

        kind = (_text(item.get("type")) or "").lower()
        # Unknown or missing type: crew is the biggest section of any sheet and
        # the preview lets the producer move the row.
        person["type"] = kind if kind in TYPES else "crew"
        # Department is a crew field and organization a client one, the same
        # split /roster/import/confirm applies on the way in.
        if person["type"] != "crew":
            person["department"] = None
        if person["type"] != "client":
            person["organization"] = None
        people.append(person)
    return people


def read_call_sheet(data: bytes, on_usage: claude_service.UsageCallback = None) -> list[dict]:
    """Check the upload, have the model read it, and clean what comes back.

    Blocking — a model call takes seconds. The router runs it in a thread.
    `on_usage` receives the model's token counts (see claude_service); a refused
    upload never reaches the model, so it is never called for one.
    """
    check_pdf(data)
    return clean_people(claude_service.parse_call_sheet_pdf(data, on_usage))
