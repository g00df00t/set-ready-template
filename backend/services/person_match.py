"""Deciding whether two records are the same person.

One definition, used by everything that needs it — the roster backfill, the
auto-save that fires when someone is added to a project, and (next) the import
preview. If these disagree about who is who, the app creates duplicates in one
place while claiming to prevent them in another.

WHAT COUNTS, AND WHY IT IS NOT THE NAME

Measured on production data, 2026-09-05:

  * 202 distinct contact identities (a shared email or phone).
  * 5 of them carried MORE THAN ONE spelling of the same person's name — one
    person was entered five different ways.
  * 1 name mapped to more than two different contact values, i.e. genuine
    same-name-different-people collisions are rare but real.

So a name is weak in both directions: it misses the same person spelled two ways,
and it merges two people who happen to share a name. Contact details decide;
the name is corroboration.

That is not academic. `add_roster_entry` used to match on `ilike(name)` — exact
apart from case — which is precisely how one producer's roster ended up holding
three copies of him: "Pat", "Pat Kehoe", "patrick kehoe". Each new spelling
looked like a new person.

WHY A NAME MATCH IS STILL USED, CAREFULLY

Someone saved with no email or phone has nothing else to match on. Adding
"Dana Whitfield" with an email, when a contactless "Dana Whitfield" already
exists, should fill in the blank rather than create a second Dana. So an exact
name match counts — but ONLY when the existing entry holds no contact detail
that CONTRADICTS the new one. Filling a blank is safe; overwriting a different
number means it is probably a different person.

AMBIGUITY IS AN ANSWER

When more than one entry matches, the verdict is AMBIGUOUS and the caller must
not pick one. Guessing silently merges two humans and there is no undo. On
2026-09-05 a single contact identity mapped to six roster entries — a producer's
own details reused across test personas including his dog — and every automatic
path correctly refused to act.
"""

import re
from dataclasses import dataclass
from enum import Enum

_NON_DIGITS = re.compile(r"\D+")


class Verdict(Enum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


@dataclass(frozen=True)
class Match:
    verdict: Verdict
    #: The single entry matched, when verdict is MATCH.
    entry: dict | None = None
    #: Every candidate, when verdict is AMBIGUOUS — so a caller can show them.
    candidates: tuple = ()
    #: True when a MATCH was reached on the name alone. Weaker; worth surfacing.
    by_name_only: bool = False
    #: True when a MATCH spells the name differently. Not an error — it is the
    #: drift this exists to fix — but the caller should say so before the
    #: roster's spelling starts winning.
    name_differs: bool = False


def email_key(value) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip().lower() or None


def phone_key(value) -> str | None:
    """Last 10 digits, so "+1 (555) 014-9544" and "5550149544" are one number."""
    if not isinstance(value, str):
        return None
    digits = _NON_DIGITS.sub("", value)
    return digits[-10:] if len(digits) >= 10 else None


def name_key(value) -> str:
    """Case-folded, whitespace-collapsed. Deliberately NOT fuzzy — a nickname is
    a different string and should be caught by contact details instead."""
    return " ".join((value or "").split()).lower() if isinstance(value, str) else ""


def contact_keys(record: dict) -> set[str]:
    return {k for k in (email_key(record.get("email")), phone_key(record.get("phone"))) if k}


def contradicts(candidate: dict, existing: dict) -> bool:
    """True when both hold the same kind of contact detail and they disagree.

    A blank on either side is not a contradiction — it is the gap being filled,
    which is the whole reason a name match is allowed at all.
    """
    a, b = email_key(candidate.get("email")), email_key(existing.get("email"))
    if a and b and a != b:
        return True
    a, b = phone_key(candidate.get("phone")), phone_key(existing.get("phone"))
    if a and b and a != b:
        return True
    return False


def find(candidate: dict, existing: list[dict]) -> Match:
    """Which of `existing` is `candidate`?

    `existing` must already be scoped to one owner — and to one roster type where
    that matters. This function never filters by owner, so passing it the wrong
    list is how one producer's data reaches another's.
    """
    by_contact = [e for e in existing if contact_keys(candidate) & contact_keys(e)]
    if len(by_contact) == 1:
        e = by_contact[0]
        return Match(Verdict.MATCH, entry=e,
                     name_differs=name_key(candidate.get("name")) != name_key(e.get("name")))
    if len(by_contact) > 1:
        # Contact details established a GROUP, not a person. Within that group the
        # name is a fair discriminator — it is the only thing separating them.
        # This is the real 2026-09-05 shape: a producer's own email and phone
        # reused across "Pat Kehoe", "Mandy" and "Suki" (his dog). Adding Suki
        # again should find Suki, not throw up its hands or pick the producer.
        narrowed = [e for e in by_contact
                    if name_key(e.get("name")) == name_key(candidate.get("name"))]
        if len(narrowed) == 1:
            return Match(Verdict.MATCH, entry=narrowed[0])
        return Match(Verdict.AMBIGUOUS, candidates=tuple(by_contact))

    # No contact overlap. Fall back to an exact name, but only where the existing
    # entry holds nothing that contradicts — see the module docstring.
    cname = name_key(candidate.get("name"))
    if not cname:
        return Match(Verdict.NONE)
    by_name = [e for e in existing
               if name_key(e.get("name")) == cname and not contradicts(candidate, e)]
    if len(by_name) == 1:
        return Match(Verdict.MATCH, entry=by_name[0], by_name_only=True)
    if len(by_name) > 1:
        return Match(Verdict.AMBIGUOUS, candidates=tuple(by_name))
    return Match(Verdict.NONE)
