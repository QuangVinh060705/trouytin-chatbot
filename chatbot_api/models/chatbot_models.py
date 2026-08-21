from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", min_length=1, max_length=100)


class ChatRoom(BaseModel):
    id: str
    # _shared_search() LEFT JOIN sang "PHONG" nên PHONG_ID có thể NULL với bài
    # đăng ở ghép -> để int cứng sẽ làm response_model ném lỗi 500.
    roomId: int | None = None
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

    # --- Các trường riêng của bài đăng Ở GHÉP ---
    # Bắt buộc phải khai báo ở đây: FastAPI serialize theo response_model nên
    # mọi field không có trong schema đều BỊ LOẠI BỎ. Thiếu chúng thì
    # _format_shared_room() tính đúng số chỗ trống nhưng frontend không bao
    # giờ nhận được, và card phòng ở ghép không hiện được "còn N chỗ".
    isShared: bool = False
    postId: int | None = None
    currentOccupants: int | None = None
    maxOccupants: int | None = None
    availableSlots: int | None = None


class ChatResponse(BaseModel):
    type: str
    message: str
    data: list[ChatRoom] = Field(default_factory=list)
    current_filters: dict[str, Any] = Field(default_factory=dict)


class ClearChatRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=100)


class ChatbotAdminMessage(BaseModel):
    id: int
    role: str
    content: str
    response_type: str | None = None
    created_at: datetime


class ChatbotAdminConversation(BaseModel):
    session_id: str
    last_message: str | None = None
    message_count: int
    updated_at: datetime
    status: str


class ChatbotAdminConversationListResponse(BaseModel):
    items: list[ChatbotAdminConversation]
    page: int
    size: int
    total: int


class ChatbotAdminMessageListResponse(BaseModel):
    session_id: str
    items: list[ChatbotAdminMessage]
