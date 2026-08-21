from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.database import create_database_engine

_DDL = """
CREATE TABLE IF NOT EXISTS chatbot_sessions (
    session_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chatbot_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chatbot_sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    response_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_chatbot_messages_session_created
    ON chatbot_messages (session_id, created_at);
"""


class ChatHistoryRepository:
    """Luu va truy van lich su hoi thoai chatbot AI, dung cho man hinh lich su cua admin."""

    def __init__(self, engine: Engine | None = None):
        self.engine = engine or create_database_engine()
        with self.engine.begin() as conn:
            conn.exec_driver_sql(_DDL)

    def log_turn(self, session_id: str, user_message: str, assistant_message: str, response_type: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO chatbot_sessions (session_id) VALUES (:session_id) "
                    "ON CONFLICT (session_id) DO NOTHING"
                ),
                {"session_id": session_id},
            )
            conn.execute(
                text(
                    "INSERT INTO chatbot_messages (session_id, role, content, response_type) "
                    "VALUES (:session_id, 'user', :user_content, NULL), "
                    "(:session_id, 'assistant', :assistant_content, :response_type)"
                ),
                {
                    "session_id": session_id,
                    "user_content": user_message,
                    "assistant_content": assistant_message,
                    "response_type": response_type,
                },
            )
            conn.execute(
                text(
                    "UPDATE chatbot_sessions "
                    "SET updated_at = now(), message_count = message_count + 2 "
                    "WHERE session_id = :session_id"
                ),
                {"session_id": session_id},
            )

    def list_sessions(self, page: int, size: int) -> tuple[list[dict], int]:
        with self.engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM chatbot_sessions")).scalar_one()
            rows = conn.execute(
                text(
                    """
                    SELECT s.session_id, s.updated_at, s.message_count,
                           (SELECT m.content FROM chatbot_messages m
                            WHERE m.session_id = s.session_id
                            ORDER BY m.created_at DESC LIMIT 1) AS last_message,
                           (SELECT m.response_type FROM chatbot_messages m
                            WHERE m.session_id = s.session_id AND m.role = 'assistant'
                            ORDER BY m.created_at DESC LIMIT 1) AS last_response_type
                    FROM chatbot_sessions s
                    ORDER BY s.updated_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": size, "offset": (page - 1) * size},
            ).mappings().all()
        return [dict(row) for row in rows], total

    def delete_session(self, session_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM chatbot_sessions WHERE session_id = :session_id"),
                {"session_id": session_id},
            )
            return result.rowcount > 0

    def list_messages(self, session_id: str) -> list[dict]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, role, content, response_type, created_at "
                    "FROM chatbot_messages WHERE session_id = :session_id "
                    "ORDER BY created_at ASC"
                ),
                {"session_id": session_id},
            ).mappings().all()
        return [dict(row) for row in rows]
