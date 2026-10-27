from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List


class ContactCreate(BaseModel):
    roster_id: Optional[UUID] = None
    organization: Optional[str] = None
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    call_time: Optional[str] = None
    sort_order: int = 0


class ContactUpdate(BaseModel):
    organization: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    call_time: Optional[str] = None
    sort_order: Optional[int] = None
    wants_pdf: Optional[bool] = None


class ContactResponse(BaseModel):
    id: UUID
    project_id: UUID
    organization: Optional[str] = None
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    call_time: Optional[str] = None
    # Set instead of call_time when the producer chose a named call
    # ("Own Call", "TBD"). Exactly one of the two is ever populated.
    call_time_note: Optional[str] = None
    sort_order: int
    # Agency and client contacts file, print, and forward the sheet, so unlike
    # crew they default to receiving the PDF. Defaulted here too, so the API
    # still responds if the column hasn't been added to the database yet.
    wants_pdf: bool = True
    last_sent_at: Optional[datetime] = None
    roster_id: Optional[UUID] = None
    roster_synced: Optional[bool] = None

class ContactImportParseRequest(BaseModel):
    text: str = Field(max_length=50_000)


class ContactImportMember(BaseModel):
    name: str
    organization: Optional[str] = None
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



class ContactImportConfirmRequest(BaseModel):
    members: List[ContactImportMember]
    save_to_roster: bool = True