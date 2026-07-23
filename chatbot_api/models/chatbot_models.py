from typing import Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", min_length=1, max_length=100)


class ChatRoom(BaseModel):
    id: str
    roomId: int
    roomCode: str
    roomName: str
    buildingName: str
    price: int
    thumbnailUrl: str | None = None
    detailRoute: str
    matchScore: int
    roomType: str
    status: str
    address: str


class ChatResponse(BaseModel):
    type: str
    message: str
    data: list[ChatRoom] = Field(default_factory=list)
    current_filters: dict[str, Any] = Field(default_factory=dict)


class ClearChatRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=100)
