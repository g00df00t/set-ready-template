"""A job's budget lines, expenses and invoices — the rows reconciliation and
the PC log are built from (services/budget.py and services/pc_log.py decide,
this fetches and stores). supabase/reconciliation.sql.

Every route gates on the job through jobs._own_job, so team sharing covers it.

The Estimate view (docs/estimate-reconcile-plan.md): qty × rate is the amount
whenever both are set (services/budget.estimate_amount), and once the estimate
is marked signed its quoted figures are locked — a 409, never a silent drop.
Sections and signing need supabase/estimate.sql; without it a line still adds
and edits, and asking for either is a 503 naming that file.

Until the migration runs, GET answers with empty lists and `migrated: false`,
and a save is a 503 that says what's missing — only a MISSING TABLE is read
that way; any other database error still raises, so an outage never looks like
an empty budget.
"""

import logging
from uuid import UUID

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response

from auth import get_accessible_owner_ids, get_user_identity
from database import get_client
from models.budget import (BudgetLineCreate, BudgetLinesBatch, BudgetLineUpdate, EstimateSign, ExpenseCreate,
                           ExpenseUpdate, InvoiceCreate, InvoiceUpdate, SectionRename, StatementSettings)
from routers.jobs import _own_job
from services import budget as svc, pc_log, reconciliation_statement as statement_svc
from services.pdf_service import render_call_sheet_pdf
from services.receipt_import import clean_name, valid_path
from services.receipt_store import remove_if_unused

logger = logging.getLogger(__name__)
router = APIRouter(tags=["budget"])

TABLES = ("job_budget_lines", "job_expenses", "job_invoices")
LIMIT = 500                    # rows of each kind on one job
NOT_MIGRATED = "Budgets aren't set up on this server yet (supabase/reconciliation.sql)."
ESTIMATE_NOT_MIGRATED = "Estimate sections and signing aren't set up on this server yet (supabase/estimate.sql)."
COST_FINAL_NOT_MIGRATED = "\"All costs in\" can't be saved on this server yet (supabase/cost_final.sql)."
STATEMENT_NOT_MIGRATED = "The statement's own details can't be saved on this server yet (supabase/statement.sql)."
SIGNED = "The estimate is signed, so its quantities, rates and amounts are locked. Unlock it to change them."


def _is_missing_table(e: Exception) -> bool:
    """A table (PGRST205) or a column (PGRST204) the migration adds isn't there."""
    text = str(e)
    return ("does not exist" in text and "relation" in text) or "PGRST205" in text \
        or "PGRST204" in text or "Could not find the" in text


def _rows(client, table: str, job_id: str) -> list[dict] | None:
    """The job's rows, in order — or None when the table doesn't exist yet."""
    try:
        rows = client.table(table).select("*").eq("job_id", job_id).execute().data
    except Exception as e:
        if _is_missing_table(e):
            return None
        raise
    return sorted(rows, key=lambda r: (r.get("sort_order") or 0, str(r.get("created_at") or ""), str(r["id"])))


def _write(fn):
    """Run one write; a missing table becomes a 503 that names the migration."""
    try:
        return fn()
    except Exception as e:
        if _is_missing_table(e):
            raise HTTPException(status_code=503, detail=NOT_MIGRATED)
        raise


def _tidy(changes: dict) -> dict:
    """Text trimmed (blank → None), dates as ISO strings."""
    out = {}
    for k, v in changes.items():
        if isinstance(v, str):
            v = " ".join(v.split()) if k not in ("note",) else v.strip()
            v = v or None
        elif hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out


def _line_shape(line: dict) -> dict:
    """A bill override only means something on a rate line, and a markup only
    on a pass-through; switching a line's bucket drops the one that no longer
    applies rather than leaving it to surprise someone later."""
    out = dict(line)
    if out.get("bucket") != "rate":
        out["bill_cents"] = None
    if out.get("bucket") != "pass":
        out["markup_bp"] = 0
    return out


def _estimate_ready(job: dict) -> bool:
    """estimate.sql has run: the job row carries the column it adds."""
    return "estimate_signed_on" in job


def _signed(job: dict) -> bool:
    return bool(job.get("estimate_signed_on"))


def _quote(row: dict) -> dict:
    """qty × rate is the amount whenever both are set."""
    amount = svc.estimate_amount(row.get("qty"), row.get("unit_amount_cents"))
    return {**row, "est_cents": amount} if amount is not None else row


def _same(key: str, a, b) -> bool:
    if key == "qty":
        return svc.hundredths(a) == svc.hundredths(b)
    return a == b


def view(client, job: dict, block: str = "*") -> dict:
    lines, expenses, invoices = (_rows(client, t, job["id"]) for t in TABLES)
    migrated = lines is not None and expenses is not None and invoices is not None
    lines, expenses, invoices = lines or [], expenses or [], invoices or []
    lines = svc.with_expenses(lines, expenses)
    fee_bp = job.get("production_fee_bp")
    fee_bp = pc_log.DEFAULT_FEE_BP if fee_bp is None else int(fee_bp)
    return {
        "migrated": migrated,
        "lines": [{**ln, "calc": svc.calc(ln)} for ln in lines],
        "expenses": expenses,
        "invoices": invoices,
        "budget": svc.totals(lines, invoices, block=block),
        "blocks": sorted({ln["block"] for ln in lines if ln.get("block")}),
        # PC log receipts not pointed at any estimate line: in no line's cost
        # until they are, so Reconcile says how many and how much.
        "unassigned_receipts": {"count": sum(1 for e in expenses if not e.get("budget_line_id")),
                                "cents": sum(int(e.get("amount_cents") or 0) for e in expenses
                                             if not e.get("budget_line_id"))},
        "estimate": {"ready": _estimate_ready(job), "signed_on": job.get("estimate_signed_on"),
                     "sections": svc.sections(lines)},
        # The client statement's own details; `ready` = supabase/statement.sql has run.
        "statement": {"ready": "statement" in job, **statement_svc.settings(job)},
        "pc_log": pc_log.totals(expenses, fee_bp, invoices),
        "categories": pc_log.CATEGORIES,
    }


@router.get("/jobs/{job_id}/budget")
def get_budget(job_id: UUID, block: str | None = None, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """`block` filters the budget totals: a market's name, "project" for the
    job-wide lines, nothing for everything."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    return view(client, job, "*" if block is None else (None if block == "project" else block))


def _own_row(client, table: str, job_id: str, row_id: str, what: str) -> dict:
    rows = _write(lambda: client.table(table).select("*").eq("id", row_id).eq("job_id", job_id).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail=f"That {what} isn't on this job.")
    return rows[0]


def _room(client, table: str, job_id: str, what: str):
    rows = _write(lambda: client.table(table).select("id").eq("job_id", job_id).execute().data)
    if len(rows) >= LIMIT:
        raise HTTPException(status_code=422, detail=f"A job can hold {LIMIT} {what}.")


# ── Budget lines ─────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/budget/lines")
def add_line(job_id: UUID, data: BudgetLineCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    _room(client, "job_budget_lines", job["id"], "budget lines")
    row = _line_shape({**_tidy(data.model_dump()), "job_id": job["id"]})
    if _signed(job) and any(row.get(k) is not None for k in svc.QUOTED_FIELDS):
        raise HTTPException(status_code=409, detail=SIGNED)
    row = _quote(row)
    if not row.get("section"):
        row.pop("section", None)      # so a database without estimate.sql still takes the line
    elif not _estimate_ready(job):
        raise HTTPException(status_code=503, detail=ESTIMATE_NOT_MIGRATED)
    if not row.get("sort_order"):
        # After everything already there, so a hand-built estimate keeps the
        # order it was typed in.
        orders = [r.get("sort_order") or 0 for r in _rows(client, "job_budget_lines", job["id"]) or []]
        row["sort_order"] = max(orders, default=0) + 1
    _write(lambda: client.table("job_budget_lines").insert(row).execute())
    return view(client, job)


@router.post("/jobs/{job_id}/budget/lines/batch")
def add_lines(job_id: UUID, data: BudgetLinesBatch, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """An imported estimate's kept lines, in one insert after whatever's there —
    all of them or none. Same rules as one line: refused on a signed estimate,
    qty × rate is the amount. Without estimate.sql the headings are left off
    rather than the whole import refused."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    if _signed(job):
        raise HTTPException(status_code=409, detail=SIGNED)
    existing = _rows(client, "job_budget_lines", job["id"])
    if existing is None:
        raise HTTPException(status_code=503, detail=NOT_MIGRATED)
    if len(existing) + len(data.lines) > LIMIT:
        raise HTTPException(status_code=422, detail=f"A job can hold {LIMIT} budget lines; that would be {len(existing) + len(data.lines)}.")
    start = max((r.get("sort_order") or 0 for r in existing), default=0)
    rows = []
    for i, line in enumerate(data.lines, start=1):
        row = _quote(_line_shape({**_tidy(line.model_dump()), "job_id": job["id"], "sort_order": start + i}))
        if not row.get("section") or not _estimate_ready(job):
            row.pop("section", None)
        rows.append(row)
    _write(lambda: client.table("job_budget_lines").insert(rows).execute())
    return view(client, job)


@router.put("/jobs/{job_id}/budget/lines/{line_id}")
def update_line(job_id: UUID, line_id: str, data: BudgetLineUpdate,
                owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    current = _own_row(client, "job_budget_lines", job["id"], line_id, "budget line")
    asked = _tidy(data.model_dump(exclude_unset=True))
    if _signed(job) and any(k in asked and not _same(k, asked[k], current.get(k)) for k in svc.QUOTED_FIELDS):
        raise HTTPException(status_code=409, detail=SIGNED)
    if "section" in asked and not _estimate_ready(job):
        raise HTTPException(status_code=503, detail=ESTIMATE_NOT_MIGRATED)
    if "cost_final" in asked and "cost_final" not in current:
        raise HTTPException(status_code=503, detail=COST_FINAL_NOT_MIGRATED)
    merged = _line_shape({**current, **asked})
    if "qty" in asked or "unit_amount_cents" in asked:
        merged = _quote(merged)       # only then: an amount typed over a qty × rate stays as typed
    changes = {k: merged[k] for k in merged
               if k not in ("id", "job_id", "created_at") and not _same(k, merged[k], current.get(k))}
    if changes:
        _write(lambda: client.table("job_budget_lines").update(changes).eq("id", line_id).execute())
    return view(client, job)


@router.delete("/jobs/{job_id}/budget/lines/{line_id}")
def delete_line(job_id: UUID, line_id: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The line's expenses stay — they come off the line, not off the log
    (the foreign key is SET NULL; done here too, so the answer is right
    whatever the database does)."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    line = _own_row(client, "job_budget_lines", job["id"], line_id, "budget line")
    if _signed(job) and line.get("est_cents") is not None:
        raise HTTPException(status_code=409, detail="That line is on the signed estimate. Unlock the estimate to remove it.")
    _write(lambda: client.table("job_expenses").update({"budget_line_id": None})
           .eq("budget_line_id", line_id).eq("job_id", job["id"]).execute())
    _write(lambda: client.table("job_budget_lines").delete().eq("id", line_id).execute())
    return view(client, job)


@router.put("/jobs/{job_id}/budget/sections")
def rename_section(job_id: UUID, data: SectionRename, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Renames a heading by moving every line under it. Allowed on a signed
    estimate: a heading is a label, not a quoted figure."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    if not _estimate_ready(job):
        raise HTTPException(status_code=503, detail=ESTIMATE_NOT_MIGRATED)
    names = _tidy({"name": data.name, "to": data.to})
    ids = [ln["id"] for ln in _rows(client, "job_budget_lines", job["id"]) or []
           if ((ln.get("section") or "").strip() or None) == names["name"]]
    if not ids:
        raise HTTPException(status_code=404, detail="There are no lines under that heading.")
    if names["to"] != names["name"]:
        _write(lambda: client.table("job_budget_lines").update({"section": names["to"]}).in_("id", ids).execute())
    return view(client, job)


@router.put("/jobs/{job_id}/estimate")
def sign_estimate(job_id: UUID, data: EstimateSign, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """A date marks the estimate signed and locks its quoted figures; None
    unlocks it. Nothing else changes either way."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    if not _estimate_ready(job):
        raise HTTPException(status_code=503, detail=ESTIMATE_NOT_MIGRATED)
    signed_on = data.signed_on.isoformat() if data.signed_on else None
    if signed_on and not any(ln.get("est_cents") is not None for ln in _rows(client, "job_budget_lines", job["id"]) or []):
        raise HTTPException(status_code=422, detail="There's nothing quoted on the estimate to sign yet.")
    _write(lambda: client.table("jobs").update({"estimate_signed_on": signed_on}).eq("id", job["id"]).execute())
    return view(client, {**job, "estimate_signed_on": signed_on})


# ── The client reconciliation statement ─────────────────────────────────────

@router.put("/jobs/{job_id}/budget/statement")
def save_statement(job_id: UUID, data: StatementSettings, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    if "statement" not in job:
        raise HTTPException(status_code=503, detail=STATEMENT_NOT_MIGRATED)
    merged = {**(job.get("statement") or {}), **_tidy_text(data.model_dump(exclude_unset=True))}
    _write(lambda: client.table("jobs").update({"statement": merged}).eq("id", job["id"]).execute())
    return view(client, {**job, "statement": merged})


def _tidy_text(fields: dict) -> dict:
    """Trimmed, line breaks kept (a contact block is several lines), blank → None."""
    out = {}
    for k, v in fields.items():
        lines = [" ".join(ln.split()) for ln in (v or "").splitlines()]
        out[k] = "\n".join(ln for ln in lines if ln) or None
    return out


@router.get("/jobs/{job_id}/budget/statement.pdf")
def statement_pdf(job_id: UUID, statement_on: date | None = None,
                  owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The statement as it stands now — not stored: like the wrap report, a
    saved copy would go stale as costs keep landing."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    lines, expenses, invoices = (_rows(client, t, job["id"]) for t in TABLES)
    lines = svc.with_expenses(lines or [], expenses or [])
    if not any(ln.get("est_cents") is not None for ln in lines):
        raise HTTPException(status_code=422, detail="There's no estimate on this job to reconcile against yet.")
    days = client.table("projects").select("shoot_date").eq("job_id", job["id"]).execute().data
    dates = pc_log.header(job, [d.get("shoot_date") for d in days], None)["project_dates"]
    s = statement_svc.build(job, lines, invoices or [], get_user_identity(job["owner_id"]), dates,
                            (statement_on or date.today()).isoformat())
    try:
        pdf = render_call_sheet_pdf(statement_svc.to_html(s))
    except Exception as e:
        logger.exception("Reconciliation statement PDF failed for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}")
    name = quote(statement_svc.filename(s) + ".pdf")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})


# ── Expenses ─────────────────────────────────────────────────────────────────

def _check_line(client, job_id: str, line_id: str | None):
    if line_id:
        _own_row(client, "job_budget_lines", job_id, line_id, "budget line")


@router.post("/jobs/{job_id}/expenses")
def add_expense(job_id: UUID, data: ExpenseCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    _room(client, "job_expenses", job["id"], "expenses")
    _check_line(client, job["id"], data.budget_line_id)
    row = {**_tidy(data.model_dump()), "job_id": job["id"]}
    if row.get("receipt_path"):
        if not valid_path(job["id"], row["receipt_path"]) or not row.get("receipt_type"):
            raise HTTPException(status_code=422, detail="That receipt isn't one of this job's.")
        row["receipt_name"] = clean_name(row.get("receipt_name"))
    else:
        # No receipt: leave the columns out, so a database without receipts.sql
        # still takes a typed line.
        for k in ("receipt_path", "receipt_name", "receipt_type"):
            row.pop(k, None)
    _write(lambda: client.table("job_expenses").insert(row).execute())
    return view(client, job)


@router.put("/jobs/{job_id}/expenses/{expense_id}")
def update_expense(job_id: UUID, expense_id: str, data: ExpenseUpdate,
                   owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    _own_row(client, "job_expenses", job["id"], expense_id, "expense")
    changes = _tidy(data.model_dump(exclude_unset=True))
    _check_line(client, job["id"], changes.get("budget_line_id"))
    if changes:
        _write(lambda: client.table("job_expenses").update(changes).eq("id", expense_id).execute())
    return view(client, job)


@router.delete("/jobs/{job_id}/expenses/{expense_id}")
def delete_expense(job_id: UUID, expense_id: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    row = _own_row(client, "job_expenses", job["id"], expense_id, "expense")
    _write(lambda: client.table("job_expenses").delete().eq("id", expense_id).execute())
    remove_if_unused(client, job["id"], row.get("receipt_path"))      # its file, once no line uses it
    return view(client, job)


# ── Invoices ─────────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/invoices")
def add_invoice(job_id: UUID, data: InvoiceCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    _room(client, "job_invoices", job["id"], "invoices")
    row = {**_tidy(data.model_dump()), "job_id": job["id"]}
    _write(lambda: client.table("job_invoices").insert(row).execute())
    return view(client, job)


@router.put("/jobs/{job_id}/invoices/{invoice_id}")
def update_invoice(job_id: UUID, invoice_id: str, data: InvoiceUpdate,
                   owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    _own_row(client, "job_invoices", job["id"], invoice_id, "invoice")
    changes = _tidy(data.model_dump(exclude_unset=True))
    if changes:
        _write(lambda: client.table("job_invoices").update(changes).eq("id", invoice_id).execute())
    return view(client, job)


@router.delete("/jobs/{job_id}/invoices/{invoice_id}")
def delete_invoice(job_id: UUID, invoice_id: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    _own_row(client, "job_invoices", job["id"], invoice_id, "invoice")
    _write(lambda: client.table("job_invoices").delete().eq("id", invoice_id).execute())
    return view(client, job)
