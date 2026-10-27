"""Finding entries in a Roster that are probably the same person.

Detection is the valuable half. A producer with 74 saved contacts does not find
duplicates by scrolling, so an address book that cannot point at its own
collisions may as well not have any. The merge is the easy part once the app can
say where to look.

Grouping uses the same signals as services/person_match.py, kept separate because
the questions differ: person_match asks "which of these is this new person",
which needs one answer. This asks "which of these are each other", which is a
partition and has to hold groups of three or five — a producer's own details
reused across test personas once produced a group of six.

⚠️ A group is a QUESTION, never a conclusion. Two entries sharing a phone number
can be a duplicate, a couple, an assistant who books for someone, or a producer
who used their own mobile as a placeholder. Every group here has to be shown to
the person who knows which, and merging without asking would be the one
unrecoverable mistake this whole feature exists to avoid.
"""

from services.person_match import contact_keys, contradicts, name_key

#: Why a group was flagged. Ordered strongest first, and shown to the producer so
#: they can judge the evidence rather than trust the verdict.
BY_CONTACT = "shared_contact"
BY_NAME = "same_name"


def _union_groups(pairs: dict) -> list[list]:
    """Collapse overlapping keys into connected groups.

    Three entries where A shares an email with B and B shares a phone with C are
    one group of three, not two pairs — otherwise merging A into B leaves C
    behind, still a duplicate and now harder to see.
    """
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for ids in pairs.values():
        ids = list(ids)
        for other in ids[1:]:
            union(ids[0], other)

    out: dict = {}
    for x in list(parent):
        out.setdefault(find(x), []).append(x)
    return [g for g in out.values() if len(g) > 1]


def find_duplicate_groups(entries: list[dict]) -> list[dict]:
    """Groups of entries that are probably one person.

    `entries` must already be scoped to one owner and one roster type. This never
    filters, so passing the wrong list is how one producer's contacts get
    compared against another's.
    """
    by_id = {e["id"]: e for e in entries}

    contact_index: dict = {}
    for e in entries:
        for key in contact_keys(e):
            contact_index.setdefault(key, set()).add(e["id"])
    contact_index = {k: v for k, v in contact_index.items() if len(v) > 1}
    contact_groups = _union_groups(contact_index)
    already = {i for g in contact_groups for i in g}

    # Same name, no contact detail anywhere to confirm or deny it. Weaker, and
    # excluded when the entries are already grouped by something stronger.
    name_index: dict = {}
    for e in entries:
        if e["id"] in already:
            continue
        n = name_key(e.get("name"))
        if n:
            name_index.setdefault(n, set()).add(e["id"])
    # Only where nothing CONTRADICTS. Two Dana Whitfields with different emails
    # are two people, however alike the names — the same rule person_match uses
    # when it allows a name match at all, and the reason it is imported rather
    # than restated.
    compatible: dict = {}
    for n, ids in name_index.items():
        members = [by_id[i] for i in ids]
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if not contradicts(a, b):
                    compatible[(n, a["id"], b["id"])] = {a["id"], b["id"]}
    name_groups = _union_groups(compatible)

    groups = []
    for ids in contact_groups:
        members = [by_id[i] for i in ids]
        shared = sorted(
            {k for k in contact_keys(members[0])
             if sum(1 for m in members if k in contact_keys(m)) > 1}
        )
        groups.append({"reason": BY_CONTACT, "shared": shared, "entries": members})
    for ids in name_groups:
        members = [by_id[i] for i in ids]
        groups.append({"reason": BY_NAME,
                       "shared": [name_key(members[0].get("name"))],
                       "entries": members})

    # Biggest first: the worst tangle is the one worth resolving first.
    groups.sort(key=lambda g: (-len(g["entries"]), g["reason"]))
    return groups
