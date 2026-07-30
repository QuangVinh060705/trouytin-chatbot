import os

from fastapi import APIRouter, Depends, Header, HTTPException, status

from dependencies import get_chat_history_repository
from models.chatbot_models import (
    ChatbotAdminConversation,
    ChatbotAdminConversationListResponse,
    ChatbotAdminMessage,
    ChatbotAdminMessageListResponse,
)
from services.chat_history_repository import ChatHistoryRepository


def verify_internal_api_key(x_internal_api_key: str = Header(default="")):
    expected = os.getenv("Chatbot__InternalApiKey", "dev-internal-key")
    if not x_internal_api_key or x_internal_api_key != expected:
        raise HTTPException(status_code=403, detail="Invalid internal API key")


router = APIRouter(
    prefix="/api/internal/admin/chatbot",
    tags=["Chatbot Admin (internal)"],
    dependencies=[Depends(verify_internal_api_key)],
)


def _status_for(last_response_type: str | None) -> str:
    return "pending_response" if last_response_type == "error" else "active"


@router.get("/conversations", response_model=ChatbotAdminConversationListResponse)
def list_conversations(
    page: int = 1,
    size: int = 20,
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
):
    page = max(page, 1)
    size = max(1, min(size, 100))
    rows, total = repository.list_sessions(page, size)
    items = [
        ChatbotAdminConversation(
            session_id=row["session_id"],
            last_message=row["last_message"],
            message_count=row["message_count"],
            updated_at=row["updated_at"],
            status=_status_for(row["last_response_type"]),
        )
        for row in rows
    ]
    return ChatbotAdminConversationListResponse(items=items, page=page, size=size, total=total)


@router.get("/conversations/{session_id}/messages", response_model=ChatbotAdminMessageListResponse)
def list_messages(
    session_id: str,
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
):
    rows = repository.list_messages(session_id)
    items = [
        ChatbotAdminMessage(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            response_type=row["response_type"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return ChatbotAdminMessageListResponse(session_id=session_id, items=items)


@router.delete("/conversations/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    session_id: str,
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
):
    deleted = repository.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Khong tim thay hoi thoai")
