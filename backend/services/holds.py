"""Holds: who's pencilled in before they're booked, and the roles a job still
needs (docs/producer-documents-map.md §0.5, §1.1). Pure — no database.

The producer, 2026-10-01: she keeps a placeholder row for every role "if needed or
not", so nothing is uncovered, and marks 1 for a first hold, 2 for a second.
Her Crew Holds sheet stacks several jobs on one page.

- A hire's status (job_hires.status): hold → confirmed, or released. Every
  hire from before this was confirmed, and still is. Only CONFIRMED people go
  on a day's crew, the rooming list, per diem and "Download all" — a second
  hold who never books must not end up on a hotel's list (Patrick, 2026-10-02).
- A hold's rank (job_hires.hold_rank): 1st or 2nd.
- Role slots (jobs.role_slots): the job's checklist — each role Open, Not
  needed, or filled by a hire. Filling one hires someone into it, so nothing
  downstream ever sees a nameless row.

The Holds view stacks every upcoming job: roles and people down the side, the
job's dates across, 1 / 2 / ✓ in the cells — and flags the same person on
two jobs on the same date.
"""

import uuid
from datetime import date

from services.job_dates import DAY_TYPES, DatesError, _days, effective_dates, hire_base, works_on

STATUSES = ("hold", "confirmed", "released")
SLOT_STATES = ("open", "not_needed")
SLOTS_MAX = 40

# Her sheet's fixed role rows, in its order — offered as a starting checklist.
DEFAULT_ROLES = ("Producer", "Photographer", "Photo Assist 1st", "Photo Assist 2nd", "Digital Tech",
                 "Videographer", "Stylist", "Styling Assist", "HMU", "Set Designer/Props")


def status_of(hire: dict) -> str:
    """A database without holds.sql has no status: everyone's confirmed."""
    s = hire.get("status")
    return s if s in STATUSES else "confirmed"


def is_booked(hire: dict) -> bool:
    return status_of(hire) == "confirmed"


def status_label(hire: dict) -> str:
    s = status_of(hire)
    if s == "hold":
        return {1: "1st hold", 2: "2nd hold"}.get(hire.get("hold_rank"), "Hold")
    return "Confirmed" if s == "confirmed" else "Released"


def validate_status(status, rank) -> tuple[str, int | None]:
    if status not in STATUSES:
        raise DatesError(f"Status is one of: {', '.join(STATUSES)}.")
    if status != "hold":
        return status, None
    if rank not in (1, 2, None):
        raise DatesError("A hold is a 1st or a 2nd.")
    return status, rank or 1


def validate_slots(value, hire_ids: set[str]) -> list[dict]:
    """[{id, role, state, hire_id}]. A hire_id that isn't on this job is
    dropped (the slot goes back to open), never trusted."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise DatesError("Roles must be a list.")
    if len(value) > SLOTS_MAX:
        raise DatesError(f"That's more than {SLOTS_MAX} roles on one job.")
    out = []
    for s in value:
        if not isinstance(s, dict):
            raise DatesError("Each role must be an object.")
        role = s.get("role")
        if not isinstance(role, str) or not " ".join(role.split()):
            raise DatesError("Each role needs a name, like HMU.")
        role = " ".join(role.split())
        if len(role) > 80:
            raise DatesError("Keep a role's name under 80 characters.")
        state = s.get("state") or "open"
        if state not in SLOT_STATES:
            raise DatesError("A role is open or not needed.")
        hire_id = str(s["hire_id"]) if s.get("hire_id") and str(s["hire_id"]) in hire_ids else None
        out.append({"id": str(s.get("id") or uuid.uuid4()), "role": role, "state": state, "hire_id": hire_id})
    return out


# ── The Holds view ───────────────────────────────────────────────────────────

def _job_dates(job: dict) -> list[str]:
    crew = job.get("crew_dates") or {}
    every = sorted({d.isoformat() for t in DAY_TYPES for d in _days(crew.get(t, []))})
    if not every:
        return []
    return [d.isoformat() for d in _days([[every[0], every[-1]]])]


def _person_key(hire: dict) -> str:
    """Who someone is across jobs: their Roster record, else their email,
    else their name. The same rule of thumb as the matcher, kept simple —
    this only ever raises a flag, it never merges anyone."""
    if hire.get("roster_id"):
        return f"r:{hire['roster_id']}"
    if (hire.get("email") or "").strip():
        return f"e:{hire['email'].strip().lower()}"
    return f"n:{' '.join((hire.get('name') or '').lower().split())}"


def build_holds(jobs: list[dict], hires: list[dict], today: str | None = None) -> dict:
    """Every upcoming job (its last date today or later, or no dates yet),
    stacked: a row per open role and per person not released, a cell per job
    date they work — "1" / "2" for a hold, "✓" confirmed. `conflicts` names
    anyone on two jobs on one date."""
    today = today or date.today().isoformat()
    by_job: dict[str, list[dict]] = {}
    for h in hires:
        by_job.setdefault(h["job_id"], []).append(h)

    blocks, worked = [], {}            # worked: (person, date) -> [(job name, label)]
    for job in jobs:
        dates = _job_dates(job)
        if dates and dates[-1] < today:
            continue
        mine = [h for h in by_job.get(job["id"], []) if status_of(h) != "released"]
        slots = job.get("role_slots") or []
        slot_of = {s["hire_id"]: s for s in slots if s.get("hire_id")}
        rows = []
        for h in sorted(mine, key=lambda h: (h.get("sort_order") or 0)):
            eff = effective_dates(hire_base(job, h), h.get("dates_override"))
            mark = "✓" if is_booked(h) else str(h.get("hold_rank") or 1)
            cells = {d: mark for d in dates if works_on(eff, d)}
            for d in cells:
                worked.setdefault((_person_key(h), d), []).append((job["name"], status_label(h), h.get("name")))
            slot = slot_of.get(h["id"])
            rows.append({"kind": "hire", "hire_id": h["id"], "slot_id": slot["id"] if slot else None,
                         "role": (slot or {}).get("role") or h.get("role") or "", "name": h.get("name"),
                         "status": status_of(h), "label": status_label(h), "cells": cells,
                         # Talent hold in their own section, grouped by segment.
                         "talent": h.get("kind") == "talent", "segment": h.get("segment")})
        # A role is open until someone who isn't released fills it — a released
        # hold leaves the role to recast, not quietly "filled by nobody".
        live = {h["id"] for h in mine}
        open_slots = [s for s in slots if s.get("state", "open") == "open" and s.get("hire_id") not in live]
        rows += [{"kind": "slot", "slot_id": s["id"], "hire_id": None, "role": s["role"], "name": None,
                  "status": "open", "label": "Not cast", "cells": {}, "talent": False, "segment": None}
                 for s in open_slots]
        blocks.append({
            "job": {"id": job["id"], "name": job.get("name"), "client_name": job.get("client_name")},
            "dates": dates, "rows": rows,
            "open_roles": len(open_slots),
            "holds": sum(1 for h in mine if status_of(h) == "hold"),
        })
    blocks.sort(key=lambda b: (b["dates"][0] if b["dates"] else "9999", b["job"]["name"] or ""))

    # One entry per person and set of jobs, with every date they clash on —
    # not a line per date, which turned three overlaps into sixteen lines.
    grouped: dict[tuple, dict] = {}
    for (who, d), where in sorted(worked.items(), key=lambda kv: kv[0][1]):
        if len({w[0] for w in where}) < 2:
            continue
        key = (who, tuple(sorted({w[0] for w in where})))
        entry = grouped.setdefault(key, {"name": where[0][2], "dates": [],
                                          "jobs": [{"job": j, "label": label} for j, label, _n in where]})
        entry["dates"].append(d)
    conflicts = sorted(grouped.values(), key=lambda c: (c["dates"][0], c["name"] or ""))
    return {"jobs": blocks, "conflicts": conflicts, "default_roles": list(DEFAULT_ROLES)}
