"""Assemble one crew member's deal memo data. No rendering, no side effects.

Mirrors call_sheet_data.py's split: the database→renderer boundary lives here,
so the renderer can be tested against hand-built fixtures the same way.

On the Jobs memo, a hire's own agreed rates win (services/job_rates.py) —
they're the deal, copied onto the hire. With none set, or on the day memo,
the rate is the Roster's, as before. Either way it lives on the Roster or the
hire, never on crew_members — see roster.py's own note on
day_rate/agent_* being excluded from PERSON_FIELDS. This module is the one
place a crew member's project row and their Roster row (via roster_id) are
joined for a rate to reach a document at all, and that document is a producer-
only PDF download, never emailed and never the call sheet.
"""

from services.job_dates import dates_block, hire_base
from services.job_rates import has_rates, memo_rate_lines, per_diem_text



def build_deal_memo_data(
    project: dict,
    crew_member: dict,
    roster_entry: dict | None,
    location: dict | None = None,
    dates: str | None = None,
) -> dict:
    """`project` and `crew_member` are the raw DB rows. `roster_entry` is the
    Roster row `crew_member["roster_id"]` points at, or None when this person
    was added to the project directly and has no Roster record — rate and
    agency fields are simply blank in that case, same as an unset column
    anywhere else in the app. `location` is the project's own project_locations
    row (same shape call_sheet_data.py takes it in), not a new column — the
    memo's "Location" line reads whatever's already on the Location page.

    Two callers, one shape. The day version passes a project and a crew row,
    and the Dates block is that row's free text. The Jobs version passes the
    job as `project` (it has the same name/client/production company/payroll
    fields), a hire as `crew_member`, and `dates` already formatted from the
    crew dates plus the hire's own (services/job_dates.dates_block).
    """
    roster_entry = roster_entry or {}
    has_agent = bool((roster_entry.get("agent_name") or "").strip())
    return {
        "project": {
            "name": project.get("name"),
            "client_name": (project.get("client_name") or "").strip(),
            "production_company": (project.get("production_company") or "").strip(),
            "payroll_provider": (project.get("payroll_provider") or "").strip(),
            "location": ((location or {}).get("location_name") or (location or {}).get("address") or "").strip(),
            # Jobs only: a day (project) has no such column, so the line
            # simply doesn't print on the day version.
            # Built from the job's amounts when set, else its free-text line.
            "per_diem": per_diem_text(project),
        },
        "crew_member": {
            "name": crew_member.get("name"),
            "role": crew_member.get("role"),
            "phone": crew_member.get("phone"),
            "email": crew_member.get("email"),
            "dates": dates if dates is not None else crew_member.get("deal_memo_dates"),
        },
        # A hire's own rates replace the Roster's whole Rate block, note and all:
        # mixing "$650/day" from the Roster with the hire's lines would print
        # two rates for one person.
        "day_rate": None if has_rates(crew_member) else roster_entry.get("day_rate"),
        "rate_note": memo_rate_lines(crew_member) if has_rates(crew_member) else roster_entry.get("rate_note"),
        "has_agent": has_agent,
        "agent_name": roster_entry.get("agent_name") if has_agent else None,
    }


def job_memo_dates(job: dict, hire: dict) -> str:
    """A hire's Dates block on the Jobs memo: the lines generated from the
    crew's dates and the hire's own, then their free-text note under them —
    the lines no day type covers yet (a down day at half rate, a check-in day
    with no travel; docs/producer-documents-map.md §4)."""
    lines = dates_block(hire_base(job, hire), hire.get("dates_override"),
                        job.get("day_labels"), hire.get("day_notes"))
    note = (hire.get("dates_note") or "").strip()
    return "\n".join(part for part in (lines, note) if part)


def job_memo_location_line(job: dict) -> str:
    """The job's own Location line ("NJ and NY"), or "" to fall back to the
    first day's location."""
    return (job.get("location_line") or "").strip()


def select_hires(hires: list[dict], wanted: list[str] | None) -> list[dict]:
    """The hires a zip should hold. None means everyone (Download all); a list
    keeps only those ids, in the job's own order — not the order they were
    ticked. Ids that aren't on this job are simply never matched, because the
    caller only ever passes this job's hires."""
    if wanted is None:
        return hires
    keep = {str(w) for w in wanted}
    return [h for h in hires if str(h["id"]) in keep]
