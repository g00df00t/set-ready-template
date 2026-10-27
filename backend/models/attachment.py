from pydantic import BaseModel
from uuid import UUID


class AttachmentResponse(BaseModel):
    id: UUID
    project_id: UUID
    filename: str
    content_type: str
    byte_size: int
    # Carried so the UI can show "23.6 MB → 2.5 MB" instead of silently
    # rewriting what the producer uploaded.
    original_byte_size: int
    sort_order: int
