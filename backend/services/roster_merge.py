"""Merging Roster entries that turned out to be one person.

This could not be built before `roster_id`. Without the link, "merge" could only
mean deleting one entry while every project row went on holding its own stale
copy — nothing would have been repaired, and the producer would have lost a
record for no benefit. With it, the rows can be repointed first and the merge
actually fixes something.

Order matters and is the whole safety story:

  1. repoint every crew/talent/contact row from the losers to the survivor
  2. fill blanks on the survivor from the losers, never overwrite
  3. only then delete the losers

Repointing first means a failure between steps leaves duplicates — recoverable —
rather than rows pointing at an entry that no longer exists. And the schema backs
that up: roster_id is ON DELETE SET NULL, so even the worst case unlinks people
rather than blanking a shoot's contact details.

⚠️ Merging is never automatic and never inferred. A group is a question; the
producer answers it. On 2026-09-05 a single contact identity covered a producer,
a stylist and a dog.
"""

import logging

logger = logging.getLogger(__name__)

LINKED_TABLES = ("crew_members", "talent", "project_contacts")

#: Filled on the survivor when it has nothing there. Never overwritten — the
#: producer chose which entry survives, and its own values are the answer.
FILLABLE = ("email", "phone", "role", "department", "organization")


def merge_entries(client, owner_id: str, keep_id: str, drop_ids: list[str]) -> dict:
    """Fold `drop_ids` into `keep_id`. Returns what actually moved."""
    drop_ids = [d for d in drop_ids if d and d != keep_id]
    if not drop_ids:
        return {"repointed": 0, "deleted": 0, "filled": []}

    # Ownership is checked by reading, not assumed from the request. A merge that
    # trusted ids from the client could fold another producer's contacts away.
    owned = {r["id"]: r for r in
             client.table("roster").select("*").eq("owner_id", owner_id).execute().data}
    if keep_id not in owned:
        raise ValueError("survivor is not on this roster")
    drop_ids = [d for d in drop_ids if d in owned]
    if not drop_ids:
        raise ValueError("nothing to merge")

    # 1 — repoint first, so a failure leaves duplicates rather than orphans
    repointed = 0
    for table in LINKED_TABLES:
        for d in drop_ids:
            rows = client.table(table).select("id").eq("roster_id", d).execute().data
            for row in rows:
                client.table(table).update({"roster_id": keep_id}).eq("id", row["id"]).execute()
                repointed += 1

    # Hires on a job link to the Roster the same way. Best-effort: a database
    # without the job tables yet must still be able to merge, and a hire left
    # pointing at a deleted entry is only unlinked (ON DELETE SET NULL).
    try:
        for d in drop_ids:
            for row in client.table("job_hires").select("id").eq("roster_id", d).execute().data:
                client.table("job_hires").update({"roster_id": keep_id}).eq("id", row["id"]).execute()
    except Exception as e:
        logger.error("job bookkeeping: repointing hires failed in merge: %s", e, exc_info=True)

    # 2 — fill the survivor's blanks from the entries being folded in, so a merge
    #     never loses the one place a detail was recorded
    keep = owned[keep_id]
    fill = {}
    for field in FILLABLE:
        if (keep.get(field) or "").strip():
            continue
        for d in drop_ids:
            value = (owned[d].get(field) or "").strip()
            if value:
                fill[field] = value
                break
    if fill:
        client.table("roster").update(fill).eq("id", keep_id).eq("owner_id", owner_id).execute()

    # 3 — and only now delete
    deleted = 0
    for d in drop_ids:
        client.table("roster").delete().eq("id", d).eq("owner_id", owner_id).execute()
        deleted += 1

    return {"repointed": repointed, "deleted": deleted, "filled": sorted(fill)}
