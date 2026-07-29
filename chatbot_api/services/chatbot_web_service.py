from threading import Lock

from core.chatbot_trouytin import RealEstateBot
from services.area_bot_service import AreaBotService


class ChatbotWebService:
    """Service xử lý hội thoại chatbot web, dùng RealEstateBot làm core."""

    def __init__(self, area_service: AreaBotService):
        self.area_service = area_service
        self._sessions: dict[str, RealEstateBot] = {}
        self._lock = Lock()

    def _get_bot(self, session_id: str) -> RealEstateBot:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = RealEstateBot(
                    area_bot=self.area_service.bot
                )
            return self._sessions[session_id]

    def chat(self, session_id: str, message: str) -> dict:
        bot = self._get_bot(session_id)
        return bot.process_message(message.strip())

    def clear(self, session_id: str) -> dict:
        with self._lock:
            removed = self._sessions.pop(session_id, None)

        return {
            "type": "system",
            "message": "Đã xóa ngữ cảnh hội thoại." if removed else "Session chưa có dữ liệu.",
            "data": [],
            "current_filters": {},
        }
