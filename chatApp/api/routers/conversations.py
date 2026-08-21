from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from api.dependencies import CurrentUser, get_current_user
from api.schemas import (
    ConversationListResponse, ConversationResponse,
    MessageListResponse, MessageResponse,
)
from core.conversation_service import ConversationService
from repositories.conversation_repository import ConversationRepository
from repositories.message_repository import MessageRepository

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _service() -> ConversationService:
    return ConversationService(ConversationRepository(), MessageRepository())


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    items, total = await run_in_threadpool(
        _service().list_conversations, user.user_id, page, page_size
    )
    return ConversationListResponse(
        items=[ConversationResponse(
            conversation_id=item.conversation_id, title=item.title,
            building_code=item.building_code, last_message=item.last_message,
            message_count=item.message_count, created_at=item.created_at,
            updated_at=item.updated_at,
        ) for item in items],
        page=page, page_size=page_size, total=total,
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    conversation, messages, total = await run_in_threadpool(
        _service().list_messages,
        user.user_id, conversation_id, page, page_size,
    )
    return MessageListResponse(
        conversation_id=conversation.conversation_id,
        items=[MessageResponse(
            message_id=item.message_id, role=item.role.value,
            content=item.content, sources=item.sources,
            created_at=item.created_at,
        ) for item in messages],
        page=page, page_size=page_size, total=total,
    )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    await run_in_threadpool(_service().delete, user.user_id, conversation_id)
    return {"success": True, "message": "Đã xóa cuộc trò chuyện."}
