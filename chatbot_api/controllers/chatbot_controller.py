import logging

from fastapi import APIRouter, Depends, HTTPException

from dependencies import get_chatbot_service
from models.chatbot_models import ChatRequest, ChatResponse, ClearChatRequest
from services.chatbot_web_service import ChatbotWebService

router = APIRouter(prefix="/api/chatbot", tags=["Chatbot Web"])
logger = logging.getLogger(__name__)


@router.post("/message", response_model=ChatResponse)
def send_message(
    request: ChatRequest,
    service: ChatbotWebService = Depends(get_chatbot_service),
):
    try:
        result = service.chat(request.session_id, request.message)
        return ChatResponse(
            type=result.get("type", "result"),
            message=result.get("message", ""),
            data=result.get("data", []),
            current_filters=result.get("current_filters", {}),
        )
    except Exception as exc:
        logger.exception("Lỗi xử lý POST /api/chatbot/message")
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý chatbot: {exc}") from exc


@router.delete("/session", response_model=ChatResponse)
def clear_session(
    request: ClearChatRequest,
    service: ChatbotWebService = Depends(get_chatbot_service),
):
    return ChatResponse(**service.clear(request.session_id))
