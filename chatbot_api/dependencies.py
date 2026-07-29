from functools import lru_cache

from services.area_bot_service import AreaBotService
from services.chatbot_web_service import ChatbotWebService


@lru_cache
def get_area_service() -> AreaBotService:
    return AreaBotService()


@lru_cache
def get_chatbot_service() -> ChatbotWebService:
    return ChatbotWebService(area_service=get_area_service())
