from pydantic import BaseModel, BeforeValidator, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import Annotated, Optional, List

# A hire (models/job.py's HireCreate) and a Roster entry can both exist with no
# email — contact details aren't always known yet when someone's first added.
# "Add from this job's hires" and "Add from roster" both carry that value
# straight through, and the roster picker has always sent "" rather than None
# for "nothing to send". EmailStr alone rejects "" as an invalid address, so
# without this, adding either kind of person without an email 422's — silently,
# from the picker's point of view, since neither add path surfaces the error.
OptionalEmail = Annotated[Optional[EmailStr], BeforeValidator(lambda v: v or None)]


class CrewMemberCreate(BaseModel):
    # Set when this person came from the producer's Roster, so corrections can
    # travel back to their master record. Absent for someone typed in directly.
    roster_id: Optional[UUID] = None
    # Set when picked from this job's hires ("Add from this job's hires").
    # Absent otherwise — the backend finds or makes the hire itself.
    hire_id: Optional[UUID] = None
    name: str
    email: OptionalEmail = None
    role: str
    phone: Optional[str] = None
    call_time: Optional[str] = None
    department: Optional[str] = None


class CrewMemberUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    call_time: Optional[str] = None
    department: Optional[str] = None
    sort_order: Optional[int] = None
    hide_contact: Optional[bool] = None
    wants_pdf: Optional[bool] = None
    # Free text, deal-memo only ("Aug 24th - Mon - travels in..."). The producer's real
    # deal memos write this per person, not as one block for the whole crew, so
    # it lives here rather than on the project. Never read by the call sheet,
    # confirm page, or wrap report — those build their own dicts and don't
    # select it.
    deal_memo_dates: Optional[str] = None


class CrewMemberResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    email: str
    role: str
    phone: Optional[str] = None
    call_time: Optional[str] = None
    # Set instead of call_time when the producer chose a named call
    # ("Own Call", "TBD"). Exactly one of the two is ever populated.
    call_time_note: Optional[str] = None
    department: Optional[str] = None
    sort_order: int = 0
    confirmed_at: Optional[datetime] = None
    roster_id: Optional[UUID] = None
    # True when this edit was also written back to the Roster.
    roster_synced: Optional[bool] = None
    # Keep their phone/email off the printed sheet. Defaulted here so the API
    # still responds if the column hasn't been added to the database yet.
    hide_contact: bool = False
    # Attach a PDF copy to their email. Off by default — crew read the sheet
    # inline on a phone; the attachment is for people who file or print it.
    wants_pdf: bool = False
    # When this person was last emailed the sheet. Only meaningful against the
    # current sheet's generated_at — see the schema note.
    last_sent_at: Optional[datetime] = None
    deal_memo_dates: Optional[str] = None
    hire_id: Optional[UUID] = None


class CrewImportParseRequest(BaseModel):
    text: str = Field(max_length=50_000)


class CrewImportMember(BaseModel):
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    call_time: Optional[str] = None

    # ── Set by /import/parse, sent back by /import/confirm ────────────────────
    #
    # "new"        nothing matches — add them
    # "on_project" already on this shoot; adding again IS the duplicate
    # "in_roster"  known to the producer but not on this shoot yet
    # "ambiguous"  more than one person matches; the app must not choose
    match_state: Optional[str] = None
    #: The crew_members.id ("on_project") or roster.id ("in_roster") matched.
    match_id: Optional[UUID] = None
    #: The name that record is filed under, when it differs from the pasted one.
    #: Shown so a producer can see WHY two records were called the same person.
    match_name: Optional[str] = None
    #: Fields where the pasted value disagrees with the matched record —
    #: [{"field", "pasted", "existing"}]. The interesting case: not a duplicate
    #: to drop, but a producer holding a newer call sheet than the app.
    differs: List[dict] = []

    #: What to do, chosen by the producer in the preview. The API trusts this
    #: rather than re-deciding, so an override always wins.
    #: "add" | "skip" | "update"
    action: Optional[str] = None


class CrewImportConfirmRequest(BaseModel):
    members: List[CrewImportMember]
    #: Also save anyone new to the producer's Roster, which is what adding one
    #: person at a time has always done. On by default so import matches
    #: single-add; the producer can turn it off for a crowd of one-off extras.
    save_to_roster: bool = True
