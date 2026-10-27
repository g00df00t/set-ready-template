"""The Budget tab's Estimate view: qty × rate, sections, signing and what it
locks, and a database without supabase/estimate.sql
(docs/estimate-reconcile-plan.md, PR 1; services/budget.py, routers/budget.py).

    cd backend && venv/bin/python tests/test_budget_estimate.py

Every line invented; the layout follows a typical photo/video estimate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from services import budget  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402
from routers import budget as budget_router  # noqa: E402
from models.budget import BudgetLineCreate, BudgetLineUpdate, EstimateSign, SectionRename  # noqa: E402
import routers.jobs as jobs_router  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def refused(name, fn, status, words=""):
    try:
        fn()
        check(name, False, "no error")
    except HTTPException as e:
        check(name, e.status_code == status and words in str(e.detail), (e.status_code, e.detail))


print("\nqty x rate")
check("3 x $1,300 is $3,900.00", budget.estimate_amount(3, 130_000) == 390_000)
check("2.5 x $1,234.57 rounds half-up once", budget.estimate_amount(2.5, 123_457) == 308_643)
check("a qty given as text", budget.estimate_amount("1.25", 100_001) == 125_001)
check("0.1 x 3 cents is exact, not float-drifted", budget.estimate_amount(0.1, 3) == 0)
check("no qty or no rate: nothing derived", budget.estimate_amount(None, 100) is None
      and budget.estimate_amount(2, None) is None and budget.estimate_amount("", 100) is None)
check("hundredths of 3 and 3.00 agree", budget.hundredths(3) == budget.hundredths("3.00") == 300)

print("\nSections")
s = budget.sections([{"section": "Crew", "est_cents": 100}, {"section": None, "est_cents": 5},
                     {"section": " Crew ", "est_cents": 200}, {"section": "Gear", "est_cents": None}])
check("in order of first appearance, subtotalled", s == [
    {"name": "Crew", "est_cents": 300, "lines": 2}, {"name": None, "est_cents": 5, "lines": 1},
    {"name": "Gear", "est_cents": 0, "lines": 1}], s)

print("\nRoutes")
J = "00000000-0000-0000-0000-0000000000e1"
OWN = {"o1"}
JOB = {"id": J, "owner_id": "o1", "name": "Example Spot", "crew_dates": {}, "production_fee_bp": 800,
       "pc_log_camera": "photography", "pc_log_generated": {}, "estimate_signed_on": None}
client = FakeClient({"jobs": [dict(JOB)], "job_budget_lines": [], "job_expenses": [], "job_invoices": []})
for mod in (budget_router, jobs_router):
    mod.get_client = lambda: client


def add(**kw):
    return budget_router.add_line(J, BudgetLineCreate(**kw), owner_ids=OWN)


def line(v, name):
    return next(ln for ln in v["lines"] if ln["name"] == name)


v = add(name="Gaffer", section="Crew expenses", qty=2, unit_amount_cents=130_000)
check("qty x rate becomes the amount", line(v, "Gaffer")["est_cents"] == 260_000)
check("the estimate is ready and unsigned", v["estimate"]["ready"] and v["estimate"]["signed_on"] is None)
v = add(name="Hero edit", section="Editorial", bucket="fee", est_cents=550_000)
v = add(name="Key grip", section="Crew expenses", qty=1, unit_amount_cents=120_000)
v = add(name="Flights", bucket="pass", est_cents=250_000, markup_bp=1500)
check("lines keep the order they were typed", [ln["name"] for ln in v["lines"]]
      == ["Gaffer", "Hero edit", "Key grip", "Flights"], [ln["name"] for ln in v["lines"]])
check("sections subtotal from the API", v["estimate"]["sections"] == [
    {"name": "Crew expenses", "est_cents": 380_000, "lines": 2},
    {"name": "Editorial", "est_cents": 550_000, "lines": 1},
    {"name": None, "est_cents": 250_000, "lines": 1}], v["estimate"]["sections"])
check("the estimate total", v["budget"]["estimate_cents"] == 1_180_000, v["budget"]["estimate_cents"])
check("a markup survives on an At cost line", line(v, "Flights")["markup_bp"] == 1500)

gaffer = line(v, "Gaffer")["id"]
v = budget_router.update_line(J, gaffer, BudgetLineUpdate(qty=3), owner_ids=OWN)
check("changing the qty re-works the amount", line(v, "Gaffer")["est_cents"] == 390_000)
hero = line(v, "Hero edit")["id"]
v = budget_router.update_line(J, hero, BudgetLineUpdate(est_cents=600_000), owner_ids=OWN)
check("a typed amount stays typed", line(v, "Hero edit")["est_cents"] == 600_000)
v = budget_router.update_line(J, hero, BudgetLineUpdate(bucket="rate"), owner_ids=OWN)
v = budget_router.update_line(J, hero, BudgetLineUpdate(bucket="fee"), owner_ids=OWN)

v = budget_router.rename_section(J, SectionRename(name="Crew expenses", to="Crew"), owner_ids=OWN)
check("renaming a heading moves its lines", [s["name"] for s in v["estimate"]["sections"]] == ["Crew", "Editorial", None])
refused("renaming a heading nobody uses is a 404",
        lambda: budget_router.rename_section(J, SectionRename(name="Nope", to="X"), owner_ids=OWN), 404)

v = add(name="Production fee", bucket="fee", floor_kind="production_fee", est_cents=0)
check("a floor line at $0 counts as quoted on purpose",
      next(f for f in v["budget"]["floor_lines"] if f["kind"] == "production_fee")["quoted"])

print("\nSigned")
v = budget_router.sign_estimate(J, EstimateSign(signed_on="2026-10-02"), owner_ids=OWN)
check("marking it signed records the date", v["estimate"]["signed_on"] == "2026-10-02"
      and client.db["jobs"][0]["estimate_signed_on"] == "2026-10-02")
refused("then a quoted amount can't change", lambda: budget_router.update_line(
    J, hero, BudgetLineUpdate(est_cents=1), owner_ids=OWN), 409, "locked")
refused("nor a qty", lambda: budget_router.update_line(J, gaffer, BudgetLineUpdate(qty=4), owner_ids=OWN), 409)
refused("nor a rate", lambda: budget_router.update_line(
    J, gaffer, BudgetLineUpdate(unit_amount_cents=1), owner_ids=OWN), 409)
v = budget_router.update_line(J, gaffer, BudgetLineUpdate(qty=3.0), owner_ids=OWN)
check("sending the same qty back isn't a change", line(v, "Gaffer")["est_cents"] == 390_000)
v = budget_router.update_line(J, gaffer, BudgetLineUpdate(name="Gaffer (2 days)", bucket="pass", block="Detroit"),
                              owner_ids=OWN)
g = line(v, "Gaffer (2 days)")
check("but name, basis and market still can", g["bucket"] == "pass" and g["block"] == "Detroit"
      and g["est_cents"] == 390_000, g)
refused("a new line can't carry a quote", lambda: add(name="Swing", est_cents=120_000), 409)
v = add(name="Fuel", bucket="pass", act_cents=4_000)
check("an unquoted line still goes on (it's for Reconcile)", line(v, "Fuel")["est_cents"] is None)
refused("a quoted line can't be removed", lambda: budget_router.delete_line(J, hero, owner_ids=OWN), 409, "Unlock")
v = budget_router.delete_line(J, line(v, "Fuel")["id"], owner_ids=OWN)
check("an unquoted one can", not any(ln["name"] == "Fuel" for ln in v["lines"]))
v = budget_router.rename_section(J, SectionRename(name="Crew", to="Crew expenses"), owner_ids=OWN)
check("a heading can still be renamed", v["estimate"]["sections"][0]["name"] == "Crew expenses")

v = budget_router.sign_estimate(J, EstimateSign(signed_on=None), owner_ids=OWN)
check("unlocking clears the date", v["estimate"]["signed_on"] is None)
v = budget_router.update_line(J, hero, BudgetLineUpdate(est_cents=650_000), owner_ids=OWN)
check("and the amounts edit again", line(v, "Hero edit")["est_cents"] == 650_000)

empty = FakeClient({"jobs": [{**JOB, "id": "j2"}], "job_budget_lines": [], "job_expenses": [], "job_invoices": []})
for mod in (budget_router, jobs_router):
    mod.get_client = lambda: empty
refused("an estimate with nothing quoted can't be signed",
        lambda: budget_router.sign_estimate("j2", EstimateSign(signed_on="2026-10-02"), owner_ids=OWN), 422)

print("\nBefore supabase/estimate.sql")
pre_job = {k: v for k, v in JOB.items() if k != "estimate_signed_on"}
line_cols = {"id", "job_id", "bucket", "block", "name", "note", "flag", "qty", "unit_amount_cents", "est_cents",
             "act_cents", "bill_cents", "markup_bp", "dropped", "awaiting_cost", "act_paid", "floor_kind",
             "sort_order", "created_at"}
pre = FakeClient({"jobs": [pre_job], "job_budget_lines": [], "job_expenses": [], "job_invoices": []},
                 schema={"jobs": set(pre_job), "job_budget_lines": line_cols,
                         "job_expenses": {"id", "job_id", "budget_line_id", "amount_cents", "sort_order", "created_at"},
                         "job_invoices": {"id", "job_id", "amount_cents", "paid", "sort_order", "created_at"}})
for mod in (budget_router, jobs_router):
    mod.get_client = lambda: pre
v = budget_router.get_budget(J, owner_ids=OWN)
check("the budget loads, saying the estimate isn't ready", v["migrated"] and v["estimate"]["ready"] is False)
v = add(name="Gaffer", qty=2, unit_amount_cents=130_000)
check("a line without a section still goes on", line(v, "Gaffer")["est_cents"] == 260_000)
v = budget_router.update_line(J, line(v, "Gaffer")["id"], BudgetLineUpdate(qty=1), owner_ids=OWN)
check("and edits", line(v, "Gaffer")["est_cents"] == 130_000)
refused("a section is a 503 naming the file", lambda: add(name="Grip", section="Crew"), 503, "estimate.sql")
refused("so is signing", lambda: budget_router.sign_estimate(J, EstimateSign(signed_on="2026-10-02"), owner_ids=OWN),
        503, "estimate.sql")
refused("and renaming a heading",
        lambda: budget_router.rename_section(J, SectionRename(name=None, to="Crew"), owner_ids=OWN), 503, "estimate.sql")

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("All passed.")
