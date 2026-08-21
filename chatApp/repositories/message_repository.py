import json
from uuid import UUID

from psycopg import sql
from psycopg.rows import dict_row

from domain.message import Message, MessageRole
from repositories.database import connect, get_schema


def _map(row: dict) -> Message:
    return Message(
        message_id=row["MESSAGE_ID"], conversation_id=row["CONVERSATION_ID"],
        role=MessageRole(row["ROLE"]), content=row["CONTENT"],
        sources=row["SOURCES"] or [], created_at=row["CREATED_AT"],
    )


class MessageRepository:
    def __init__(self):
        self.table = sql.SQL("{}.{}").format(
            sql.Identifier(get_schema()), sql.Identifier("CHAT_MESSAGES")
        )

    def create(self, message: Message) -> Message:
        query = sql.SQL("""
            INSERT INTO {} ("MESSAGE_ID","CONVERSATION_ID","ROLE","CONTENT","SOURCES","CREATED_AT")
            VALUES (%s,%s,%s,%s,%s::jsonb,%s) RETURNING *
        """).format(self.table)
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (
                message.message_id, message.conversation_id, message.role.value,
                message.content, json.dumps(message.sources, ensure_ascii=False),
                message.created_at,
            ))
            return _map(cursor.fetchone())

    def list(self, conversation_id: UUID, page: int, page_size: int):
        count_query = sql.SQL('SELECT COUNT(*) FROM {} WHERE "CONVERSATION_ID"=%s').format(self.table)
        list_query = sql.SQL("""
            SELECT * FROM {} WHERE "CONVERSATION_ID"=%s
            ORDER BY "CREATED_AT" ASC LIMIT %s OFFSET %s
        """).format(self.table)
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(count_query, (conversation_id,))
            total = cursor.fetchone()["count"]
            cursor.execute(list_query, (conversation_id, page_size, (page - 1) * page_size))
            return [_map(row) for row in cursor.fetchall()], total

    def recent(self, conversation_id: UUID, limit: int = 10) -> list[Message]:
        query = sql.SQL("""
            SELECT * FROM (
              SELECT * FROM {} WHERE "CONVERSATION_ID"=%s ORDER BY "CREATED_AT" DESC LIMIT %s
            ) recent ORDER BY "CREATED_AT" ASC
        """).format(self.table)
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (conversation_id, limit))
            return [_map(row) for row in cursor.fetchall()]
