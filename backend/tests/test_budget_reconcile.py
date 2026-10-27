"""The Budget tab's Reconcile view through the routes: receipts on the PC log
pointed at an estimate line become its actual, what a signed estimate still
lets her record, the market filter, and the PC log's list of lines to pick
from (docs/estimate-reconcile-plan.md, PR 3). The arithmetic itself is
test_budget.py's, against the real reference job.

    cd backend && venv/bin/python tests/test_budget_reconcile.py

Every line and amount invented.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from services import budget  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402
from routers import budget as budget_router, jobs as jobs_router, pc_log as pc_router, vendors as vendors_router  # noqa: E402
from models.budget import BudgetLineCreate, BudgetLineUpdate, EstimateSign, ExpenseCreate, ExpenseUpdate  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


print("\nReceipts behind a line")
lines = budget.with_expenses([{"id": "a", "act_cents": 999}, {"id": "b", "act_cents": 5}],
                             [{"budget_line_id": "a", "amount_cents": 100}, {"budget_line_id": "a", "amount_cents": 250},
                              {"budget_line_id": None, "amount_cents": 7}])
check("a line's actual is the sum of its receipts, and says how many",
      lines[0]["act_cents"] == 350 and lines[0]["act_from_expenses"] and lines[0]["expense_count"] == 2, lines[0])
check("a line without any keeps its typed actual", lines[1]["act_cents"] == 5 and lines[1]["expense_count"] == 0)

J = "00000000-0000-0000-0000-0000000000a1"
OTHER = "00000000-0000-0000-0000-0000000000a2"
OWN = {"o1"}
JOB = {"id": J, "owner_id": "o1", "name": "Example Lookbook", "crew_dates": {}, "vendors": [], "hotels": [],
       "production_fee_bp": 800, "pc_log_camera": "photography", "pc_log_generated": {}, "estimate_signed_on": None,
       "per_diem_shoot": None, "per_diem_other": None}
client = FakeClient({"jobs": [dict(JOB), {**JOB, "id": OTHER, "owner_id": "o2"}], "job_hires": [], "projects": [],
                     "project_locations": [], "job_budget_lines": [], "job_expenses": [], "job_invoices": [],
                     "job_pc_log_sends": []})
for mod in (budget_router, jobs_router, pc_router, vendors_router):
    mod.get_client = lambda: client
pc_router._producer = lambda job: "Producer Example"


def line(v, name):
    return next(ln for ln in v["lines"] if ln["name"] == name)


budget_router.add_line(J, BudgetLineCreate(name="Lodging", bucket="pass", block="Detroit", est_cents=250_000), owner_ids=OWN)
budget_router.add_line(J, BudgetLineCreate(name="Sound mixer", bucket="rate", block="Detroit", qty=3,
                                           unit_amount_cents=130_000), owner_ids=OWN)
budget_router.add_line(J, BudgetLineCreate(name="Edit", bucket="fee", est_cents=650_000), owner_ids=OWN)
v = budget_router.add_line(J, BudgetLineCreate(name="Camera package", bucket="rate", block="Yakima", est_cents=140_000),
                           owner_ids=OWN)
lodging, mixer, camera = (line(v, n)["id"] for n in ("Lodging", "Sound mixer", "Camera package"))

print("\nThe PC log offers the estimate's lines")
log = pc_router.get_pc_log(J, owner_ids=OWN)
check("every line, with its heading and market", [b["name"] for b in log["budget_lines"]]
      == ["Lodging", "Sound mixer", "Edit", "Camera package"] and log["budget_lines"][0]["block"] == "Detroit",
      log["budget_lines"])

print("\nPointing receipts at a line")
budget_router.add_expense(J, ExpenseCreate(payee="Example Inn", description="2 rooms", amount_cents=98_000), owner_ids=OWN)
v = budget_router.add_expense(J, ExpenseCreate(payee="Example Inn", description="1 room", amount_cents=47_728,
                                               budget_line_id=lodging), owner_ids=OWN)
first = next(e for e in v["expenses"] if e["description"] == "2 rooms")["id"]
v = budget_router.update_expense(J, first, ExpenseUpdate(budget_line_id=lodging), owner_ids=OWN)
ln = line(v, "Lodging")
check("the line's actual is their sum", ln["act_cents"] == 145_728 and ln["act_from_expenses"] and ln["expense_count"] == 2, ln)
check("so it bills at cost", ln["calc"]["billed_cents"] == 145_728 and ln["calc"]["profit_loss_cents"] == 0)
log = pc_router.get_pc_log(J, owner_ids=OWN)
check("the PC log row says which line it's against",
      {r["budget_line_id"] for r in log["rows"] if r["source"] == "expense"} == {lodging})
try:
    budget_router.update_expense(J, first, ExpenseUpdate(budget_line_id="no-such-line"), owner_ids=OWN)
    check("a line that isn't this job's is refused", False, "accepted")
except HTTPException as e:
    check("a line that isn't this job's is refused", e.status_code == 404)
v = budget_router.update_expense(J, first, ExpenseUpdate(budget_line_id=None), owner_ids=OWN)
check("taking one off takes it out of the sum", line(v, "Lodging")["act_cents"] == 47_728)

print("\nA line with receipts stays open until all its costs are in")
ln = line(v, "Lodging")
check("an At cost line with one receipt is still open, heading for its estimate",
      ln["act_open"] and ln["calc"]["diff_cents"] is None and budget.projected(ln)[0] == 250_000, ln["calc"])
check("one receipt not against any line is counted, with its amount",
      v["unassigned_receipts"] == {"count": 1, "cents": 98_000}, v["unassigned_receipts"])
budget_router.update_expense(J, first, ExpenseUpdate(budget_line_id=mixer), owner_ids=OWN)
v = budget_router.get_budget(J, owner_ids=OWN)
m = line(v, "Sound mixer")
check("a Fixed line with a receipt below its quote: the rest is still billing with no cost yet",
      m["calc"]["unreconciled_cents"] == 390_000 - 98_000 and m["calc"]["profit_loss_cents"] is None, m["calc"])
t = v["budget"]
check("and the identity still holds", t["billed_cents"] == t["cost_cents"] + t["unreconciled_cents"] + t["profit_loss_cents"], t)
try:
    budget_router.update_line(J, mixer, BudgetLineUpdate(cost_final=True), owner_ids=OWN)
    check("before cost_final.sql, 'All costs in' is a 503 naming the file", False, "saved")
except HTTPException as e:
    check("before cost_final.sql, 'All costs in' is a 503 naming the file", e.status_code == 503 and "cost_final.sql" in e.detail)
for row in client.db["job_budget_lines"]:
    row.setdefault("cost_final", False)                       # the column, as the migration adds it
v = budget_router.update_line(J, mixer, BudgetLineUpdate(cost_final=True), owner_ids=OWN)
m = line(v, "Sound mixer")
check("'All costs in' closes it: what wasn't spent is kept",
      not m["act_open"] and m["calc"]["unreconciled_cents"] == 0 and m["calc"]["profit_loss_cents"] == 390_000 - 98_000, m["calc"])
budget_router.update_line(J, mixer, BudgetLineUpdate(cost_final=False), owner_ids=OWN)
budget_router.update_expense(J, first, ExpenseUpdate(budget_line_id=None), owner_ids=OWN)

print("\nOn a signed estimate")
budget_router.sign_estimate(J, EstimateSign(signed_on="2026-10-02"), owner_ids=OWN)
v = budget_router.update_line(J, mixer, BudgetLineUpdate(bill_cents=260_000, act_cents=260_000, act_paid=True), owner_ids=OWN)
m = line(v, "Sound mixer")
check("billing at (days not worked), the actual and paid still record",
      m["bill_cents"] == 260_000 and m["est_cents"] == 390_000 and m["act_paid"] and m["calc"]["profit_loss_cents"] == 0, m)
v = budget_router.update_line(J, camera, BudgetLineUpdate(dropped=True), owner_ids=OWN)
check("Not shot still records", line(v, "Camera package")["dropped"])
v = budget_router.update_line(J, line(v, "Edit")["id"], BudgetLineUpdate(awaiting_cost=True), owner_ids=OWN)
v = budget_router.add_line(J, BudgetLineCreate(name="Fuel", bucket="rate", block="Detroit", act_cents=5_492), owner_ids=OWN)
f = line(v, "Fuel")
check("a cost that wasn't on the estimate goes on", f["est_cents"] is None and f["calc"]["unquoted"])
t = v["budget"]
check("and is listed as unquoted, off the margin", t["unquoted_cents"] == 5_492 and f["calc"]["profit_loss_cents"] == -5_492)
check("dropped scope counts the line not shot and the days not worked",
      t["dropped_scope_cents"] == 140_000 + 130_000, t["dropped"])
check("the identity holds", t["billed_cents"] == t["cost_cents"] + t["unreconciled_cents"] + t["profit_loss_cents"], t)

print("\nThe market filter")
d = budget_router.get_budget(J, block="Detroit", owner_ids=OWN)["budget"]
check("one market's totals are only its lines",
      d["billed_cents"] == 47_728 + 260_000 and d["estimate_cents"] == 250_000 + 390_000, d["billed_cents"])
p = budget_router.get_budget(J, block="project", owner_ids=OWN)["budget"]
check("'project' is the whole-job lines", p["billed_cents"] == 650_000 and p["by_bucket"]["fee"]["billed_cents"] == 650_000)
check("the markets are listed for the chips", budget_router.get_budget(J, owner_ids=OWN)["blocks"] == ["Detroit", "Yakima"])

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("All passed.")
