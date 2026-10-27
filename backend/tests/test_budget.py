"""Budget lines, expenses, invoices and the PC log's footer
(services/budget.py, services/pc_log.py, routers/budget.py).

    cd backend && venv/bin/python tests/test_budget.py

Checked against a real job first: tests/fixtures/reference_job_v7.json, the
reference reconciliation as the v7 prototype left it
(Patrick, 2026-10-02: "use v7 as the fixture"). Then an invented PC log,
tests/fixtures/pc_log_example.json, added up by hand. Then the routes,
including a database that hasn't had supabase/reconciliation.sql yet.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from models.budget import (BudgetLineCreate, BudgetLineUpdate, ExpenseCreate, ExpenseUpdate,  # noqa: E402
                           InvoiceCreate, InvoiceUpdate)
from services import budget as svc, pc_log  # noqa: E402
from tests.fake_supabase import FakeAPIError, FakeClient  # noqa: E402
from routers import budget as budget_router  # noqa: E402
import routers.jobs as jobs_router  # noqa: E402  (the _own_job the router uses)

FAILS = []
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def balances(t):
    return t["billed_cents"] == t["cost_cents"] + t["unreconciled_cents"] + t["profit_loss_cents"]


print("\nRounding")
check("half rounds up", svc.round_div(5, 10) == 1 and svc.round_div(15, 10) == 2)
check("under half rounds down", svc.round_div(14, 10) == 1)
check("negatives round away from zero", svc.round_div(-15, 10) == -2 and svc.round_div(-14, 10) == -1)
check("a 15% markup on 1,291.87 is 193.78", svc.markup_of(129187, 1500) == 19378)

print("\nThe reference job, v7")
dw = json.load(open(FIXTURES / "reference_job_v7.json"))
lines = [{**ln, "id": f"l{i}"} for i, ln in enumerate(dw["lines"])]
exp = dw["expected"]
t = svc.totals(lines, dw["invoices"])
check("the identity holds: billed = cost + unreconciled + P/L", balances(t), t)
for key in ("billed_cents", "cost_cents", "profit_loss_cents", "unreconciled_cents", "estimate_cents",
            "projected_billing_cents", "dropped_scope_cents", "expense_variance_cents", "margin_bp",
            "invoiced_cents", "received_cents", "left_to_invoice_cents", "cash_in_hand_cents",
            "committed_cents", "after_committed_cents", "markup_to_bill_cents"):
    check(f"{key} = {exp[key]}", t[key] == exp[key], t[key])
for b, want in exp["by_bucket"].items():
    got = {k: t["by_bucket"][b][k] for k in want}
    check(f"{b} bucket: {want}", got == want, got)
check("the estimate is the signed $66,370", t["estimate_cents"] == 6_637_000)
check("dropped scope + expense variance = estimate − projected billing",
      t["dropped_scope_cents"] + t["expense_variance_cents"] == t["estimate_cents"] - t["projected_billing_cents"])
by_key = {f"{ln['name']}|{ln['block'] or ''}": ln for ln in lines}
for key, want in exp["lines"].items():
    c = svc.calc(by_key[key])
    got = {k: c[k] for k in want}
    check(f"line {key.split('|')[0]!r}", got == want, got)
check("Detroit camera package keeps 552.42 of margin (owner's gear, bought-in rest)",
      svc.calc(by_key["Video camera package + media management|Detroit"])["profit_loss_cents"] == 55242)
check("per diem billed at receipted cost reads zero P/L",
      svc.calc(by_key["Crew per diem|Detroit"])["profit_loss_cents"] == 0)
check("an added fee line (retouching) bills and isn't 'unquoted'",
      not svc.calc(by_key["Photo retouching — 5 hrs @ 150|"])["unquoted"] and not t["unquoted"])
check("the cancellation fee, decided on nothing yet, bills nothing and isn't counted",
      svc.calc(by_key["Cancellation fee — dropped days|"])["billed_cents"] is None)
check("pass-throughs past the 10% band are flagged: ground transport and flights",
      [o["name"] for o in t["over_variance_band"]] == exp["over_variance_band"], t["over_variance_band"])
check("flights are 28.7% over (2,866 bp)",
      next(o for o in t["over_variance_band"] if o["name"].startswith("Flights"))["over_bp"] == 2866)
check("all three floor lines are present and unquoted",
      [f["kind"] for f in t["floor_lines"] if not f["quoted"]] == exp["floor_lines_unquoted"])
yak = [d for d in t["dropped"] if d["block"] == "Yakima"]
check("Yakima's six lines are dropped scope, 8,775 in all", len(yak) == 6 and sum(d["cents"] for d in yak) == 877500)
check("dropped scope has all three shapes", {d["why"] for d in t["dropped"]} == {"not shot", "days not worked", "scope reduced"})

print("\nFiltering by market")
det = svc.totals(lines, dw["invoices"], block="Detroit")
check("Detroit balances on its own", balances(det))
check("Detroit has no fee lines", det["by_bucket"]["fee"]["billed_cents"] == 0)
check("Detroit billed 15,485.77 — the client statement's Detroit subtotal", det["billed_cents"] == 1_548_577, det["billed_cents"])
proj = svc.totals(lines, dw["invoices"], block=None)
check("job-wide lines = fees + the drives", proj["billed_cents"] == 2_650_000 + 148_565, proj["billed_cents"])
parts = sum(svc.totals(lines, block=b)["billed_cents"] for b in (None, "Detroit", "Puget Sound", "Yakima"))
check("the markets and the job-wide lines add up to the whole", parts == t["billed_cents"])
check("cash is the whole job whatever the filter", det["received_cents"] == t["received_cents"])

print("\nOpen lines (the $21,545 bug)")
open_lines = [{"id": "a", "bucket": "rate", "name": "2nd camera", "est_cents": 420000},
              {"id": "b", "bucket": "rate", "name": "Sound", "est_cents": 390000, "bill_cents": 260000, "act_cents": 250000},
              {"id": "c", "bucket": "pass", "name": "Hotel", "est_cents": 250000},
              {"id": "d", "bucket": "rate", "name": "Unquoted fuel", "act_cents": 5492},
              {"id": "e", "bucket": "pass", "name": "Wifi", "act_cents": 1600}]
o = svc.totals(open_lines, [{"amount_cents": 500000, "paid": True}])
check("a quoted rate line with no cost is unreconciled, not profit", o["unreconciled_cents"] == 420000)
check("and the identity still holds", balances(o), o)
check("P/L is only what's known: 10,000 retained − 54.92 absorbed", o["profit_loss_cents"] == 10000 - 5492)
check("unquoted costs: rate fuel and pass wifi", o["unquoted_cents"] == 5492 + 1600)
check("committed = open rate billing + open pass estimates", o["committed_cents"] == 420000 + 250000)
check("after committed = received − cost − committed",
      o["after_committed_cents"] == 500000 - (250000 + 5492 + 1600) - 670000)
check("an empty budget has no margin", svc.totals([])["margin_bp"] is None)

print("\nExpenses roll into a line")
rolled = svc.with_expenses(
    [{"id": "pd", "bucket": "pass", "name": "Crew per diem", "est_cents": 82500, "act_cents": 99900},
     {"id": "x", "bucket": "pass", "name": "Untouched", "act_cents": 100}],
    [{"budget_line_id": "pd", "amount_cents": 7154}, {"budget_line_id": "pd", "amount_cents": 4536},
     {"budget_line_id": None, "amount_cents": 9999}])
check("a line with expenses takes their sum, ignoring the typed act",
      rolled[0]["act_cents"] == 11690 and rolled[0]["act_from_expenses"])
check("a line without keeps its own", rolled[1]["act_cents"] == 100 and not rolled[1]["act_from_expenses"])

print("\nThe PC log footer")
pc = json.load(open(FIXTURES / "pc_log_example.json"))
p = pc_log.totals(pc["rows"], pc["fee_bp"], pc["invoices"])
for key in ("total_cents", "fee_cents", "grand_total_cents", "advance_cents", "difference_cents"):
    check(f"{key} = {pc['expected'][key]}", p[key] == pc["expected"][key], p[key])
check("each column", p["by_category"] == pc["expected"]["by_category"], p["by_category"])
check("columns add up to the total", sum(p["by_category"].values()) == p["total_cents"])
check("a hidden line is off the log", p["total_cents"] < sum(r["amount_cents"] for r in pc["rows"]))
check("only PAID invoices are the advance", p["advance_cents"] == 1_000_000)
check("the nine categories, in her column order",
      list(pc_log.CATEGORIES.values()) == ["Photography", "Video", "Talent", "Stylist/HMU", "Art Dept/Props",
                                           "Location/Studio", "Production/Misc", "Producer", "Payroll Service Fee"])
check("the fee is taken once on the total: 8% of 7 cents is 1 cent, not 7 × 0", pc_log.totals(
    [{"amount_cents": 1, "category": "video"}] * 7, 800, [])["fee_cents"] == 1)

print("\nRoutes")
J, OTHER = "00000000-0000-0000-0000-0000000000b1", "00000000-0000-0000-0000-0000000000b2"
db = {"jobs": [{"id": J, "owner_id": "o1", "name": "Riverbend", "production_fee_bp": 800},
               {"id": OTHER, "owner_id": "o2", "name": "Not ours"}]}
client = FakeClient(db)
budget_router.get_client = jobs_router.get_client = lambda: client
OWN = {"o1"}

v = budget_router.get_budget(J, owner_ids=OWN)
check("an empty job reads empty, migrated", v["migrated"] and v["lines"] == [] and v["budget"]["billed_cents"] == 0)
v = budget_router.add_line(J, BudgetLineCreate(bucket="pass", name="  Flights ", block="Detroit",
                                               est_cents=250000, bill_cents=1, markup_bp=0), owner_ids=OWN)
line = v["lines"][0]
check("a line is added, its name tidied", line["name"] == "Flights" and line["block"] == "Detroit")
check("a bill override is dropped off a pass-through", line["bill_cents"] is None)
v = budget_router.update_line(J, line["id"], BudgetLineUpdate(bucket="rate", bill_cents=200000), owner_ids=OWN)
check("switching to rate keeps the override sent with it", v["lines"][0]["bill_cents"] == 200000)
v = budget_router.update_line(J, line["id"], BudgetLineUpdate(bucket="pass"), owner_ids=OWN)
check("switching back drops it", v["lines"][0]["bill_cents"] is None)
v = budget_router.add_expense(J, ExpenseCreate(budget_line_id=line["id"], payee="Example Air", amount_cents=140180,
                                               category="production_misc", spent_on="2026-10-12"), owner_ids=OWN)
check("an expense rolls into its line", v["lines"][0]["act_cents"] == 140180 and v["lines"][0]["act_from_expenses"])
check("and onto the PC log", v["pc_log"]["total_cents"] == 140180 and v["pc_log"]["fee_cents"] == 11214)
check("dates are stored as ISO", v["expenses"][0]["spent_on"] == "2026-10-12")
exp_id = v["expenses"][0]["id"]
v = budget_router.update_expense(J, exp_id, ExpenseUpdate(category="video"), owner_ids=OWN)
check("an expense's category changes", v["pc_log"]["by_category"]["video"] == 140180)
v = budget_router.add_invoice(J, InvoiceCreate(label="Advance", amount_cents=100000, paid=True), owner_ids=OWN)
check("a paid invoice is the advance", v["pc_log"]["advance_cents"] == 100000)
inv_id = v["invoices"][0]["id"]
v = budget_router.update_invoice(J, inv_id, InvoiceUpdate(paid=False), owner_ids=OWN)
check("unpaid, it isn't", v["pc_log"]["advance_cents"] == 0)

client.db["jobs"].append({"id": "j-x", "owner_id": "o1", "name": "Another of ours"})
other_line = budget_router.add_line("j-x", BudgetLineCreate(name="Elsewhere"), owner_ids=OWN)["lines"][0]
try:
    budget_router.add_expense(J, ExpenseCreate(budget_line_id=other_line["id"], amount_cents=1), owner_ids=OWN)
    check("an expense can't roll into another job's line", False, "not refused")
except HTTPException as e:
    check("an expense can't roll into another job's line", e.status_code == 404)

v = budget_router.delete_line(J, line["id"], owner_ids=OWN)
check("deleting a line keeps its expense, unlinked",
      v["lines"] == [] and len(v["expenses"]) == 1 and v["expenses"][0]["budget_line_id"] is None)
v = budget_router.delete_expense(J, exp_id, owner_ids=OWN)
check("an expense is deleted", v["expenses"] == [])
v = budget_router.delete_invoice(J, inv_id, owner_ids=OWN)
check("an invoice is deleted", v["invoices"] == [])

for name, fn in (("someone else's job", lambda: budget_router.get_budget(OTHER, owner_ids=OWN)),
                 ("a line that isn't on the job",
                  lambda: budget_router.update_line(J, "nope", BudgetLineUpdate(name="x"), owner_ids=OWN))):
    try:
        fn()
        check(f"{name} is a 404", False, "no error")
    except HTTPException as e:
        check(f"{name} is a 404", e.status_code == 404)

blocks = budget_router.add_line(J, BudgetLineCreate(name="Mixer", block="Detroit", est_cents=100), owner_ids=OWN)
budget_router.add_line(J, BudgetLineCreate(bucket="fee", name="Producer", est_cents=900), owner_ids=OWN)
check("the markets on the job are listed", blocks["blocks"] == ["Detroit"])
check("?block=project is the job-wide lines",
      budget_router.get_budget(J, block="project", owner_ids=OWN)["budget"]["billed_cents"] == 900)
check("?block=Detroit is that market",
      budget_router.get_budget(J, block="Detroit", owner_ids=OWN)["budget"]["billed_cents"] == 100)

print("\nBefore supabase/reconciliation.sql")
old = FakeClient({"jobs": [{"id": J, "owner_id": "o1", "name": "Riverbend"}]},
                 schema={"jobs": {"id", "owner_id", "name"}})
budget_router.get_client = jobs_router.get_client = lambda: old
v = budget_router.get_budget(J, owner_ids=OWN)
check("the budget reads empty and says it isn't migrated", v["migrated"] is False and v["lines"] == [])
check("the PC log falls back to the 8% default", v["pc_log"]["fee_bp"] == 800)
for name, fn in (("adding a line", lambda: budget_router.add_line(J, BudgetLineCreate(name="x"), owner_ids=OWN)),
                 ("adding an expense", lambda: budget_router.add_expense(J, ExpenseCreate(amount_cents=1), owner_ids=OWN)),
                 ("adding an invoice", lambda: budget_router.add_invoice(J, InvoiceCreate(label="x", amount_cents=1),
                                                                          owner_ids=OWN))):
    try:
        fn()
        check(f"{name} is a 503 naming the migration", False, "no error")
    except HTTPException as e:
        check(f"{name} is a 503 naming the migration", e.status_code == 503 and "reconciliation.sql" in e.detail)

broken = FakeClient({"jobs": [{"id": J, "owner_id": "o1", "name": "Riverbend"}]}, fail=("job_expenses",))
budget_router.get_client = jobs_router.get_client = lambda: broken
try:
    budget_router.get_budget(J, owner_ids=OWN)
    check("any other database error still raises — an outage never reads as empty", False, "swallowed")
except FakeAPIError:
    check("any other database error still raises — an outage never reads as empty", True)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("All budget checks passed.")
