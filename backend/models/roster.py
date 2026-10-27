from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from typing import List, Optional


class RosterEntryCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    organization: Optional[str] = None
    type: str = "crew"
    company: Optional[str] = None
    # A day rate is producer-only and must never reach a crew-facing surface —
    # see services/roster_sync.py's PERSON_FIELDS, which deliberately excludes
    # this and the agent_* fields below so an edit can never propagate them
    # onto a project row a call sheet or wrap report might read from.
    day_rate: Optional[str] = None
    rate_note: Optional[str] = None
    agency: Optional[str] = None
    agent_name: Optional[str] = None
    agent_email: Optional[str] = None
    agent_phone: Optional[str] = None


class RosterEntryUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    # Talent: home city (decides whether they travel) and portfolio link —
    # the talent hold sheet's Based and Link columns (talent_hires.sql).
    based: Optional[str] = Field(None, max_length=120)
    portfolio_url: Optional[str] = Field(None, max_length=500)

    @field_validator("portfolio_url")
    @classmethod
    def _web_link_only(cls, v):
        # It's rendered as a link on screen and in the talent hold sheet: only
        # an http(s) address, never javascript: or anything else a link can run.
        v = (v or "").strip()
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("A portfolio link must start with http:// or https://")
        return v or None
    role: Optional[str] = None
    department: Optional[str] = None
    organization: Optional[str] = None
    type: Optional[str] = None
    company: Optional[str] = None
    day_rate: Optional[str] = None
    rate_note: Optional[str] = None
    agency: Optional[str] = None
    agent_name: Optional[str] = None
    agent_email: Optional[str] = None
    agent_phone: Optional[str] = None


class RosterImportParseRequest(BaseModel):
    text: str = Field(max_length=50_000)
    type: str = "crew"


# Deliberately missing company/day_rate/agency fields — paste-import can't
# reliably pull a rate out of arbitrary pasted text, and keeping those fields
# manual-entry-only keeps this pipeline's surface small.
class RosterImportMember(BaseModel):
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    organization: Optional[str] = None


class RosterImportConfirmRequest(BaseModel):
    members: List[RosterImportMember]
    type: str = "crew"


class RosterEntryResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    based: Optional[str] = None
    portfolio_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    organization: Optional[str] = None
    type: str = "crew"
    company: Optional[str] = None
    day_rate: Optional[str] = None
    rate_note: Optional[str] = None
    agency: Optional[str] = None
    agent_name: Optional[str] = None
    agent_email: Optional[str] = None
    agent_phone: Optional[str] = None
    created_at: datetime
    # What propagating this edit actually did, so the UI can say so instead of
    # silently rewriting the producer's jobs. None when nothing was propagated.
    synced: Optional[dict] = None


class RosterMergeRequest(BaseModel):
    """Fold `drop_ids` into `keep_id`. Both must be on the caller's own roster;
    the API re-reads to confirm rather than trusting the ids it was handed."""
    keep_id: UUID
    drop_ids: List[UUID]
