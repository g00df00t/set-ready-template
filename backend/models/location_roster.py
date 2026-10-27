from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class LocationRosterCreate(BaseModel):
    name: str
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None


class LocationRosterUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None


class LocationRosterResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    address: Optional[str] = None
    parking_notes: Optional[str] = None
    parking_address: Optional[str] = None
    additional_notes: Optional[str] = None
    created_at: datetime
