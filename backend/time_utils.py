from datetime import datetime
from fastapi import HTTPException

# Ordered so the most specific / most common user formats win first.
_TIME_FORMATS = (
    "%I:%M %p",   # 8:00 AM
    "%I:%M%p",    # 8:00AM
    "%I %p",      # 8 AM
    "%I%p",       # 8AM
    "%H:%M:%S",   # 08:00:00 (already-normalized, round-trips from Postgres)
    "%H:%M",      # 14:30
    "%H",         # 8  (bare hour, treated as 24h)
)


def to_pg_time(value: str) -> str:
    """Normalize a user-facing time string to HH:MM:SS for a Postgres time column.

    Accepts forms like '8:00 AM', '8 AM', '8am', '8:00am', '8:00 a.m.',
    '14:30', and '8'. Raises HTTPException(422) with a readable message when
    the input can't be parsed, instead of passing garbage to the database.
    """
    raw = (value or "").strip()
    # '8:00 a.m.' -> '8:00 AM'; collapse stray internal whitespace.
    cleaned = " ".join(raw.replace(".", "").upper().split())
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    raise HTTPException(
        status_code=422,
        detail=f'"{raw}" isn\'t a valid time. Try a format like "8:00 AM" or "14:30".',
    )


def to_display_time(value: str | None) -> str | None:
    """Format a stored Postgres time as '7:00 AM'. None for empty/unparseable."""
    if not value:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(value, fmt)
            return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
        except ValueError:
            continue
    return None


def to_pg_time_or_none(value: str | None) -> str | None:
    """Lenient variant for bulk import: empty or unparseable input yields None
    instead of raising, so one bad pasted cell doesn't reject the whole batch."""
    if not value or not value.strip():
        return None
    try:
        return to_pg_time(value)
    except HTTPException:
        return None


# Named call times a producer can use instead of a clock time. A call sheet is
# read at 5am by someone who needs to know when to be there, so this is a closed
# set rather than free text: an unrecognized entry is far more likely to be a
# typo'd time ("9:0O AM") than a deliberate label, and silently printing that on
# the sheet is worse than refusing it.
#
# Keys are matched case- and punctuation-insensitively; the value is what
# appears on the call sheet.
_CALL_TIME_LABELS = {
    "own call": "Own Call",
    "oc": "Own Call",
    "own time": "Own Time",
    "self report": "Self Report",
    "sr": "Self Report",
    "tbd": "TBD",
    "tba": "TBD",
    "hold": "Hold",
    "as needed": "As Needed",
    "on call": "On Call",
    "n/a": "N/A",
    "na": "N/A",
}

CALL_TIME_LABEL_CHOICES = ["Own Call", "Own Time", "Self Report", "TBD", "Hold", "As Needed", "On Call", "N/A"]


def _label_for(value: str) -> str | None:
    """Canonical label for a named call time, or None if it isn't one."""
    key = " ".join(value.replace(".", "").replace("-", " ").lower().split())
    if key.startswith("o/c"):
        key = "oc"
    return _CALL_TIME_LABELS.get(key)


def split_call_time(value: str | None) -> tuple[str | None, str | None]:
    """Resolve one user-entered call time into (pg_time, label).

    A producer types into a single field, so this decides what they meant:
    empty is no call time at all, a recognized phrase is a named call time, and
    anything else has to parse as a clock time or be refused. Exactly one of the
    two return values is ever set.
    """
    raw = (value or "").strip()
    if not raw:
        return None, None
    label = _label_for(raw)
    if label:
        return None, label
    try:
        return to_pg_time(raw), None
    except HTTPException:
        raise HTTPException(
            status_code=422,
            detail=(
                f'"{raw}" isn\'t a valid time. Use a time like "8:00 AM" or "14:30", '
                f'or one of: {", ".join(CALL_TIME_LABEL_CHOICES[:5])}.'
            ),
        )


def split_call_time_lenient(value: str | None) -> tuple[str | None, str | None]:
    """Import variant: an unparseable cell yields no call time rather than
    rejecting the whole batch, matching to_pg_time_or_none's behaviour."""
    try:
        return split_call_time(value)
    except HTTPException:
        return None, None


def display_call_time(call_time: str | None, note: str | None) -> str | None:
    """What to show for a person's call time: the label if there is one,
    otherwise the formatted clock time, otherwise nothing."""
    return note or to_display_time(call_time)
