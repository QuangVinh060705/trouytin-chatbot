import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from core.exceptions import ConversationNotFoundError
from domain.conversation import Conversation
from domain.message import Message, MessageRole
from repositories.conversation_repository import ConversationRepository
from repositories.message_repository import MessageRepository

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        conversations: ConversationRepository,
        messages: MessageRepository,
    ):
        self.conversations = conversations
        self.messages = messages

    def chat(
        self, *, user_id: str, building_code: str, question: str,
        conversation_id: UUID | None,
    ) -> tuple[Conversation, Message, list[dict]]:
        now = datetime.now(timezone.utc)
        building_code = building_code.strip().upper()
        if conversation_id:
            conversation = self.conversations.get_owned(conversation_id, user_id)
            if not conversation:
                raise ConversationNotFoundError(
                    "Cuộc trò chuyện không tồn tại hoặc không thuộc người dùng."
                )
            if conversation.building_code != building_code:
                raise ConversationNotFoundError("Cuộc trò chuyện không thuộc tòa nhà này.")
        else:
            conversation = self.conversations.create(Conversation(
                conversation_id=uuid4(), user_id=user_id,
                building_code=building_code, title=question.strip()[:200],
                created_at=now, updated_at=now,
            ))

        self.messages.create(Message(
            message_id=uuid4(), conversation_id=conversation.conversation_id,
            role=MessageRole.USER, content=question.strip(), sources=[],
            created_at=now,
        ))
        recent = self.messages.recent(conversation.conversation_id, limit=10)
        history = "\n".join(
            f"{item.role.value}: {item.content}" for item in recent[:-1]
        )
        from core.chatbot import generate_response_with_sources
        from core.retriever_cache import get_retriever
        retriever = get_retriever(building_code)
        answer, sources = generate_response_with_sources(
            question, retriever, building_code, history
        )
        assistant = self.messages.create(Message(
            message_id=uuid4(), conversation_id=conversation.conversation_id,
            role=MessageRole.ASSISTANT, content=answer, sources=sources,
            created_at=datetime.now(timezone.utc),
        ))
        self.conversations.touch(conversation.conversation_id)
        logger.info(
            "chat_completed user_id=%s conversation_id=%s building_code=%s sources=%s",
            user_id, conversation.conversation_id, building_code, len(sources),
        )
        return conversation, assistant, sources

    def list_conversations(self, user_id: str, page: int, page_size: int):
        return self.conversations.list_owned(user_id, page, page_size)

    def list_messages(
        self, user_id: str, conversation_id: UUID, page: int, page_size: int
    ):
        conversation = self.conversations.get_owned(conversation_id, user_id)
        if not conversation:
            raise ConversationNotFoundError(
                "Cuộc trò chuyện không tồn tại hoặc không thuộc người dùng."
            )
        messages, total = self.messages.list(conversation_id, page, page_size)
        return conversation, messages, total

    def delete(self, user_id: str, conversation_id: UUID) -> None:
        if not self.conversations.soft_delete(conversation_id, user_id):
            raise ConversationNotFoundError(
                "Cuộc trò chuyện không tồn tại hoặc không thuộc người dùng."
            )
