"""A job's dates: the Whole crew row, one person's changes to it, and what
follows from the two. Pure — no database, no side effects.

The model is the approved Deal Memos "Sheet" design (docs/job-layer-plan.md §5):

    jobs.crew_dates          {"travel": [[first, last], ...], "checkin": [...],
                              "prep": [...], "shoot": [...], "off": [...],
                              "wrap": [...], "travel_out": [...]}
    job_hires.dates_override same shape; a MISSING key means "same as crew",
                             an EMPTY list means "none" (a local hire with no
                             travel day)

Everything is ISO "YYYY-MM-DD" strings in and out, the way the API and
<input type="date"> both speak it.

The deal memo's Dates lines are formatted here, and must read exactly the way
the front end writes them ("Oct 11th - Sun - Travel in", "Oct 13th (Tue) –
Oct 15th (Thu) - Shoot day"). tests/date_line_cases.json holds the shared cases
so the two can't drift apart.
"""

import re
from datetime import date, timedelta

# Order matters: it's the order a job happens in, and the order ties sort in.
# "checkin" and "off" joined 2026-10-01 from the producer's answers (docs/producer-
# documents-map.md §2.4): a hotel check-in with no travel (someone already in
# town — usually unpaid, but per diem and a night) and a down day (always ½ the
# shoot rate, per diem and a night). Both are optional: guided setup never asks
# for them, and a job without them reads exactly as before.
DAY_TYPES = ("travel", "checkin", "prep", "shoot", "off", "wrap", "travel_out")

# The producer's vocabulary, with one split (Patrick, 2026-09-28): a WRAP day is work —
# wardrobe and prop stylists packing up merchandise, shipping it back,
# returning unused purchases — while TRAVEL OUT is everyone flying home. They
# were one "Wrap/Travel out" type, which put the same line on a stylist's memo
# and a photographer's for two different days.
LABELS = {
    "travel": "Travel in",
    "checkin": "Check-in",
    "prep": "Prep/Scout",
    "shoot": "Shoot day",
    "off": "Down day",
    "wrap": "Wrap day",
    "travel_out": "Travel out",
}

# What a deal memo's Dates line says, where it says more than the screen's
# label: the producer's own wording, so the line tells the crew member what it means
# for them. Must match the front end's MEMO_LABELS (tests/date_line_cases.json).
MEMO_LABELS = {
    **LABELS,
    "checkin": "Check into hotel (no travel)",
    "off": "Down day – ½ day rate",
}


# Days a person is away but not working: they're never put on that date's
# call sheet, and a day there doesn't count as theirs to work.
NOT_WORKING = ("checkin", "off")


def works_on(dates: dict | None, day: str) -> bool:
    """Whether these (effective) dates have the person WORKING `day` — any type
    but a check-in or a down day. Decides who's put on a day's crew."""
    return any(a <= day <= b for t, spans in (dates or {}).items() if t not in NOT_WORKING for a, b in spans)


class DatesError(ValueError):
    """A dates dict that isn't the shape above. The message is safe to show."""


# ── Shape ────────────────────────────────────────────────────────────────────

def _iso(value) -> date:
    if not isinstance(value, str):
        raise DatesError("Dates must be ISO strings like 2026-10-11.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DatesError(f"{value!r} isn't a date — use YYYY-MM-DD.")


def validate_dates(value) -> dict:
    """The dict, normalised (each span ordered first ≤ last, spans sorted), or
    DatesError. Used for both crew_dates and dates_override — an empty list is
    kept, because in an override it means "none"."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DatesError("Dates must be an object keyed by day type.")
    out = {}
    for key, spans in value.items():
        if key not in DAY_TYPES:
            raise DatesError(f"Unknown day type {key!r}.")
        if not isinstance(spans, list):
            raise DatesError(f"{LABELS[key]} must be a list of [first, last] spans.")
        clean = []
        for span in spans:
            if not isinstance(span, (list, tuple)) or len(span) != 2:
                raise DatesError(f"{LABELS[key]} spans must be [first, last].")
            a, b = _iso(span[0]), _iso(span[1])
            if b < a:
                a, b = b, a
            clean.append([a.isoformat(), b.isoformat()])
        out[key] = sorted(clean)
    return out


# Talent keep their OWN schedule (Patrick, 2026-10-02). They don't follow the
# crew: someone the crew flies in for prep on the 18th might fly a model in on
# the 19th to shoot the 20th and leave the 21st, and another the day after. So
# a talent hire follows NOTHING — a type they have no date for is none, not
# "same as crew" — and their dates are set when they're hired (talent_dates).
# Crew are unchanged: a missing type still means the crew's dates.

def base_dates(crew_dates: dict | None, kind: str | None = None) -> dict:
    """What a hire follows for a type they have no date of their own for:
    the crew's dates — and for talent, nothing."""
    if kind == "talent":
        return {}
    return crew_dates or {}


def hire_base(job: dict, hire: dict) -> dict:
    """base_dates for this hire on this job. Pass it wherever a hire's dates
    are worked out, in place of the job's crew_dates."""
    return base_dates(job.get("crew_dates"), hire.get("kind"))


def talent_dates(shoot_days: list[str]) -> dict:
    """A talent's dates from the shoot days they're booked for: travel in the
    day before the first, travel out the day after the last, and a down day
    on any day in between they don't shoot — by default they stay rather than
    fly home and back (Patrick, 2026-10-02). The producer changes any of it,
    e.g. flying out the night of the last shoot. {} when given no days."""
    days = sorted({_iso(d) for d in shoot_days or []})
    if not days:
        return {}
    one = timedelta(days=1)
    shoot, off = [], []
    for d in days:
        if shoot and date.fromisoformat(shoot[-1][1]) + one == d:
            shoot[-1][1] = d.isoformat()
        else:
            shoot.append([d.isoformat(), d.isoformat()])
    shot = set(days)
    d = days[0]
    while d < days[-1]:
        if d not in shot:
            if off and date.fromisoformat(off[-1][1]) + one == d:
                off[-1][1] = d.isoformat()
            else:
                off.append([d.isoformat(), d.isoformat()])
        d += one
    first_in, last_out = (days[0] - one).isoformat(), (days[-1] + one).isoformat()
    return {"travel": [[first_in, first_in]], "checkin": [], "prep": [], "shoot": shoot,
            "off": off, "wrap": [], "travel_out": [[last_out, last_out]]}


# A talent goes on a day's talent list only for a shoot or a fitting (a prep
# date set on their hire) — never for a travel day.
TALENT_DAY_TYPES = ("shoot", "prep")


def talent_on_day(dates: dict | None, day: str) -> bool:
    return any(a <= day <= b for t in TALENT_DAY_TYPES for a, b in (dates or {}).get(t, []))


def effective_dates(crew_dates: dict | None, override: dict | None) -> dict:
    """One person's actual dates: their own where they have them, the crew's
    everywhere else."""
    crew_dates, override = crew_dates or {}, override or {}
    return {t: list(override[t]) if t in override else list(crew_dates.get(t, []))
            for t in DAY_TYPES}


def is_custom(override: dict | None) -> bool:
    """True when this person has changed anything about the crew dates."""
    return bool(override)


# ── Formatting ───────────────────────────────────────────────────────────────

def _ordinal(day: int) -> str:
    if day % 10 == 1 and day != 11:
        return "st"
    if day % 10 == 2 and day != 12:
        return "nd"
    if day % 10 == 3 and day != 13:
        return "rd"
    return "th"


def _day(d: date) -> str:
    # strftime's %b/%a follow the locale; spelled out so a server locale can't
    # turn "Oct" into "okt" on a document crew members sign.
    month = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[d.month - 1]
    return f"{month} {d.day}{_ordinal(d.day)}"


def _weekday(d: date) -> str:
    return ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[d.weekday()]


def format_span(first: str, last: str) -> str:
    """"Oct 11th - Sun" for one day, "Oct 13th (Tue) – Oct 15th (Thu)" for a
    span — the front end's formatDateOrRange, exactly."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    if a == b:
        return f"{_day(a)} - {_weekday(a)}"
    return f"{_day(a)} ({_weekday(a)}) – {_day(b)} ({_weekday(b)})"


# What a talent's date lines say (their call sheet, to the agent): a down day
# carries no half-rate — that's the crew deal — and a prep date on a talent is
# a fitting.
TALENT_LABELS = {**MEMO_LABELS, "prep": "Fitting", "off": "Down day (no shoot)"}


def format_line(day_type: str, first: str, last: str, labels: dict | None = None) -> str:
    return f"{format_span(first, last)} - {(labels or MEMO_LABELS)[day_type]}"


# Day labels ("Brand A – Studio, NJ") are the job's, one per date, and name the
# WORK that day — so they print on prep, shoot, down and wrap lines, not on a
# travel line that happens to share the date. Day notes ("already in town")
# are one person's, one per date, and print on that date's first line.
LABELLED_TYPES = ("prep", "shoot", "off", "wrap")

TEXT_MAX = 200


def validate_day_text(value) -> dict:
    """{ISO date: text} for jobs.day_labels and job_hires.day_notes — trimmed,
    blanks dropped, or DatesError."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DatesError("Day labels and notes must be an object keyed by date.")
    out = {}
    for key, text in value.items():
        d = _iso(key).isoformat()
        if text is None:
            continue
        if not isinstance(text, str):
            raise DatesError("Each label or note must be text.")
        text = " ".join(text.split())
        if len(text) > TEXT_MAX:
            raise DatesError(f"Keep each label or note under {TEXT_MAX} characters.")
        if text:
            out[d] = text
    return out


def _runs(t: str, span, labels: dict, notes: dict, noted: set) -> list[tuple[str, str, str]]:
    """One stored span as (first, last, suffix) runs. Days inside a stored
    span are consecutive, so a run continues exactly while the suffix — label
    and note — stays the same (doc §3.3: collapse only when type, label and
    note all match). A span with neither prints as it always has. A note goes
    on the first line of its date only (`noted`)."""
    out: list[tuple[str, str, str]] = []
    for d in _days([span]):
        iso = d.isoformat()
        parts = []
        if t in LABELLED_TYPES and labels.get(iso):
            parts.append(labels[iso])
        if notes.get(iso) and iso not in noted:
            parts.append(notes[iso])
            noted.add(iso)
        suffix = "".join(f" - {p}" for p in parts)
        if out and out[-1][2] == suffix:
            out[-1] = (out[-1][0], iso, suffix)
        else:
            out.append((iso, iso, suffix))
    return out


def dates_block(crew_dates: dict | None, override: dict | None,
                labels: dict | None = None, notes: dict | None = None, kind: str | None = None) -> str:
    """The deal memo's Dates block: one line per span, in the order the job
    happens, with the job's day label and the person's day note after the
    date they belong to. Empty string when there's nothing to say."""
    eff = effective_dates(crew_dates, override)
    labels, notes, noted = labels or {}, notes or {}, set()
    pieces = sorted((span[0], DAY_TYPES.index(t), t, span) for t in DAY_TYPES for span in eff[t])
    lines = []
    for _first, order, t, span in pieces:
        for a, b, suffix in _runs(t, span, labels, notes, noted):
            lines.append((a, order, format_line(t, a, b, TALENT_LABELS if kind == "talent" else None) + suffix))
    return "\n".join(line for *_k, line in sorted(lines))


def person_days(crew_dates: dict | None, override: dict | None,
                labels: dict | None = None, notes: dict | None = None) -> list[dict]:
    """Every date this person has, once, in order: [{date, types, label,
    note}]. What the screen lists for writing day notes against — the same
    dates the Dates block prints."""
    eff = effective_dates(crew_dates, override)
    labels, notes = labels or {}, notes or {}
    by_date: dict[str, list[str]] = {}
    for t in DAY_TYPES:
        for d in _days(eff[t]):
            by_date.setdefault(d.isoformat(), [])
            if t not in by_date[d.isoformat()]:
                by_date[d.isoformat()].append(t)
    return [{"date": d, "types": ts,
             "label": labels.get(d) if any(t in LABELLED_TYPES for t in ts) else None,
             "note": notes.get(d)}
            for d, ts in sorted(by_date.items())]


# ── Legacy free text → structured ────────────────────────────────────────────
#
# crew_members.deal_memo_dates is free text, one line per span, mostly written
# by the deal memo page's picker (so in format_line's shape) but typeable by
# hand. Converting it happens once, when an account opts in to Jobs. Anything
# this can't read with confidence is REPORTED, never guessed at or dropped.

_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_WEEKDAYS = {w: i for i, w in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}

_DAY = r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
_WKD = r"\(?([A-Za-z]{3})[a-z]*\.?\)?"
_RANGE_RE = re.compile(rf"^{_DAY}\s*(?:{_WKD})?\s*[–—-]\s*{_DAY}\s*(?:{_WKD})?\s*[–—-]\s*(.+)$")
_SINGLE_RE = re.compile(rf"^{_DAY}\s*(?:[–—-]\s*)?(?:{_WKD})?\s*[–—-]\s*(.+)$")


def _day_type(label: str) -> str | None:
    """Which day type a hand-written label means. Leaving is checked first:
    the old combined "Wrap/Travel out" label (and "Travel Day - flies out")
    was, for most people, the day they flew home — so it reads as travel out,
    and only a label that says wrap without leaving is a wrap day."""
    s = label.lower()
    if "down day" in s or "day off" in s or "off day" in s:
        return "off"
    if any(w in s for w in ("travel out", "travels out", "depart", "flies out", "fly out",
                            "flies home", "fly home", "flying home", "heads home")):
        return "travel_out"
    if "wrap" in s:
        return "wrap"
    if "prep" in s or "scout" in s:
        return "prep"
    if "shoot" in s:
        return "shoot"
    if "travel" in s or "arriv" in s or "fly" in s or "flies" in s:
        return "travel"
    # A check-in that doesn't mention travelling is someone already in town
    # (the producer's "Aug 24th - Mon - check in", Q2): its own type since 2026-10-01,
    # because it's paid differently from a travel day.
    if "check in" in s or "check-in" in s or "check into" in s:
        return "checkin"
    return None


def _resolve(month: str, day: str, weekday: str | None, ref: date) -> date | None:
    """The date these parts mean, near `ref`. The lines carry no year, so try
    the years either side and keep the one closest to the job — preferring one
    whose weekday agrees, when the line gives a weekday."""
    m = _MONTHS.get(month.lower()[:3])
    if not m:
        return None
    wd = _WEEKDAYS.get(weekday.lower()[:3]) if weekday else None
    if weekday and wd is None:
        return None
    options = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            options.append(date(y, m, int(day)))
        except ValueError:
            continue
    if not options:
        return None
    if wd is not None:
        agreeing = [d for d in options if d.weekday() == wd]
        options = agreeing or options
    return min(options, key=lambda d: abs((d - ref).days))


def parse_legacy_line(line: str, ref: date) -> tuple[str, str, str] | None:
    """(day_type, first, last) or None."""
    text = " ".join(line.split())
    m = _RANGE_RE.match(text)
    if m:
        mo1, d1, w1, mo2, d2, w2, label = m.groups()
        t = _day_type(label)
        a, b = _resolve(mo1, d1, w1, ref), _resolve(mo2, d2, w2, ref)
        if t and a and b:
            if b < a:
                # "Dec 30th – Jan 2nd" resolved each end on its own; keep the
                # span forward in time rather than inverting it.
                b = _resolve(mo2, d2, w2, a + timedelta(days=183)) or b
            if b >= a:
                return t, a.isoformat(), b.isoformat()
    m = _SINGLE_RE.match(text)
    if m:
        mo, d, w, label = m.groups()
        t = _day_type(label)
        a = _resolve(mo, d, w, ref)
        if t and a:
            return t, a.isoformat(), a.isoformat()
    return None


def parse_legacy_text(texts: list[str], ref: date) -> tuple[dict, list[str]]:
    """Every line of every text → (override, unparsed lines).

    Several day rows for the same person may each carry their own copy of the
    block, so identical lines are read once.

    The override holds every day type whenever anything parsed: the old
    block was a complete statement of that person's dates, so a type it never
    mentions means "none", not "same as crew".
    """
    seen, spans, unparsed = set(), {t: [] for t in DAY_TYPES}, []
    for text in texts:
        for raw in (text or "").splitlines():
            line = " ".join(raw.split())
            if not line or line.lower() in seen:
                continue
            seen.add(line.lower())
            parsed = parse_legacy_line(line, ref)
            if parsed is None:
                unparsed.append(line)
                continue
            t, a, b = parsed
            if [a, b] not in spans[t]:
                spans[t].append([a, b])
    if not any(spans.values()):
        return {}, unparsed
    return {t: sorted(v) for t, v in spans.items()}, unparsed


# ── Conflicts: when the crew dates move under someone's custom dates ─────────

def _days(spans) -> list[date]:
    out = []
    for a, b in spans:
        d, end = date.fromisoformat(a), date.fromisoformat(b)
        while d <= end:
            out.append(d)
            d += timedelta(days=1)
    return out


# How far someone's own dates can sit outside the crew's before it's a
# mistake rather than an early arrival or a late wrap-out.
CONFLICT_SLACK_DAYS = 3


def conflicts_for(crew_dates: dict | None, hire: dict) -> list[dict]:
    """The right conflict rule for this hire: crew are judged against the
    crew's dates (find_conflicts); talent only for shooting on a day the crew
    isn't shooting, or dates that overlap — they're expected to come and go."""
    override = hire.get("dates_override") or {}
    if hire.get("kind") != "talent":
        return find_conflicts(crew_dates, override)
    crew_shoot = {d for d in _days((crew_dates or {}).get("shoot", []))}
    out = []
    if crew_shoot and any(d not in crew_shoot for d in _days(override.get("shoot", []))):
        out.append({"type": "shoot", "reason": "Shoots on a day the crew isn't shooting"})
    out += [c for c in _overlaps(override) if not any(o["type"] == c["type"] for o in out)]
    return sorted(out, key=lambda c: DAY_TYPES.index(c["type"]))


def _overlaps(dates: dict) -> list[dict]:
    """Two blocks of the same type claiming the same day — a glitch."""
    out = []
    for t in DAY_TYPES:
        seen: set[date] = set()
        doubled = False
        for span in (dates or {}).get(t, []):
            for d in _days([span]):
                doubled = doubled or d in seen
                seen.add(d)
        if doubled:
            out.append({"type": t, "reason": "Their dates overlap each other"})
    return out


def find_conflicts(crew_dates: dict | None, override: dict | None) -> list[dict]:
    """What about this person's own dates is genuinely wrong, as
    [{"type": day_type, "reason": str}] — one entry per flagged cell. These
    marks stay on screen, so they must never fire on a real schedule.

    The first version judged a person's dates against the crew's ORDER — prep
    after the first shoot day, wrap before the last, travel after their first
    working day — and the producer's real jobs do all of that on purpose: a prep day
    between two brands' shoots, someone flying home early, a travel day
    mid-job (docs/producer-documents-map.md §0.2). Nor can "a day the crew isn't
    working" be a rule: arriving two days early to prep is normal. So only:

      1. They SHOOT on a day the crew isn't working at all.
      2. One of their dates is more than CONFLICT_SLACK_DAYS outside the
         job's first-to-last crew date — adrift, not early or late.
      3. Two of their own blocks of the SAME type overlap (a glitch). Two
         types on one day is a real day, not a conflict: shoot then fly out
         that evening (her sheets have a "Travel/Wrap" column), fly in and
         prep, prep then shoot.

    Dates a move left behind are caught at the move itself instead: the
    Pre-production page offers "Move them too" to everyone with their own
    dates whenever the crew's dates shift, conflict or not.

    People following the crew dates are never flagged: they move with the crew
    by definition. Nothing is fixed here — a producer who gave someone their
    own schedule meant it, so the app points at the conflict (plan §6).
    """
    if not is_custom(override):
        return []
    crew = effective_dates(crew_dates, {})
    crew_days = {d for t in DAY_TYPES for d in _days(crew[t])}
    out = []

    if crew_days:
        first, last = min(crew_days), max(crew_days)
        slack = timedelta(days=CONFLICT_SLACK_DAYS)
        for t in DAY_TYPES:
            if t not in override:
                continue            # following the crew for this type
            own = _days(override[t])
            if t == "shoot" and any(d not in crew_days for d in own):
                out.append({"type": t, "reason": "Shoots on a day the crew isn't working"})
            elif any(d < first - slack or d > last + slack for d in own):
                out.append({"type": t, "reason": "Days away from the rest of the job"})

    # Overlap: two blocks of the same type claiming the same day.
    out += [c for c in _overlaps(effective_dates(crew_dates, override))
            if not any(o["type"] == c["type"] for o in out)]

    return sorted(out, key=lambda c: DAY_TYPES.index(c["type"]))


def crew_shift_days(old: dict | None, new: dict | None) -> int:
    """How far the crew moved, in days — what "Move with the crew" shifts a
    custom person by. Measured on the first shoot day, falling back to the first
    date of any kind; 0 when either side has no dates to measure."""
    def anchor(dates):
        dates = dates or {}
        shoot = _days(dates.get("shoot", []))
        if shoot:
            return min(shoot)
        every = [d for t in DAY_TYPES for d in _days(dates.get(t, []))]
        return min(every) if every else None
    a, b = anchor(old), anchor(new)
    return (b - a).days if a and b else 0


def shift_dates(dates: dict | None, days: int) -> dict:
    """Every span moved by `days`. Keys (including empty "none" lists) are
    kept exactly, so shifting never turns a custom type back into "same as
    crew"."""
    delta = timedelta(days=days)
    return {t: [[(date.fromisoformat(a) + delta).isoformat(),
                 (date.fromisoformat(b) + delta).isoformat()] for a, b in spans]
            for t, spans in (dates or {}).items()}


def date_span(crew_dates: dict | None, day_dates: list[str]) -> tuple[str, str] | None:
    """(first, last) for the dashboard: the crew dates when there are any,
    else first-to-last day."""
    every = [d for t in DAY_TYPES for d in _days((crew_dates or {}).get(t, []))]
    if every:
        return min(every).isoformat(), max(every).isoformat()
    days = sorted(d for d in day_dates if d)
    return (days[0], days[-1]) if days else None


def day_label(crew_dates: dict | None, days: list[dict], day_id: str) -> str | None:
    """"Day 2 of 4" for the call sheet and its email — the same numbering as
    the Shoot days tab and the day sidebar (frontend lib/jobDates.ts
    planDays), so a sheet can't call a day something the app doesn't.

    The shoot days are the crew's shoot dates, in order, whether or not a day
    exists for each yet; a day off those dates (a scout, a travel day) has no
    number. With no shoot dates set, days just number in shooting order.
    None when this day has no number, or the job has only one shoot day —
    "Day 1 of 1" says nothing a one-day sheet needs."""
    ordered = sorted(days, key=lambda d: (d.get("shoot_date") is None, d.get("shoot_date") or "",
                                          d.get("created_at") or ""))
    shoot = sorted({d.isoformat() for d in _days((crew_dates or {}).get("shoot") or [])})
    if not shoot:
        slots = [d["id"] for d in ordered]
    else:
        slots = []
        for when in shoot:
            on = [d["id"] for d in ordered if d.get("shoot_date") == when]
            slots.extend(on or [None])      # None: a shoot date not set up yet
    if len(slots) < 2 or day_id not in slots:
        return None
    return f"Day {slots.index(day_id) + 1} of {len(slots)}"
