from threading import Lock

from core.chatbot_trouytin import RealEstateBot
from services.area_bot_service import AreaBotService
from services.chat_history_repository import ChatHistoryRepository


class ChatbotWebService:
    """Service xử lý hội thoại chatbot web, dùng RealEstateBot làm core."""

    def __init__(self, area_service: AreaBotService, history_repository: ChatHistoryRepository):
        self.area_service = area_service
        self.history_repository = history_repository
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
        stripped_message = message.strip()
        result = bot.process_message(stripped_message)
        self.history_repository.log_turn(
            session_id=session_id,
            user_message=stripped_message,
            assistant_message=result.get("message", ""),
            response_type=result.get("type", "result"),
        )
        return result

    def clear(self, session_id: str) -> dict:
        with self._lock:
            removed = self._sessions.pop(session_id, None)

        return {
            "type": "system",
            "message": "Đã xóa ngữ cảnh hội thoại." if removed else "Session chưa có dữ liệu.",
            "data": [],
            "current_filters": {},
        }
