from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List


class TalentCreate(BaseModel):
    roster_id: Optional[UUID] = None
    role: Optional[str] = None
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    call_time: Optional[str] = None
    location_assignment: Optional[str] = None


class TalentUpdate(BaseModel):
    role: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    call_time: Optional[str] = None
    sort_order: Optional[int] = None
    location_assignment: Optional[str] = None
    hide_contact: Optional[bool] = None


class TalentResponse(BaseModel):
    id: UUID
    project_id: UUID
    role: Optional[str] = None
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    call_time: Optional[str] = None
    # Set instead of call_time when the producer chose a named call
    # ("Own Call", "TBD"). Exactly one of the two is ever populated.
    call_time_note: Optional[str] = None
    sort_order: int
    location_assignment: Optional[str] = None
    # Talent contact details are handled by the agency, so these default to
    # hidden. Defaults to True here too, so a missing column fails closed.
    hide_contact: bool = True
    roster_id: Optional[UUID] = None
    roster_synced: Optional[bool] = None


class TalentImportParseRequest(BaseModel):
    text: str = Field(max_length=50_000)


class TalentImportMember(BaseModel):
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    call_time: Optional[str] = None
    # Set by /import/parse, sent back by /import/confirm. Same contract as crew —
    # see models/crew.py and services/import_match.py.
    match_state: Optional[str] = None
    match_id: Optional[UUID] = None
    match_name: Optional[str] = None
    differs: List[dict] = []
    action: Optional[str] = None



class TalentImportConfirmRequest(BaseModel):
    members: List[TalentImportMember]
    save_to_roster: bool = True
