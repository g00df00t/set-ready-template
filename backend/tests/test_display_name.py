"""The producer's display name, on its way into an email From header.

    cd backend && venv/bin/python tests/test_display_name.py

user_metadata is writable by the user through Supabase's own auth API, so this
value is untrusted no matter what the account page allows. It ends up in the
From header of mail sent to a producer's entire crew, which is why the newline
cases below are the ones that matter.

Hostile inputs are built with chr() rather than written as literals, so this file
stays free of the control characters it is about.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import _clean_display_name, _NAME_MAX  # noqa: E402

LF, CR, TAB, NUL, ESC = chr(10), chr(13), chr(9), chr(0), chr(27)

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


def eq(label: str, raw, expected) -> None:
    got = _clean_display_name(raw)
    check(label, got == expected, f"{raw!r} -> {got!r}, wanted {expected!r}")


print("\nOrdinary names survive untouched")
eq("a plain name", "Pat Kehoe", "Pat Kehoe")
eq("a company name", "Kehoe Productions", "Kehoe Productions")
eq("an apostrophe", "Siobhan O'Connor", "Siobhan O'Connor")
eq("accents and a hyphen", "Jean-Luc Beart", "Jean-Luc Beart")
eq("an ampersand", "Smith & Co.", "Smith & Co.")

print("\nHeader injection is the reason this function exists")
# A newline becomes a space rather than vanishing: it is whitespace, and the
# same rule has to hold for tabs or words get welded together. What matters for
# the header is that no CR or LF survives, which the next check pins down.
eq("a newline becomes a space", "Pat" + LF + "Bcc: victim@example.com", "Pat Bcc: victim@example.com")
eq("CRLF likewise", "Pat" + CR + LF + "Bcc: victim@example.com", "Pat Bcc: victim@example.com")
check("no output can ever contain CR or LF",
      all((CR not in (r or "") and LF not in (r or ""))
          for r in [_clean_display_name(v) for v in
                    ["a" + LF + "b", "a" + CR + LF + "b", LF, CR, "a" + LF * 3 + "b"]]))
eq("a NUL byte", "Pat" + NUL + "Kehoe", "PatKehoe")
eq("an ANSI escape", "Pat" + ESC + "[31mKehoe", "Pat[31mKehoe")

print("\nWhitespace is tidied, not merely stripped")
eq("leading and trailing space", "  Pat Kehoe  ", "Pat Kehoe")
eq("a tab between words becomes one space", "Pat" + TAB + "Kehoe", "Pat Kehoe")
eq("a run of spaces collapses", "Pat    Kehoe", "Pat Kehoe")
eq("newlines between words leave a single space", "Pat " + LF + LF + " Kehoe", "Pat Kehoe")

print("\nNothing is nothing -- the caller falls back to plain 'Set Ready'")
eq("None", None, None)
eq("empty string", "", None)
eq("only spaces", "     ", None)
eq("only control characters", LF + CR + TAB, None)
eq("a non-string", 12345, None)
eq("a dict, in case metadata is malformed", {"full_name": "x"}, None)

print("\nLength is bounded")
out = _clean_display_name("Wolfeschlegelsteinhausenbergerdorff " * 6)
check(f"capped at {_NAME_MAX} characters", out is not None and len(out) <= _NAME_MAX,
      f"got {len(out or '')}")
check("a capped name has no trailing space", out == (out or "").strip())
eq("a name exactly at the cap is untouched", "A" * _NAME_MAX, "A" * _NAME_MAX)

print("\nWhat crew actually see on the From line")
for raw, expect in [("Pat Kehoe", "Pat Kehoe via Set Ready"), (None, "Set Ready"), ("   ", "Set Ready")]:
    n = _clean_display_name(raw)
    check(f"{raw!r} -> {expect!r}", (f"{n} via Set Ready" if n else "Set Ready") == expect)

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
