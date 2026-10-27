"""A job's budget lines, expenses and invoices (supabase/reconciliation.sql).

Money is integer cents in and out of the API — the browser converts — so no
float ever reaches a total. Percentages are basis points (1500 = 15%).
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

Cents = Optional[int]
MAX_CENTS = 1_000_000_000          # $10,000,000 — the same ceiling as a vendor's fee
Bucket = Literal["fee", "rate", "pass"]
FloorKind = Literal["production_fee", "insurance", "contingency"]
Category = Literal["photography", "video", "talent", "stylist_hmu", "art_props",
                   "location_studio", "production_misc", "producer", "payroll_fee"]


class BudgetLineCreate(BaseModel):
    bucket: Bucket = "rate"
    block: Optional[str] = Field(None, max_length=80)
    section: Optional[str] = Field(None, max_length=120)      # supabase/estimate.sql
    name: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(None, max_length=4000)
    flag: Optional[str] = Field(None, max_length=120)
    qty: Optional[float] = Field(None, ge=0, le=100_000)
    unit_amount_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    est_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    act_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    bill_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    markup_bp: int = Field(0, ge=0, le=100_000)
    dropped: bool = False
    awaiting_cost: bool = False
    act_paid: bool = False
    floor_kind: Optional[FloorKind] = None
    sort_order: int = 0


class BudgetLineUpdate(BaseModel):
    bucket: Optional[Bucket] = None
    block: Optional[str] = Field(None, max_length=80)
    section: Optional[str] = Field(None, max_length=120)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    note: Optional[str] = Field(None, max_length=4000)
    flag: Optional[str] = Field(None, max_length=120)
    qty: Optional[float] = Field(None, ge=0, le=100_000)
    unit_amount_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    est_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    act_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    bill_cents: Cents = Field(None, ge=0, le=MAX_CENTS)
    markup_bp: Optional[int] = Field(None, ge=0, le=100_000)
    dropped: Optional[bool] = None
    awaiting_cost: Optional[bool] = None
    act_paid: Optional[bool] = None
    cost_final: Optional[bool] = None       # "All costs in" (supabase/cost_final.sql)
    floor_kind: Optional[FloorKind] = None
    sort_order: Optional[int] = None


class BudgetLinesBatch(BaseModel):
    """An imported estimate's lines, the ones the producer kept — added together."""
    lines: list[BudgetLineCreate] = Field(min_length=1, max_length=200)


class StatementSettings(BaseModel):
    """What only the client reconciliation statement says (jobs.statement)."""
    client_contact: Optional[str] = Field(None, max_length=600)    # name, company — one per line
    estimate_ref: Optional[str] = Field(None, max_length=80)       # "EST-0001"
    intro: Optional[str] = Field(None, max_length=2000)            # what happened, in her words


class EstimateSign(BaseModel):
    """A date marks the estimate signed (its quoted figures lock); None unlocks it."""
    signed_on: Optional[date] = None


class SectionRename(BaseModel):
    """Every line under `name` (None = no section) moves to `to`."""
    name: Optional[str] = Field(None, max_length=120)
    to: Optional[str] = Field(None, max_length=120)


class ExpenseCreate(BaseModel):
    budget_line_id: Optional[str] = None
    spent_on: Optional[date] = None
    payee: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    amount_cents: int = Field(ge=0, le=MAX_CENTS)
    category: Category = "production_misc"
    sort_order: int = 0
    # The receipt it was read from (routers/receipts.py), kept in the private
    # bucket. Only a path in this job's own folder is accepted.
    receipt_path: Optional[str] = Field(None, max_length=200)
    receipt_name: Optional[str] = Field(None, max_length=200)
    receipt_type: Optional[Literal["application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"]] = None


class ExpenseUpdate(BaseModel):
    budget_line_id: Optional[str] = None
    spent_on: Optional[date] = None
    payee: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    amount_cents: Optional[int] = Field(None, ge=0, le=MAX_CENTS)
    category: Optional[Category] = None
    sort_order: Optional[int] = None


class InvoiceCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(ge=0, le=MAX_CENTS)
    issued_on: Optional[date] = None
    paid: bool = False
    paid_on: Optional[date] = None
    sort_order: int = 0


class InvoiceUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=200)
    amount_cents: Optional[int] = Field(None, ge=0, le=MAX_CENTS)
    issued_on: Optional[date] = None
    paid: Optional[bool] = None
    paid_on: Optional[date] = None
    sort_order: Optional[int] = None
