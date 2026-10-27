from pydantic import BaseModel
from uuid import UUID
from typing import Optional


class CompanyMoveCreate(BaseModel):
    label: Optional[str] = None
    location_name: Optional[str] = None
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None
    move_time: Optional[str] = None
    sort_order: int = 0


class CompanyMoveUpdate(BaseModel):
    label: Optional[str] = None
    location_name: Optional[str] = None
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None
    move_time: Optional[str] = None
    sort_order: Optional[int] = None


class CompanyMoveResponse(BaseModel):
    id: UUID
    project_id: UUID
    label: Optional[str] = None
    location_name: Optional[str] = None
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None
    move_time: Optional[str] = None
    sort_order: int
