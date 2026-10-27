"""Deal memo generation.

    cd backend && venv/bin/python tests/test_deal_memo.py

The property that matters, stated precisely: the two real templates the producer sent
(docs/master-record-documents-review.md §2) differ in exactly one place — an
Agent signature block, present only when the Roster entry has an agent. Every
other section is identical fixed boilerplate. This asserts that boundary,
plus the two degraded cases the router will actually hit in practice: a crew
member with no Roster link at all (rate/agency simply blank), and a project
with none of the three new optional fields set (client/production
company/payroll provider all fall back to generic phrasing instead of
rendering blank or raising).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.deal_memo_builder import build_deal_memo  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILS.append(name)


PROJECT = {
    "name": "Fall Lookbook",
    "client_name": "Northwind",
    "production_company": "Northwind Productions LLC",
    "payroll_provider": "Test Payroll Co",
}
CREW = {
    "name": "Susan Test", "role": "Stylist",
    "phone": "555-1212", "email": "susan@example.com",
    "deal_memo_dates": "Aug 24th - Mon - check in\nAug 25th - Tues - Shoot",
}
ROSTER_WITH_AGENT = {"day_rate": "$650/day", "rate_note": "10-hour scout/shoot days", "agent_name": "Jane Agent"}
ROSTER_NO_AGENT = {"day_rate": "$500/day", "rate_note": None, "agent_name": None}
LOCATION = {"location_name": "Parlay Studio NJ"}

print("\nAgent vs. no-agent — the one real structural difference")
with_agent = build_deal_memo(PROJECT, CREW, ROSTER_WITH_AGENT, LOCATION)
without_agent = build_deal_memo(PROJECT, CREW, ROSTER_NO_AGENT, LOCATION)

check("a Roster entry with an agent_name gets an Agent signature block",
      "<strong>Agent</strong>" in with_agent)
check("the agent's name is printed next to their signature line",
      "Jane Agent" in with_agent)
check("a Roster entry with no agent_name gets no Agent signature block",
      "<strong>Agent</strong>" not in without_agent)
check("both variants still get the Crew Member signature block",
      "<strong>Crew Member</strong>" in with_agent and "<strong>Crew Member</strong>" in without_agent)
check("both variants carry the same fixed boilerplate (Governing Law section)",
      "governed by the laws of the state" in with_agent
      and "governed by the laws of the state" in without_agent)

print("\nProject fields interpolate into the boilerplate, not just the header")
check("payroll provider is named in the Employment & Insurance section, not just the header",
      with_agent.count("Test Payroll Co") >= 2,
      "should appear in the header AND in section 5's boilerplate")
check("client name drives the Cancellation section, not just a header field",
      "Northwind" in with_agent and "8 days prior to the scheduled shoot" in with_agent)

print("\nA crew member with no Roster link at all")
no_roster = build_deal_memo(PROJECT, CREW, None, LOCATION)
check("renders without raising", isinstance(no_roster, str) and len(no_roster) > 0)
check("still shows the crew member's own name", "Susan Test" in no_roster)
check("gets no Agent block (nothing to know an agent from)",
      "<strong>Agent</strong>" not in no_roster)

print("\nA project with none of the three new optional fields set")
bare_project = {"name": "Untitled Test Shoot"}
bare = build_deal_memo(bare_project, CREW, ROSTER_NO_AGENT, None)
check("renders without raising", isinstance(bare, str) and len(bare) > 0)
check("falls back to generic phrasing rather than printing a blank or 'None'",
      "None" not in bare and "the Payroll Provider" in bare)
check("Client Terms section is skipped entirely with no client_name — nothing to point at",
      "Client Terms and Conditions" not in bare)

print("\nThe Jobs version: the Dates block from the crew dates plus the hire's own")
# The job stands in for the project (same name/client/production company/
# payroll fields) and a hire for the crew row; dates arrive formatted.
from services.job_dates import dates_block  # noqa: E402

JOB = {**PROJECT, "crew_dates": {
    "travel": [["2026-10-11", "2026-10-11"]],
    "shoot": [["2026-10-13", "2026-10-15"]],
    "travel_out": [["2026-10-16", "2026-10-16"]],
}}
HIRE = {"name": "Susan Test", "role": "Stylist", "phone": "555-1212", "email": "susan@example.com",
        "deal_memo_dates": "STALE FREE TEXT — must not print"}


def memo_for(override):
    return build_deal_memo(JOB, HIRE, ROSTER_NO_AGENT, LOCATION,
                           dates=dates_block(JOB["crew_dates"], override))


crew_only = memo_for({})
check("from the crew dates alone", "Oct 11th - Sun - Travel in" in crew_only
      and "Oct 13th (Tue) – Oct 15th (Thu) - Shoot day" in crew_only
      and "Oct 16th - Fri - Travel out" in crew_only)
check("the old free text on the row is ignored when dates are given", "STALE" not in crew_only)
custom = memo_for({"shoot": [["2026-10-14", "2026-10-15"]]})
check("from a custom override", "Oct 14th (Wed) – Oct 15th (Thu) - Shoot day" in custom
      and "Oct 13th (Tue)" not in custom)
local = memo_for({"travel": [], "travel_out": []})
check("an empty override is 'None' — a local hire gets no travel or wrap line",
      "Travel in" not in local and "Travel out" not in local and "Shoot day" in local)
two = memo_for({"shoot": [["2026-10-12", "2026-10-12"], ["2026-10-16", "2026-10-16"]], "travel_out": []})
check("two separate shoot blocks print as two lines, in order",
      two.index("Oct 12th - Mon - Shoot day") < two.index("Oct 16th - Fri - Shoot day"))
check("the job's payroll provider still reaches the boilerplate", custom.count("Test Payroll Co") >= 2)
check("the rate still comes from the Master Roster only", "$500/day" in custom)

print("\nThe Jobs memo prints what the producer's does (docs/producer-documents-map.md §4)")
from services.deal_memo_data import job_memo_dates, job_memo_location_line  # noqa: E402

noted = job_memo_dates(JOB, {"dates_override": {}, "dates_note": "Aug 26th - Wed - down day – ½ day rate"})
check("a dates note prints under the generated lines",
      noted.index("Oct 16th - Fri - Travel out") < noted.index("down day – ½ day rate"), noted)
check("no note, no trailing blank line", not job_memo_dates(JOB, {"dates_override": {}}).endswith("\n"))
check("a note alone still prints when there are no crew dates",
      job_memo_dates({"crew_dates": {}}, {"dates_note": "Check into hotel"}) == "Check into hotel")
check("the job's location line wins", job_memo_location_line({"location_line": " NJ and NY "}) == "NJ and NY")
check("no location line falls back (empty)", job_memo_location_line({}) == "")

producer_style = build_deal_memo(
    {**JOB, "per_diem_line": "$70/day for travel | $50/day shoot days"}, HIRE,
    {"day_rate": None, "rate_note": "Shoot day rate = $800\nTravel day rate = $400"}, {"location_name": "NJ and NY"},
    dates=noted)
check("the rate note keeps its line breaks", "Shoot day rate = $800<br>Travel day rate = $400" in producer_style)
check("no stray dash when there's a note but no day rate", "Rate:</td><td> —" not in producer_style)
check("the per diem line prints under Rate", "Per Diem:" in producer_style and "$70/day for travel | $50/day shoot days" in producer_style)
check("the location line prints", "NJ and NY" in producer_style)
check("the dates note reaches the memo", "down day – ½ day rate" in producer_style)
check("free text is still escaped", "&lt;b&gt;" in build_deal_memo(
    {**JOB, "per_diem_line": "<b>x</b>"}, HIRE, ROSTER_NO_AGENT, LOCATION, dates=""))
bare_hire = build_deal_memo(JOB, {"name": "Dana", "role": None, "email": None, "phone": None}, None, None, dates="")
check("a hire with no role or email prints blanks, never 'None'", ">None<" not in bare_hire, bare_hire[:0])
check("the day version has no per diem line", "Per Diem:" not in build_deal_memo(PROJECT, CREW, ROSTER_NO_AGENT, LOCATION))

print("\nThe producer's 2026-10-01 notes: bold labels, download only the ones ticked")
check("labels are bold, the way her marked-up memo asks",
      "td.label { font-weight: 700;" in without_agent)
from services.deal_memo_data import select_hires  # noqa: E402
_hires = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
check("no selection means everyone (Download all)", select_hires(_hires, None) == _hires)
check("a selection keeps the job's order, not the ticking order",
      [h["id"] for h in select_hires(_hires, ["c", "a"])] == ["a", "c"])
check("an id from another job matches nothing", select_hires(_hires, ["zzz"]) == [])

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
