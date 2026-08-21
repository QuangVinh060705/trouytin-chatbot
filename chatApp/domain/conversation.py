from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class Conversation:
    conversation_id: UUID
    user_id: str
    building_code: str
    title: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool = False
    last_message: str | None = None
    message_count: int = 0
