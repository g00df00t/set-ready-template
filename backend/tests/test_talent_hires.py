"""Talent as hires (supabase/talent_hires.sql, services/talent_sheet.py).

    cd backend && venv/bin/python tests/test_talent_hires.py

Patrick's calls of 2026-10-02: talent get rooms but not per diem; never a
crew deal memo or a day's crew list (they go on its talent list); the agency
fee lives on the hire, 20% by default; the first document is her talent hold
sheet. Every crew-only path must keep ignoring talent.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from models.job import HireCreate, HireUpdate  # noqa: E402
from models.roster import RosterEntryUpdate  # noqa: E402
from routers import deal_memo as memo_router, holds as holds_router, jobs as jobs_router  # noqa: E402
from services import per_diem, rooming, talent_sheet  # noqa: E402
from services.holds import build_holds  # noqa: E402
from services.job_dates import talent_dates  # noqa: E402
from services.job_hires import sync_hire_to_days  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


J = "00000000-0000-0000-0000-0000000000b1"
R_MAYA = "00000000-0000-0000-0000-0000000000d1"
CREW = {"travel": [["2030-10-19", "2030-10-19"]], "shoot": [["2030-10-20", "2030-10-21"]],
        "travel_out": [["2030-10-22", "2030-10-22"]]}


def make_db():
    return {
        "jobs": [{"id": J, "owner_id": "o1", "name": "Fall", "client_name": "Northwind", "crew_dates": CREW,
                  "per_diem_shoot": 50, "per_diem_other": 70, "role_slots": []}],
        "projects": [{"id": "d1", "owner_id": "o1", "job_id": J, "name": "Fall", "shoot_date": "2030-10-20"},
                     {"id": "d2", "owner_id": "o1", "job_id": J, "name": "Fall", "shoot_date": "2030-10-21"}],
        "job_hires": [], "crew_members": [], "talent": [], "team_members": [],
        "roster": [{"id": R_MAYA, "owner_id": "o1", "type": "talent", "name": "Maya Lin", "email": "maya@example.com",
                    "agency": "Wilhelmina", "agent_name": "Jo Agent", "agent_email": "jo@example.com",
                    "based": "Seattle", "portfolio_url": "https://example.com/maya", "day_rate": "$1,500/day"}],
    }


def use(db):
    client = FakeClient(db)
    for mod in (jobs_router, holds_router, memo_router):
        mod.get_client = lambda: client
    return client


def hire(**kw):
    body = {"name": "Maya Lin", "email": "maya@example.com", "roster_id": R_MAYA, "kind": "talent",
            "segment": "Northwind Women", **kw}
    return jobs_router.add_hire(J, HireCreate(**body), owner_ids={"o1"}, write_owner_id="o1")


print("\nHiring talent")
db = make_db(); use(db)
out = hire()
maya = db["job_hires"][0]
check("a talent hire is kind talent, in her segment, with the 20% agency fee",
      maya["kind"] == "talent" and maya["segment"] == "Northwind Women" and maya["agency_fee_pct"] == 20, maya)
check("the rate fills in from the Roster like crew", maya.get("rate_shoot") == 1500)
check("talent go on each day's TALENT list, not its crew",
      sorted(r["project_id"] for r in db["talent"]) == ["d1", "d2"] and db["crew_members"] == [],
      (db["talent"], db["crew_members"]))
check("each talent row links back to the hire", all(r["hire_id"] == maya["id"] for r in db["talent"]))
try:
    hire()
    check("the same talent can't be hired twice", False)
except HTTPException as e:
    check("the same talent can't be hired twice", e.status_code == 409)
jobs_router.add_hire(J, HireCreate(name="Maya Lin", email="maya@example.com", role="Stylist", save_to_roster=False),
                     owner_ids={"o1"}, write_owner_id="o1")
check("...but the same person can also be crew (two different jobs to do)",
      len(db["job_hires"]) == 2 and db["job_hires"][1].get("kind", "crew") == "crew")
crew_id = db["job_hires"][1]["id"]
jobs_router.remove_hire(J, crew_id, owner_ids={"o1"})

print("\nNew talent go to the Roster as talent")
db2 = make_db(); use(db2)
jobs_router.add_hire(J, HireCreate(name="New Face", email="new@example.com", kind="talent"), owner_ids={"o1"}, write_owner_id="o1")
check("saved to the Master Roster typed talent", any(r["name"] == "New Face" and r["type"] == "talent" for r in db2["roster"]))

print("\nHolds, dates and corrections")
use(db)
jobs_router.update_hire(J, maya["id"], HireUpdate(status="hold", hold_rank=1), owner_ids={"o1"}, write_owner_id="o1")
check("a talent hold comes off the days' talent lists", db["talent"] == [])
jobs_router.update_hire(J, maya["id"], HireUpdate(status="confirmed"), owner_ids={"o1"}, write_owner_id="o1")
check("confirming puts her back on", len(db["talent"]) == 2)
db["talent"][0]["call_time"] = "07:00:00"
jobs_router.update_hire(J, maya["id"], HireUpdate(dates_override=talent_dates(["2030-10-21"])),
                        owner_ids={"o1"}, write_owner_id="o1")
check("a date change takes her off untouched days, keeps a day with a call time",
      sorted((r["project_id"], bool(r.get("call_time"))) for r in db["talent"]) == [("d1", True), ("d2", False)], db["talent"])
sync_hire_to_days(FakeClient(db), maya["id"], {"phone": "555-0199"})
check("a correction on the hire reaches her talent rows", all(r.get("phone") == "555-0199" for r in db["talent"]))
jobs_router.update_hire(J, maya["id"], HireUpdate(segment="  Northwind   Swim ", agency_fee_pct=15, notes="first choice"),
                        owner_ids={"o1"}, write_owner_id="o1")
maya = db["job_hires"][0]
check("segment, fee and notes save", (maya["segment"], maya["agency_fee_pct"], maya["notes"]) == ("Northwind Swim", 15, "first choice"))

print("\nWhat talent get, and don't")
job = db["jobs"][0]
check("no per diem for talent", per_diem.build_sheet(job, db["job_hires"])["rows"] == [])
check("but a room when they travel", any(r["name"] == "Maya Lin" for r in rooming.build_sheets(job, db["job_hires"])["sheets"][0]["rows"]))
try:
    memo_router.download_job_deal_memo(J, maya["id"], owner_ids={"o1"})
    check("no crew deal memo for talent", False)
except HTTPException as e:
    check("no crew deal memo for talent", e.status_code == 400)
try:
    memo_router.download_all_job_deal_memos(J, None, owner_ids={"o1"})
    check("Download all skips talent", False)
except HTTPException as e:
    check("Download all skips talent", e.status_code == 400)
listed = jobs_router.list_hires(J, owner_ids={"o1"})[0]
check("the hires list carries her agency, agent, home city and link",
      listed.get("talent_info") == {"agency": "Wilhelmina", "agent": "Jo Agent", "based": "Seattle",
                                    "portfolio_url": "https://example.com/maya"}, listed.get("talent_info"))
check("...and the days she's on", len(listed["days"]) == 2)
view = build_holds(db["jobs"], db["job_hires"], today="2030-10-01")["jobs"][0]["rows"][0]
check("the Holds view marks her as talent, with her segment", view["talent"] is True and view["segment"] == "Northwind Swim")

print("\nThe talent hold sheet")
sheet = talent_sheet.build_talent_sheet(job, db["job_hires"], {R_MAYA: db["roster"][0]})
row = sheet["segments"][0]["rows"][0]
check("titled client – job, grouped by segment", sheet["title"] == "Northwind – Fall" and sheet["segments"][0]["name"] == "Northwind Swim")
check("her columns", (row["agency"], row["agent"], row["rate"], row["based"], row["notes"], row["link"])
      == ("Wilhelmina", "Jo Agent", "$1,500 + 15%", "Seattle", "first choice", "https://example.com/maya"), row)
check("X (booked) across the days she works — a mark every font has",
      row["cells"] == {"2030-10-20": "X", "2030-10-21": "X", "2030-10-22": "X"}, row["cells"])
check("the files say what 1, 2 and X mean", "X = booked" in talent_sheet.to_html(sheet))
check("the day row reads like hers", sheet["dates"][1]["what"] == "SHOOT DAY")
check("rate with no fee is just the rate; no rate is blank",
      talent_sheet.rate_text({"rate_shoot": 900}) == "$900" and talent_sheet.rate_text({}) == "")
ws = load_workbook(io.BytesIO(talent_sheet.to_xlsx(sheet))).active
values = [list(r) for r in ws.iter_rows(values_only=True)]
check("the Excel has the segment, her headers and the row",
      any(v[0] == "Northwind Swim" for v in values) and any(v[:3] == ["AGENCY", "AGENT", "TALENT"] for v in values)
      and any(v[2] == "Maya Lin" and v[3] == "$1,500 + 15%" for v in values))
link_cell = next(ws.cell(row=i + 1, column=7) for i, v in enumerate(values) if v[2] == "Maya Lin")
check("the portfolio is a real hyperlink", link_cell.hyperlink and link_cell.hyperlink.target == "https://example.com/maya")
html = talent_sheet.to_html(sheet)
check("the PDF lists her with her link", "Maya Lin" in html and 'href="https://example.com/maya"' in html)
bad = talent_sheet.build_talent_sheet(job, db["job_hires"], {R_MAYA: {**db["roster"][0], "portfolio_url": "javascript:alert(1)"}})
check("⚠️ a non-web link never renders as a link", bad["segments"][0]["rows"][0]["link"] == ""
      and "javascript:" not in talent_sheet.to_html(bad))
check("what she typed is escaped", "&lt;b&gt;" in talent_sheet.to_html(
    {**sheet, "segments": [{"name": "<b>x</b>", "rows": []}]}))
resp = holds_router.download_talent_xlsx(J, owner_ids={"o1"})
check("the download names the job", "Talent%20Holds%20-%20Fall.xlsx" in resp.headers["content-disposition"])

print("\nRoster fields")
check("a portfolio link must be a web address", RosterEntryUpdate(portfolio_url="https://x.com").portfolio_url == "https://x.com")
try:
    RosterEntryUpdate(portfolio_url="javascript:alert(1)")
    check("javascript: links are refused", False)
except Exception:
    check("javascript: links are refused", True)

print("\nTalent keep their own schedule")
# Patrick, 2026-10-02: talent don't follow the crew. Crew fly in the 18th to
# prep the 19th, shoot the 20th–21st, fly out the 22nd; a model might fly in
# the 19th, shoot the 20th and leave the 21st.
db3 = make_db()
db3["jobs"][0]["crew_dates"] = {"travel": [["2030-10-18", "2030-10-18"]], "prep": [["2030-10-19", "2030-10-19"]],
                                "shoot": [["2030-10-20", "2030-10-21"]], "travel_out": [["2030-10-22", "2030-10-22"]]}
db3["projects"].append({"id": "d0", "owner_id": "o1", "job_id": J, "name": "Fall prep", "shoot_date": "2030-10-19"})
use(db3)
hire(shoot_days=["2030-10-20"])
maya3 = db3["job_hires"][0]
check("hired for one shoot day: in the day before, out the day after",
      {t: v for t, v in maya3["dates_override"].items() if v} ==
      {"travel": [["2030-10-19", "2030-10-19"]], "shoot": [["2030-10-20", "2030-10-20"]],
       "travel_out": [["2030-10-21", "2030-10-21"]]}, maya3["dates_override"])
check("on that shoot day's talent list only — not prep, not a travel day",
      [r["project_id"] for r in db3["talent"]] == ["d1"], db3["talent"])
jobs_router.add_hire(J, HireCreate(name="Sam Crew", email="sam@example.com", role="Gaffer", save_to_roster=False),
                     owner_ids={"o1"}, write_owner_id="o1")
check("crew still follow the crew, prep day included", sorted(c["project_id"] for c in db3["crew_members"]) == ["d0", "d1", "d2"])
listed = {h["name"]: h for h in jobs_router.list_hires(J, owner_ids={"o1"})}
check("the table shows her own dates, nothing inherited",
      listed["Maya Lin"]["effective_dates"]["prep"] == [] and listed["Maya Lin"]["effective_dates"]["wrap"] == [])
check("...no conflict for coming and going", listed["Maya Lin"]["conflicts"] == [])
check("...and no Prep/Scout line", "Prep" not in listed["Maya Lin"]["dates_text"])
job3 = db3["jobs"][0]
rows = {r["name"]: r for r in rooming.build_sheets(job3, db3["job_hires"])["sheets"][0]["rows"]}
check("rooming: her one night, the crew's four",
      rows["Maya Lin"]["cells"] == {"2030-10-19": "1", "2030-10-20": "1", "2030-10-21": "c/o"} and rows["Sam Crew"]["total"] == 4,
      (rows["Maya Lin"]["cells"], rows["Sam Crew"]["cells"]))
hold = talent_sheet.build_talent_sheet(job3, db3["job_hires"], {R_MAYA: db3["roster"][0]})["segments"][0]["rows"][0]
check("the talent hold sheet marks her dates only", "2030-10-19" in hold["cells"] and "2030-10-22" not in hold["cells"]
      and "2030-10-21" in hold["cells"], hold["cells"])
db3["jobs"][0]["crew_dates"] = {**db3["jobs"][0]["crew_dates"], "shoot": [["2030-10-23", "2030-10-24"]]}
listed = {h["name"]: h for h in jobs_router.list_hires(J, owner_ids={"o1"})}
check("when the crew's shoot moves, she doesn't — and she's flagged",
      listed["Maya Lin"]["effective_dates"]["shoot"] == [["2030-10-20", "2030-10-20"]]
      and [c["type"] for c in listed["Maya Lin"]["conflicts"]] == ["shoot"], listed["Maya Lin"]["conflicts"])
db3["jobs"][0]["crew_dates"] = {**db3["jobs"][0]["crew_dates"], "shoot": [["2030-10-20", "2030-10-21"]]}
jobs_router.update_hire(J, maya3["id"], HireUpdate(dates_override={**maya3["dates_override"], "prep": [["2030-10-19", "2030-10-19"]]}),
                        owner_ids={"o1"}, write_owner_id="o1")
check("a fitting on the prep day puts her on that day",
      sorted(r["project_id"] for r in db3["talent"]) == ["d0", "d1"], db3["talent"])
db5 = make_db(); use(db5)
hire()
check("no days picked: every crew shoot day", db5["job_hires"][0]["dates_override"]["shoot"] == [["2030-10-20", "2030-10-21"]])

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
