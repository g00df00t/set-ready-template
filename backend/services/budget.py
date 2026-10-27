"""A job's budget: estimate lines and their reconciliation, on the budget
model of the reference job (docs/setready-budget-reconciliation-handoff.md). Pure — no database.

THE ONE PLACE this arithmetic lives (Patrick, 2026-10-02). The screen shows
what the API computed; the PC log, its snapshot and its Excel/PDF all read it
from here. tests/fixtures/reference_job_v7.json is the real job it's checked
against, and is what a client-side mirror would have to pass too.

A conventional budget-vs-actual table nets intended margin against real
overruns, so each line carries a BUCKET — its billing basis — and Profit/Loss
means something different in each:

    fee   billed as quoted (or at `act`, after a scope change); no cost
          underneath, so the billed figure IS the profit
    rate  billed at the quoted rate (`bill` overrides it when scope moved)
          whatever it cost — the difference is retained margin
    pass  billed at actual cost plus any markup — only the estimate variance
          matters

and the identity that has to hold, to the cent:

    Σ billed = Σ cost + Σ unreconciled + Σ profit/loss

`unreconciled` is a rate line that's quoted (so billable) with no cost booked
yet. Leaving it out once overstated a real job's profit by $21,545.

A line whose actual comes from PC log receipts is OPEN until the producer
ticks "All costs in" (cost_final; Patrick, 2026-10-02 — invoices trickle in).
Open, a Fixed line's quote not yet spent is still unreconciled, and an At cost
line still projects to its estimate; its cost is "so far". A typed actual is
taken as final, as it always was.

MONEY IS INTEGER CENTS and percentages are basis points, so no float enters a
total. A markup is rounded half-up to the cent once, per line, and that rounded
figure is the one every total uses — which is why the identity balances by
construction.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

BUCKETS = ("fee", "rate", "pass")
FLOOR_KINDS = ("production_fee", "insurance", "contingency")

# What "the estimate is signed" locks (supabase/estimate.sql): the quoted
# figures. Name, market, section and basis stay editable — the real job's
# per diem had to change basis at reconciliation (handoff §9).
QUOTED_FIELDS = ("qty", "unit_amount_cents", "est_cents")

# A pass-through this far over its estimate is worth a look (the prototype's
# "past your 10% variance band").
VARIANCE_BAND_BP = 1000


def round_div(numer: int, denom: int) -> int:
    """numer / denom, rounded half away from zero, in integers."""
    if denom <= 0:
        raise ValueError("denominator must be positive")
    q, r = divmod(abs(numer), denom)
    if 2 * r >= denom:
        q += 1
    return q if numer >= 0 else -q


def markup_of(cents: int, bp: int) -> int:
    return round_div(cents * (bp or 0), 10_000)


# ── The estimate ─────────────────────────────────────────────────────────────

def hundredths(qty) -> int | None:
    """A quantity (numeric(8,2): 3, 2.5, "1.25") as exact hundredths, never via
    a float sum. None when there isn't one."""
    if qty is None or qty == "":
        return None
    try:
        return int((Decimal(str(qty)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def estimate_amount(qty, unit_cents: int | None) -> int | None:
    """qty × rate, in cents, rounded half-up once: "3 × $1,300" is 390000.
    None unless both are set — then the amount is typed instead."""
    h = hundredths(qty)
    if h is None or unit_cents is None:
        return None
    return round_div(h * int(unit_cents), 100)


def sections(lines: list[dict]) -> list[dict]:
    """The estimate's headings in the order they first appear, each with its
    quoted subtotal and line count. A line with no section is under None."""
    out: dict[str | None, dict] = {}
    for line in lines:
        name = (line.get("section") or "").strip() or None
        s = out.setdefault(name, {"name": name, "est_cents": 0, "lines": 0})
        s["est_cents"] += line.get("est_cents") or 0
        s["lines"] += 1
    return list(out.values())


# ── One line ─────────────────────────────────────────────────────────────────

def with_expenses(lines: list[dict], expenses: list[dict]) -> list[dict]:
    """Lines with any expenses rolled into them take those expenses' sum as
    their actual cost — a typed act on such a line is ignored, so the two can
    never disagree. Marked `act_from_expenses` (and how many) so the screen
    can say so."""
    sums: dict[str, int] = {}
    counts: dict[str, int] = {}
    # "All costs in" — what decides whether a receipt line is still open.
    for e in expenses:
        if e.get("budget_line_id"):
            sums[e["budget_line_id"]] = sums.get(e["budget_line_id"], 0) + int(e["amount_cents"])
            counts[e["budget_line_id"]] = counts.get(e["budget_line_id"], 0) + 1
    out = []
    for line in lines:
        if line.get("id") in sums:
            out.append({**line, "act_cents": sums[line["id"]], "act_from_expenses": True,
                        "expense_count": counts[line["id"]], "act_open": not line.get("cost_final")})
        else:
            out.append({**line, "act_from_expenses": False, "expense_count": 0, "act_open": False})
    return out


def calc(line: dict) -> dict:
    """What one line bills, costs and makes. None means "not known yet",
    which is different from 0."""
    est, act, bill = line.get("est_cents"), line.get("act_cents"), line.get("bill_cents")
    diff = est - act if est is not None and act is not None else None
    out = {"est_cents": est, "act_cents": act, "diff_cents": diff, "billed_cents": None,
           "cost_cents": None, "profit_loss_cents": None, "unreconciled_cents": 0,
           "derived": False, "unquoted": False}

    if line.get("dropped"):
        # Quoted, not performed: kept on record, out of every total.
        return {**out, "diff_cents": None, "billed_cents": 0, "cost_cents": 0}

    bucket = line.get("bucket")
    if bucket == "fee":
        billed = act if act is not None else est
        return {**out, "billed_cents": billed, "cost_cents": 0, "profit_loss_cents": billed,
                "derived": act is None and est is not None}

    if bucket == "rate":
        rate = bill if bill is not None else est
        if rate is not None and act is not None and line.get("act_open"):
            # Receipts so far, more to come: the unspent quote is still unreconciled,
            # and profit is only known once it's gone over.
            return {**out, "diff_cents": None, "billed_cents": rate, "cost_cents": act,
                    "profit_loss_cents": rate - act if act >= rate else None,
                    "unreconciled_cents": rate - act if act < rate else 0}
        if rate is not None:
            return {**out, "billed_cents": rate, "cost_cents": act,
                    "profit_loss_cents": rate - act if act is not None else None,
                    "unreconciled_cents": rate if act is None else 0}
        if act is not None:
            # Nothing quoted means nothing billed: the whole cost is absorbed.
            return {**out, "billed_cents": 0, "cost_cents": act, "profit_loss_cents": -act, "unquoted": True}
        return out

    # pass-through
    if act is None:
        return out
    m = markup_of(act, line.get("markup_bp") or 0)
    return {**out, "billed_cents": act + m, "cost_cents": act, "profit_loss_cents": m,
            "unquoted": est is None, **({"diff_cents": None} if line.get("act_open") else {})}


def projected(line: dict) -> tuple[int, int]:
    """(billing, profit) this line is heading for, treating anything still open
    as landing on its estimate. What "left to invoice" is measured against."""
    if line.get("dropped"):
        return 0, 0
    est, act, bill = line.get("est_cents"), line.get("act_cents"), line.get("bill_cents")
    bucket = line.get("bucket")
    if bucket == "fee":
        billed = (act if act is not None else est) or 0
        return billed, billed
    if bucket == "rate":
        rate = bill if bill is not None else est
        if rate is not None:
            return rate, rate - act if act is not None else 0
        return 0, -act if act is not None else 0
    basis = act if act is not None else (est or 0)
    if line.get("act_open") and act is not None:
        basis = max(act, est or 0)          # receipts so far: still heading for the estimate
    m = markup_of(basis, line.get("markup_bp") or 0)
    return basis + m, m


# ── The whole budget ─────────────────────────────────────────────────────────

def _block(line: dict) -> str | None:
    return (line.get("block") or "").strip() or None


def totals(lines: list[dict], invoices: list[dict] | None = None, block: str | None = "*") -> dict:
    """Everything the budget screens and the panels need.

    `block="*"` is the whole job; None is the project-wide lines only (the
    prototype's "Fees" chip); a name is that market. Filtering is how "did
    Detroit go over" gets answered without fee revenue swamping it. The cash
    figures are always the whole job — invoices don't belong to a market.
    """
    invoices = invoices or []
    shown = [ln for ln in lines if block == "*" or _block(ln) == block]

    t = {"billed_cents": 0, "cost_cents": 0, "profit_loss_cents": 0, "unreconciled_cents": 0,
         "by_bucket": {b: {"billed_cents": 0, "cost_cents": 0, "profit_loss_cents": 0,
                           "est_cents": 0, "act_cents": 0, "diff_cents": 0} for b in BUCKETS},
         "estimate_cents": 0, "projected_billing_cents": 0, "projected_profit_cents": 0,
         "awaiting_cost": 0, "cost_unpaid_cents": 0}
    unreconciled, unquoted, dropped, over_band, markups = [], [], [], [], []

    for line in shown:
        c = calc(line)
        g = t["by_bucket"].get(line.get("bucket"))
        est, act, bill = line.get("est_cents"), line.get("act_cents"), line.get("bill_cents")
        t["estimate_cents"] += est or 0          # the signed estimate, dropped lines included
        label = {"id": line.get("id"), "name": line.get("name"), "block": _block(line)}

        if line.get("dropped"):
            if est:
                dropped.append({**label, "cents": est, "why": "not shot"})
            continue

        for k in ("billed_cents", "cost_cents", "profit_loss_cents"):
            if c[k] is not None:
                t[k] += c[k]
                if g is not None:
                    g[k] += c[k]
        if g is not None:
            g["est_cents"] += est or 0
            g["act_cents"] += act or 0
            g["diff_cents"] += c["diff_cents"] or 0
        t["unreconciled_cents"] += c["unreconciled_cents"]
        pb, pp = projected(line)
        t["projected_billing_cents"] += pb
        t["projected_profit_cents"] += pp
        if line.get("awaiting_cost") and act is None:
            t["awaiting_cost"] += 1
        if c["cost_cents"] and not line.get("act_paid"):
            t["cost_unpaid_cents"] += c["cost_cents"]

        if c["unreconciled_cents"]:
            unreconciled.append({**label, "cents": c["unreconciled_cents"]})
        if c["unquoted"]:
            unquoted.append({**label, "cents": act})
        # Dropped scope has three shapes; counting only the first once
        # reported $8,775 when the truth was $19,575.
        if line.get("bucket") == "rate" and est is not None and bill is not None and bill < est:
            dropped.append({**label, "cents": est - bill, "why": "days not worked"})
        elif line.get("bucket") == "fee" and est is not None and act is not None and act < est:
            dropped.append({**label, "cents": est - act, "why": "scope reduced"})
        if line.get("bucket") == "pass" and est and act is not None and (act - est) * 10_000 > est * VARIANCE_BAND_BP:
            over_band.append({**label, "over_bp": round_div((act - est) * 10_000, est)})
        if line.get("bucket") == "pass" and line.get("markup_bp") and act is not None:
            markups.append({**label, "cost_cents": act, "markup_cents": markup_of(act, line["markup_bp"])})

    dropped.sort(key=lambda d: -d["cents"])
    t["unreconciled"] = unreconciled
    t["unquoted"] = unquoted
    t["unquoted_cents"] = sum(u["cents"] for u in unquoted)
    t["dropped"] = dropped
    t["dropped_scope_cents"] = sum(d["cents"] for d in dropped)
    # estimate − projected billing = dropped scope + expense variance. The
    # footer that says so is the check the dropped-scope figure is complete.
    t["expense_variance_cents"] = t["estimate_cents"] - t["projected_billing_cents"] - t["dropped_scope_cents"]
    t["over_variance_band"] = over_band
    t["markups"] = markups
    t["markup_to_bill_cents"] = sum(m["markup_cents"] for m in markups)
    t["margin_bp"] = round_div(t["profit_loss_cents"] * 10_000, t["billed_cents"]) if t["billed_cents"] > 0 else None
    t["floor_lines"] = floor_lines(lines)
    t.update(cash(lines, invoices))
    return t


def floor_lines(lines: list[dict]) -> list[dict]:
    """Production fee, insurance, contingency: on every estimate, zeroed on
    purpose or flagged. The real estimate omitted all three — and its own terms
    then referred to a production fee "quoted above"."""
    out = []
    for kind in FLOOR_KINDS:
        line = next((ln for ln in lines if ln.get("floor_kind") == kind), None)
        est = line.get("est_cents") if line else None
        out.append({"kind": kind, "line_id": line.get("id") if line else None,
                    "quoted": est is not None, "est_cents": est})
    return out


def cash(lines: list[dict], invoices: list[dict]) -> dict:
    """Billing and cash — a different question from profit, so a different card.

    after_committed — cash in hand less everything still to land at estimate —
    was the most useful number on the real job: a $33,185 deposit came to
    about $568 once open crew and travel landed.

    cash_in_hand subtracts every booked cost, paid or not (the prototype's
    figure). cost_unpaid_cents in totals() is the part not yet marked paid.
    """
    whole = [ln for ln in lines if not ln.get("dropped")]
    cost = sum(calc(ln)["cost_cents"] or 0 for ln in whole)
    unrec = sum(calc(ln)["unreconciled_cents"] for ln in whole)
    open_pass = sum(ln.get("est_cents") or 0 for ln in whole
                    if ln.get("bucket") == "pass" and ln.get("act_cents") is None)
    open_pass += sum(max((ln.get("est_cents") or 0) - ln["act_cents"], 0) for ln in whole
                     if ln.get("bucket") == "pass" and ln.get("act_open") and ln.get("act_cents") is not None)
    projected_billing = sum(projected(ln)[0] for ln in whole)
    invoiced = sum(int(i.get("amount_cents") or 0) for i in invoices)
    received = advance_received(invoices)
    committed = unrec + open_pass
    return {"invoiced_cents": invoiced, "received_cents": received,
            "left_to_invoice_cents": projected_billing - invoiced,
            "cash_in_hand_cents": received - cost,
            "committed_cents": committed,
            "after_committed_cents": received - cost - committed}


def advance_received(invoices: list[dict]) -> int:
    """What the client has paid so far — the PC log's LESS ADVANCE RECEIVED."""
    return sum(int(i.get("amount_cents") or 0) for i in invoices if i.get("paid"))
