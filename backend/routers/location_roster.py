from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from typing import List
from database import get_client
from auth import get_accessible_owner_ids, get_write_owner_id
from models.location_roster import LocationRosterCreate, LocationRosterUpdate, LocationRosterResponse
from routers.roster import edits_from

router = APIRouter(tags=["location-roster"])


@router.get("/location-roster", response_model=List[LocationRosterResponse])
def list_locations(owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    result = client.table("location_roster").select("*").in_("owner_id", list(owner_ids)).order("name").execute()
    return result.data


@router.post("/location-roster", response_model=LocationRosterResponse)
def add_location(data: LocationRosterCreate, write_owner_id: str = Depends(get_write_owner_id)):
    client = get_client()
    result = client.table("location_roster").insert({
        "owner_id": write_owner_id,
        "name": data.name,
        "address": data.address,
        "parking_notes": data.parking_notes,
        "parking_address": data.parking_address,
        "additional_notes": data.additional_notes,
    }).execute()
    return result.data[0]


@router.put("/location-roster/{entry_id}", response_model=LocationRosterResponse)
def update_location(entry_id: UUID, data: LocationRosterUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    # Same rule as the Roster: a cleared field saves as empty (roster.edits_from).
    updates = edits_from(data, required=("name",))
    if not updates:
        result = client.table("location_roster").select("*").eq("id", str(entry_id)).in_("owner_id", list(owner_ids)).execute()
    else:
        result = client.table("location_roster").update(updates).eq("id", str(entry_id)).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Location not found")
    return result.data[0]


@router.delete("/location-roster/{entry_id}")
def delete_location(entry_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    result = client.table("location_roster").delete().eq("id", str(entry_id)).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Location not found")
    return {"ok": True}
