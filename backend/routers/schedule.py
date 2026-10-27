from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from typing import List
from database import get_client
from auth import get_accessible_owner_ids
from models.schedule import ScheduleItemCreate, ScheduleItemUpdate, ScheduleItemResponse
from time_utils import to_pg_time

router = APIRouter(tags=["schedule"])


def _own_project(client, project_id: str, owner_ids: set[str]):
    result = client.table("projects").select("id").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/projects/{project_id}/schedule", response_model=ScheduleItemResponse)
def add_schedule_item(project_id: UUID, data: ScheduleItemCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("schedule_items").insert({
        "project_id": str(project_id),
        "start_time": to_pg_time(data.start_time),
        "end_time": to_pg_time(data.end_time) if data.end_time else None,
        "description": data.description,
        "sort_order": data.sort_order,
    }).execute()
    return result.data[0]


@router.get("/projects/{project_id}/schedule", response_model=List[ScheduleItemResponse])
def list_schedule(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("schedule_items").select("*").eq("project_id", str(project_id)).order("sort_order").execute()
    return result.data


@router.put("/projects/{project_id}/schedule/{item_id}", response_model=ScheduleItemResponse)
def update_schedule_item(project_id: UUID, item_id: UUID, data: ScheduleItemUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    updates = data.model_dump(exclude_unset=True)
    for field in ("start_time", "end_time"):
        if field in updates:
            updates[field] = to_pg_time(updates[field]) if updates[field] else None
    result = client.table("schedule_items").update(updates).eq("id", str(item_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Schedule item not found")
    return result.data[0]


@router.delete("/projects/{project_id}/schedule/{item_id}")
def delete_schedule_item(project_id: UUID, item_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("schedule_items").delete().eq("id", str(item_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Schedule item not found")
    return {"ok": True}
