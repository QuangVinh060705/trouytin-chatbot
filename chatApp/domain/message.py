from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True)
class Message:
    message_id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    sources: list[dict[str, Any]]
    created_at: datetime
