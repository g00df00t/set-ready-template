"""Making sure the people on a shoot end up in the producer's Roster.

Adding someone to a project one at a time has always saved them to the Roster
too — the frontend fires a /roster POST straight after. Pasting thirty people did
not, so a producer who imported a call sheet got a crew list and an address book
that still had never heard of any of them.

The difference was never intentional. It is the same act at a different scale,
and scale is the only thing that changes: thirty at once deserves to be stated
("24 will also be saved to your Roster") where one at a time does not.

Identity comes from services/person_match.py, so importing cannot create the
duplicates the rest of this work exists to prevent.
"""

import logging

from services.person_match import find, Verdict

logger = logging.getLogger(__name__)


def ensure_all_in_roster(client, owner_id: str, people: list[dict], type_: str = "crew") -> list:
    """A Roster id for each person, creating entries for anyone missing.

    Returns a list positionally matching `people`; an entry is None only when
    saving failed, which is deliberately survivable — a producer's import must
    not fail because their address book could not be updated.

    One read and at most one bulk insert, however many people were pasted.
    """
    try:
        existing = client.table("roster").select("*").eq("owner_id", owner_id).eq("type", type_).execute().data
    except Exception as e:
        logger.warning("roster lookup failed during import for %s: %s", owner_id, e)
        return [None] * len(people)

    ids: list = [None] * len(people)
    pending: list[dict] = []          # rows to create, and their positions
    pending_at: list[int] = []

    for i, p in enumerate(people):
        if not (p.get("name") or "").strip():
            continue
        # Pending rows are searched too, so one paste listing the same person
        # twice creates a single Roster entry rather than two.
        found = find(p, existing + pending)
        if found.verdict is Verdict.MATCH:
            if found.entry in pending:
                ids[i] = None                      # filled in after the insert
                pending_at.append(i)
                continue
            ids[i] = found.entry["id"]
            continue
        row = {"owner_id": owner_id, "type": type_, "name": p.get("name"),
               "email": p.get("email") or None, "phone": p.get("phone") or None,
               "role": p.get("role") or None,
               "department": p.get("department") or None if type_ == "crew" else None}
        pending.append(row)
        pending_at.append(i)

    if not pending:
        return ids

    try:
        created = client.table("roster").insert(pending).execute().data
    except Exception as e:
        # The crew import itself has already succeeded or is about to; losing the
        # address-book half is worth a log, not an error the producer sees.
        logger.warning("roster insert failed during import for %s: %s", owner_id, e)
        return ids

    # Match created rows back to the people who asked for them, by identity
    # rather than by position — the insert may reorder, and a collapsed duplicate
    # means there are fewer rows back than positions waiting.
    for i in pending_at:
        found = find(people[i], created)
        if found.verdict is Verdict.MATCH:
            ids[i] = found.entry["id"]
    return ids
