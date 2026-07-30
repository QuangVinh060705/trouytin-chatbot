from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    message: str
    detail: str | None = None


class ChatRequest(BaseModel):
    building_code: str = Field(min_length=1, examples=["1"])
    query: str = Field(min_length=1, examples=["Xe gửi ở đâu?"])

    @field_validator("building_code", "query")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Không được để trống.")
        return value.strip()


class LegacyChatResponse(BaseModel):
    building_code: str
    query: str
    answer: str


# Backward-compatible import name.
ChatResponse = LegacyChatResponse


class MobileChatRequest(BaseModel):
    conversation_id: UUID | None = None
    building_code: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=10000)

    @field_validator("building_code", "question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Không được để trống.")
        return value.strip()


class ChatSourceResponse(BaseModel):
    document_id: str | None = None
    title: str | None = None
    original_file_name: str | None = None
    page: int | None = None
    chunk_index: int | None = None
    source: str | None = None


class ChatMessageResponse(BaseModel):
    message_id: UUID
    role: str
    content: str
    created_at: datetime


class MobileChatResponse(BaseModel):
    conversation_id: UUID
    message: ChatMessageResponse
    sources: list[ChatSourceResponse]


class IngestResponse(BaseModel):
    building_code: str
    files_received: list[str]
    total_chunks: int
    message: str


class DocumentResponse(BaseModel):
    document_id: UUID
    original_file_name: str
    storage_url: str | None
    status: str
    building_code: str
    category: str | None
    title: str | None
    chunk_count: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    success: bool
    documents: list[DocumentResponse]


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    page: int
    page_size: int
    total: int


class DocumentReindexResponse(BaseModel):
    success: bool
    document: DocumentResponse


class ConversationResponse(BaseModel):
    conversation_id: UUID
    title: str
    building_code: str
    last_message: str | None = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    page: int
    page_size: int
    total: int


class MessageResponse(BaseModel):
    message_id: UUID
    role: str
    content: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class MessageListResponse(BaseModel):
    conversation_id: UUID
    items: list[MessageResponse]
    page: int
    page_size: int
    total: int
