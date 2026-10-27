from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from models.project import ShootDate


class JobCreate(BaseModel):
    """New job — which also creates Day 1, to keep the guided flow (plan §13)."""
    name: str
    client_name: Optional[str] = None
    production_company: Optional[str] = None
    payroll_provider: Optional[str] = None
    # Day 1's own fields, same as ProjectCreate.
    shoot_date: Optional[ShootDate] = None
    general_call_time: Optional[str] = None


class JobUpdate(BaseModel):
    name: Optional[str] = None
    client_name: Optional[str] = None
    production_company: Optional[str] = None
    payroll_provider: Optional[str] = None
    # The deal memo's Location and Per Diem lines (supabase/jobs_deal_memo_fields.sql).
    location_line: Optional[str] = None
    per_diem_line: Optional[str] = None
    # Per diem a day (supabase/rates_v1.sql): shoot days, and every other day.
    per_diem_shoot: Optional[float] = Field(None, ge=0, le=100_000)
    per_diem_other: Optional[float] = Field(None, ge=0, le=100_000)
    per_diem_paid_by: Optional[str] = Field(None, max_length=200)
    # The number the car service gets instead of someone's own (supabase/travel_legs.sql).
    producer_phone: Optional[str] = Field(None, max_length=40)


class DayLabelsUpdate(BaseModel):
    # {ISO date: text}; checked by services/job_dates.validate_day_text.
    day_labels: dict


class JobDefaults(BaseModel):
    """What every new job starts with — the /account Job defaults card."""
    per_diem_shoot: Optional[float] = Field(None, ge=0, le=100_000)
    per_diem_other: Optional[float] = Field(None, ge=0, le=100_000)
    per_diem_paid_by: Optional[str] = Field(None, max_length=200)


class CrewDatesUpdate(BaseModel):
    # Shape checked by services/job_dates.validate_dates — a 422 with a
    # readable message rather than a Pydantic error list.
    crew_dates: dict


class JobResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    client_name: Optional[str] = None
    production_company: Optional[str] = None
    payroll_provider: Optional[str] = None
    location_line: Optional[str] = None
    per_diem_line: Optional[str] = None
    per_diem_shoot: Optional[float] = None
    per_diem_other: Optional[float] = None
    per_diem_paid_by: Optional[str] = None
    day_labels: dict = {}
    crew_dates: dict = {}
    created_at: Optional[datetime] = None


class HireCreate(BaseModel):
    roster_id: Optional[UUID] = None
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    dates_override: dict = {}
    # Save someone typed in directly to the Master Roster as well — what adding
    # a person to a day has always done.
    save_to_roster: bool = True
    # Hire them as a hold (services/holds.py) — and/or into one of the job's
    # role slots, which then shows them as that role filled.
    status: Optional[Literal["hold", "confirmed"]] = None
    hold_rank: Optional[int] = None
    slot_id: Optional[str] = None
    # Talent are hires too (supabase/talent_hires.sql), grouped by segment.
    kind: Literal["crew", "talent"] = "crew"
    segment: Optional[str] = Field(None, max_length=80)
    # Talent only: the shoot days they're booked for. Their travel in/out and
    # any down days between are worked out from these (job_dates.talent_dates).
    shoot_days: list[str] = Field(default_factory=list, max_length=60)


class HireUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    # {} is "Reset to crew dates".
    dates_override: Optional[dict] = None
    # Printed under their generated date lines on the memo ("down day – ½ day
    # rate"). Job-only: not a person field, so it never syncs anywhere.
    dates_note: Optional[str] = None
    # {ISO date: text}: their own note on one date's line (validate_day_text).
    day_notes: Optional[dict] = None
    sort_order: Optional[int] = None
    # The agreed deal (services/job_rates.py). Producer-only; null clears one.
    rate_shoot: Optional[float] = Field(None, ge=0, le=1_000_000)
    rate_travel: Optional[float] = Field(None, ge=0, le=1_000_000)
    rate_prep: Optional[float] = Field(None, ge=0, le=1_000_000)
    rate_note: Optional[str] = Field(None, max_length=1000)
    # Set when the producer saves a suggestion as it was offered, so the Rate
    # column can say where it came from. The router checks the job is theirs.
    rate_source: Optional[Literal["job", "roster"]] = None
    rate_source_job_id: Optional[UUID] = None
    # hold (1st/2nd) → confirmed, or released (services/holds.py).
    status: Optional[Literal["hold", "confirmed", "released"]] = None
    hold_rank: Optional[int] = None
    # Talent: their hold sheet's section ("Brand Women"), the agency's fee on
    # top of the rate (her "+20%"), and the sheet's Notes column.
    segment: Optional[str] = Field(None, max_length=80)
    agency_fee_pct: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = Field(None, max_length=500)


class HireShift(BaseModel):
    """"Move with the crew": shift this person's own dates by N days."""
    days: int


# What "Set up a day" can bring across from another day. Crew means the
# people working that date (from their deal memo dates), with the source
# day's call times where they had one.
DAY_PARTS = ("crew", "location", "talent", "contacts", "meals", "hotel", "schedule", "notes")


class AddDay(BaseModel):
    name: Optional[str] = None
    shoot_date: Optional[ShootDate] = None
    # Set up a day (the Shoot days placeholders): copy_from a day in this job,
    # or blank=True for a new location. Either one switches on `include`;
    # with neither, this is the original "Add a day" — duplicate the latest.
    copy_from: Optional[UUID] = None
    blank: bool = False
    include: Optional[list[Literal[DAY_PARTS]]] = None


class MoveDay(BaseModel):
    to_job_id: UUID


class BetaToggle(BaseModel):
    enabled: bool

