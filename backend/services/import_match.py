"""Deciding what a pasted call sheet row already is.

A producer pastes an old call sheet to save retyping thirty people. Some of them
are already on this shoot; more are already in the producer's Roster from another
job. Today every one is inserted blind, which is how a crew list ends up with the
same person twice and why nothing gets linked to the Roster.

This works out which is which, and does nothing about it. The producer decides in
the preview; `confirm` obeys whatever they chose. That ordering is deliberate —
silently dropping a row someone pasted on purpose is the failure mode to avoid,
and it is the same complaint a beta tester has now raised five different ways:
*let me decide this, not the tool.*

Identity comes from services/person_match.py, so the import, the roster auto-save
and the backfill cannot disagree about who is who.
"""

import logging

from services.person_match import find, Verdict

logger = logging.getLogger(__name__)

#: Fields carried by an import, compared against whatever already exists. A
#: difference here is the interesting case: not a duplicate to drop, but a
#: producer holding a newer call sheet than the app has.
COMPARED = ("role", "department", "email", "phone", "call_time")

ON_PROJECT = "on_project"
IN_ROSTER = "in_roster"
AMBIGUOUS = "ambiguous"
NEW = "new"

#: What each state does unless the producer says otherwise.
DEFAULT_ACTION = {
    ON_PROJECT: "skip",     # adding someone already here IS the duplicate
    IN_ROSTER: "add",       # known person, not on this shoot yet
    AMBIGUOUS: "add",       # can't identify them; adding is recoverable, merging isn't
    NEW: "add",
}


def _norm(v) -> str:
    return " ".join(str(v).split()).lower() if v is not None else ""


def _differences(pasted: dict, existing: dict) -> list[dict]:
    """Fields where the two disagree, ignoring anything blank on either side.

    A blank is missing information, not a contradiction — and reporting it as a
    difference would bury the real ones under noise on every row.
    """
    out = []
    for field in COMPARED:
        a, b = _norm(pasted.get(field)), _norm(existing.get(field))
        if a and b and a != b:
            out.append({"field": field, "pasted": pasted.get(field), "existing": existing.get(field)})
    return out


def classify(members: list[dict], project_rows: list[dict], roster_rows: list[dict]) -> list[dict]:
    """Annotate each pasted row with what it already is.

    `project_rows` is the crew already on this shoot; `roster_rows` the producer's
    saved crew. Both must already be scoped to the owner — this never filters, so
    handing it the wrong list is how one producer's data reaches another's.

    The project is checked first: already being on this shoot is the more urgent
    fact, and the one that produces a visible duplicate.
    """
    annotated = []
    for m in members:
        row = dict(m)

        on_project = find(m, project_rows)
        if on_project.verdict is Verdict.MATCH:
            row.update(match_state=ON_PROJECT,
                       match_id=on_project.entry["id"],
                       match_name=on_project.entry.get("name"),
                       differs=_differences(m, on_project.entry))
        elif on_project.verdict is Verdict.AMBIGUOUS:
            row.update(match_state=AMBIGUOUS, match_id=None, match_name=None, differs=[])
        else:
            in_roster = find(m, roster_rows)
            if in_roster.verdict is Verdict.MATCH:
                row.update(match_state=IN_ROSTER,
                           match_id=in_roster.entry["id"],
                           match_name=in_roster.entry.get("name"),
                           differs=_differences(m, in_roster.entry))
            elif in_roster.verdict is Verdict.AMBIGUOUS:
                row.update(match_state=AMBIGUOUS, match_id=None, match_name=None, differs=[])
            else:
                row.update(match_state=NEW, match_id=None, match_name=None, differs=[])

        row["action"] = DEFAULT_ACTION[row["match_state"]]
        annotated.append(row)
    return annotated


def classify_against_roster(client, people: list[dict], owner_ids: set[str]) -> list[dict]:
    """The Roster page's version of `classify`: each person marked new / already
    in the Roster / ambiguous, for both of its imports — a paste and an uploaded
    call sheet — so the two previews can't disagree.

    There is no project on the Roster page, so only the Roster is checked, and
    each person only against entries of their own `type` — a crew member and a
    client sharing an email are one producer wearing two hats, not a match.
    `owner_ids` must be the caller's accessible owners (auth.py); everything
    read is scoped to them.

    Informational only: /roster/import/confirm re-matches on the way in and
    fills blanks on a match rather than duplicating, whatever this said. So a
    failure here returns the people unannotated rather than failing an import
    the producer has already paid a model call for.
    """
    try:
        roster = client.table("roster").select("*").in_("owner_id", list(owner_ids)).execute().data
        by_type: dict[str, list[dict]] = {}
        for entry in roster:
            by_type.setdefault(entry.get("type") or "crew", []).append(entry)
        return [classify([p], [], by_type.get(p.get("type") or "crew", []))[0] for p in people]
    except Exception as e:
        logger.warning("roster import classification failed: %s", type(e).__name__)
        return people
