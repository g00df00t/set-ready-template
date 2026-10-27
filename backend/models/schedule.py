from pydantic import BaseModel
from uuid import UUID
from typing import Optional


class ScheduleItemCreate(BaseModel):
    start_time: str
    end_time: Optional[str] = None
    description: str
    sort_order: int = 0


class ScheduleItemUpdate(BaseModel):
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class ScheduleItemResponse(BaseModel):
    id: UUID
    project_id: UUID
    start_time: str
    end_time: Optional[str] = None
    description: str
    sort_order: int
