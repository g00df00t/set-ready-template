"""Editing a Roster or Location Roster entry can clear a field.

    cd backend && venv/bin/python tests/test_roster_edits.py

The update routes used model_dump(exclude_none=True), which drops the null the
form sends for a field the producer just emptied. So an emptied phone number or
parking note came straight back after Save (found testing staging,
2026-09-28). Now what's sent is saved, what isn't sent is left alone, and a
required field can't be blanked.

Calls the route functions directly against tests/fake_supabase.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_supabase import FakeClient  # noqa: E402
from routers import location_roster, roster  # noqa: E402
from models.roster import RosterEntryCreate, RosterEntryUpdate  # noqa: E402
from models.location_roster import LocationRosterUpdate  # noqa: E402
from services import roster_sync, job_hires  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


R1 = "00000000-0000-0000-0000-0000000000e1"
L1 = "00000000-0000-0000-0000-0000000000f1"
DB = {
    "roster": [{"id": R1, "owner_id": "o1", "type": "talent", "name": "Ava Test", "email": "ava@example.com",
                "phone": "555-0100", "role": "Lead", "agency": "Silver Lining", "agent_name": "Jo Agent",
                "day_rate": "$900", "rate_note": None}],
    "location_roster": [{"id": L1, "owner_id": "o1", "name": "Pier 57", "address": "25 11th Ave",
                         "parking_notes": "Lot B", "parking_address": None, "additional_notes": None}],
    "projects": [], "crew_members": [], "talent": [], "project_contacts": [], "jobs": [], "job_hires": [],
    "call_sheets": [], "team_members": [],
}
client = FakeClient(DB)
for mod in (roster, location_roster, roster_sync, job_hires):
    mod.get_client = lambda: client


def entry():
    return next(r for r in DB["roster"] if r["id"] == R1)


print("\nRoster")
roster.update_roster_entry(R1, RosterEntryUpdate(name="Ava Test", phone=None, email="ava@example.com"),
                           owner_ids={"o1"}, write_owner_id="o1")
check("an emptied phone is cleared", entry()["phone"] is None, entry())
check("fields not sent are untouched (agency, agent, rate)",
      entry()["agency"] == "Silver Lining" and entry()["agent_name"] == "Jo Agent" and entry()["day_rate"] == "$900", entry())
roster.update_roster_entry(R1, RosterEntryUpdate(role="  "), owner_ids={"o1"}, write_owner_id="o1")
check("a whitespace-only value counts as empty", entry()["role"] is None, entry())
roster.update_roster_entry(R1, RosterEntryUpdate(name="", type=None), owner_ids={"o1"}, write_owner_id="o1")
check("the name can't be blanked", entry()["name"] == "Ava Test")
check("nor the type", entry()["type"] == "talent")
roster.update_roster_entry(R1, RosterEntryUpdate(department=None), owner_ids={"o1"}, write_owner_id="o1")
check("the inline department select can go back to none", entry().get("department") is None)
row = roster.update_roster_entry(R1, RosterEntryUpdate(), owner_ids={"o1"}, write_owner_id="o1")
check("an edit that sends nothing returns the entry unchanged", row["name"] == "Ava Test")

print("\nLocation Roster")
location_roster.update_location(L1, LocationRosterUpdate(name="Pier 57", parking_notes=None), owner_ids={"o1"})
loc = DB["location_roster"][0]
check("emptied parking notes are cleared", loc["parking_notes"] is None, loc)
check("the address wasn't sent, so it stays", loc["address"] == "25 11th Ave", loc)
location_roster.update_location(L1, LocationRosterUpdate(name=""), owner_ids={"o1"})
check("the name can't be blanked", DB["location_roster"][0]["name"] == "Pier 57")

print("\nAdding someone who's already on the Roster")
DB["roster"].append({"id": "r-grip", "owner_id": "o1", "type": "crew", "name": "Quinn Test",
                     "email": "quinn@example.com", "phone": None, "role": "Best Boy Grip"})
before = len(DB["roster"])
row = roster.add_roster_entry(RosterEntryCreate(type="crew", name="Quin Tester", email="QUINN@example.com",
                                                role="Grip", phone="555-0199", company="Grip Co",
                                                day_rate="$450"), owner_ids={"o1"}, write_owner_id="o1")
quinn = next(r for r in DB["roster"] if r["id"] == "r-grip")
check("no second entry is made", len(DB["roster"]) == before and row["id"] == "r-grip", row)
check("the saved role isn't overwritten by what was typed", quinn["role"] == "Best Boy Grip", quinn)
check("nor the saved email", quinn["email"] == "quinn@example.com", quinn)
check("a blank on the entry is filled in (phone)", quinn["phone"] == "555-0199", quinn)
check("...and so are company and day rate, not just contact details",
      quinn.get("company") == "Grip Co" and quinn.get("day_rate") == "$450", quinn)
check("the name typed into Add never replaces the saved one", quinn["name"] == "Quinn Test", quinn)

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
