"""Thin HTTP routes for legacy and persistent mobile chat."""

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from api.dependencies import (
    CurrentUser, assert_building_access, get_optional_current_user,
)
from api.schemas import (
    ChatMessageResponse, ChatRequest, LegacyChatResponse,
    MobileChatRequest, MobileChatResponse,
)
from core.conversation_service import ConversationService
from repositories.conversation_repository import ConversationRepository
from repositories.message_repository import MessageRepository

router = APIRouter(prefix="/chat", tags=["chat"])
compat_router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _legacy_mobile_answer(building_code: str, question: str) -> str:
    from core.chatbot import generate_response
    from core.retriever_cache import get_retriever
    return generate_response(
        question, get_retriever(building_code), building_code
    )


@router.post("", response_model=LegacyChatResponse)
def chat(request: ChatRequest):
    from core.chatbot import generate_response
    from core.retriever_cache import get_retriever
    building_code = request.building_code.strip().upper()
    retriever = get_retriever(building_code)
    answer = generate_response(request.query, retriever, building_code)
    return LegacyChatResponse(
        building_code=building_code, query=request.query, answer=answer
    )


@compat_router.post("", response_model=MobileChatResponse | LegacyChatResponse)
async def mobile_chat(
    request: MobileChatRequest,
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    if user is None:
        building_code = request.building_code.strip().upper()
        answer = await run_in_threadpool(
            _legacy_mobile_answer, building_code, request.question,
        )
        return LegacyChatResponse(
            building_code=building_code, query=request.question, answer=answer
        )
    assert_building_access(user, request.building_code)
    service = ConversationService(
        ConversationRepository(), MessageRepository()
    )
    conversation, message, sources = await run_in_threadpool(
        service.chat,
        user_id=user.user_id,
        building_code=request.building_code,
        question=request.question,
        conversation_id=request.conversation_id,
    )
    return MobileChatResponse(
        conversation_id=conversation.conversation_id,
        message=ChatMessageResponse(
            message_id=message.message_id, role=message.role.value,
            content=message.content, created_at=message.created_at,
        ),
        sources=sources,
    )
