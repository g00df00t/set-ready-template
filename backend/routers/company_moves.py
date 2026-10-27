from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from typing import List
from database import get_client
from auth import get_accessible_owner_ids
from models.company_move import CompanyMoveCreate, CompanyMoveUpdate, CompanyMoveResponse
from time_utils import to_pg_time

router = APIRouter(tags=["company-moves"])


def _own_project(client, project_id: str, owner_ids: set[str]):
    result = client.table("projects").select("id").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/projects/{project_id}/company-moves", response_model=List[CompanyMoveResponse])
def list_moves(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("company_moves").select("*").eq("project_id", str(project_id)).order("sort_order").execute()
    return result.data


@router.post("/projects/{project_id}/company-moves", response_model=CompanyMoveResponse)
def add_move(project_id: UUID, data: CompanyMoveCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("company_moves").insert({
        "project_id": str(project_id),
        "label": data.label,
        "location_name": data.location_name,
        "address": data.address,
        "parking_notes": data.parking_notes,
        "parking_address": data.parking_address,
        "additional_notes": data.additional_notes,
        "move_time": to_pg_time(data.move_time) if data.move_time else None,
        "sort_order": data.sort_order,
    }).execute()
    return result.data[0]


@router.put("/projects/{project_id}/company-moves/{move_id}", response_model=CompanyMoveResponse)
def update_move(project_id: UUID, move_id: UUID, data: CompanyMoveUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    updates = data.model_dump(exclude_unset=True)
    if "move_time" in updates:
        updates["move_time"] = to_pg_time(updates["move_time"]) if updates["move_time"] else None
    result = client.table("company_moves").update(updates).eq("id", str(move_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Company move not found")
    return result.data[0]


@router.delete("/projects/{project_id}/company-moves/{move_id}")
def delete_move(project_id: UUID, move_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("company_moves").delete().eq("id", str(move_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Company move not found")
    return {"ok": True}
