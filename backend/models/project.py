from pydantic import AfterValidator, BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Annotated, Optional

# A two-digit year typed into a native date input ("07/27/26") is stored verbatim
# as year 0026, and then prints on the call sheet that goes out to crew. Bound the
# range so a typo fails at the API instead of in someone's inbox.
MIN_SHOOT_YEAR = 2000
MAX_SHOOT_YEAR = 2100


def _validate_shoot_year(value: date) -> date:
    if not MIN_SHOOT_YEAR <= value.year <= MAX_SHOOT_YEAR:
        raise ValueError(
            f"Shoot date year {value.year:04d} looks wrong — use a four-digit year "
            f"between {MIN_SHOOT_YEAR} and {MAX_SHOOT_YEAR}."
        )
    return value


ShootDate = Annotated[date, AfterValidator(_validate_shoot_year)]


class ProjectCreate(BaseModel):
    name: str
    # The job this day belongs to. Omitted by the current version's New
    # project, which gets a new one-day job of its own instead.
    job_id: Optional[UUID] = None
    shoot_date: Optional[ShootDate] = None
    general_call_time: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    shoot_date: Optional[ShootDate] = None
    general_call_time: Optional[str] = None
    notes: Optional[str] = None
    # Header pills. Each is independently clearable — None hides that pill.
    first_call_time: Optional[str] = None
    first_shot_time: Optional[str] = None
    lunch_time: Optional[str] = None
    est_wrap_time: Optional[str] = None
    # Deal-memo-only fields — never printed on the call sheet or wrap report,
    # since call_sheet_data.py and wrap_report_data.py build their own project
    # dicts field-by-field and don't select these. See services/deal_memo_data.py.
    client_name: Optional[str] = None
    production_company: Optional[str] = None
    payroll_provider: Optional[str] = None


class ProjectResponse(BaseModel):
    id: UUID
    owner_id: UUID
    job_id: Optional[UUID] = None
    name: str
    shoot_date: Optional[date] = None
    general_call_time: Optional[str] = None
    notes: Optional[str] = None
    first_call_time: Optional[str] = None
    first_shot_time: Optional[str] = None
    lunch_time: Optional[str] = None
    est_wrap_time: Optional[str] = None
    client_name: Optional[str] = None
    production_company: Optional[str] = None
    payroll_provider: Optional[str] = None
    created_at: datetime


class LocationCreate(BaseModel):
    location_name: Optional[str] = None
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None


class LocationResponse(BaseModel):
    id: UUID
    project_id: UUID
    location_name: Optional[str] = None
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None


class MealPlanCreate(BaseModel):
    breakfast_start: Optional[str] = None
    breakfast_end: Optional[str] = None
    breakfast_notes: Optional[str] = None
    lunch_start: Optional[str] = None
    lunch_end: Optional[str] = None
    lunch_notes: Optional[str] = None


class MealPlanResponse(BaseModel):
    id: UUID
    project_id: UUID
    breakfast_start: Optional[str] = None
    breakfast_end: Optional[str] = None
    breakfast_notes: Optional[str] = None
    lunch_start: Optional[str] = None
    lunch_end: Optional[str] = None
    lunch_notes: Optional[str] = None


class AccommodationCreate(BaseModel):
    hotel_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website_url: Optional[str] = None
    room_block: Optional[str] = None
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    amenities: Optional[str] = None
    notes: Optional[str] = None


class AccommodationResponse(BaseModel):
    id: UUID
    project_id: UUID
    hotel_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website_url: Optional[str] = None
    room_block: Optional[str] = None
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    amenities: Optional[str] = None
    notes: Optional[str] = None
