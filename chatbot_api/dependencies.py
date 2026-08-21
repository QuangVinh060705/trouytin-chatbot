from functools import lru_cache

from services.area_bot_service import AreaBotService
from services.chat_history_repository import ChatHistoryRepository
from services.chatbot_web_service import ChatbotWebService


@lru_cache
def get_area_service() -> AreaBotService:
    return AreaBotService()


@lru_cache
def get_chat_history_repository() -> ChatHistoryRepository:
    return ChatHistoryRepository()


@lru_cache
def get_chatbot_service() -> ChatbotWebService:
    return ChatbotWebService(
        area_service=get_area_service(),
        history_repository=get_chat_history_repository(),
    )
