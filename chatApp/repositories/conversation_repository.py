from datetime import datetime, timezone
from uuid import UUID

from psycopg import sql
from psycopg.rows import dict_row

from domain.conversation import Conversation
from repositories.database import connect, get_schema


def _map(row: dict) -> Conversation:
    return Conversation(
        conversation_id=row["CONVERSATION_ID"], user_id=row["USER_ID"],
        building_code=row["BUILDING_CODE"], title=row["TITLE"],
        created_at=row["CREATED_AT"], updated_at=row["UPDATED_AT"],
        is_deleted=row["IS_DELETED"],
        last_message=row.get("LAST_MESSAGE"),
        message_count=row.get("MESSAGE_COUNT", 0),
    )


class ConversationRepository:
    def __init__(self):
        schema = get_schema()
        self.table = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier("CHAT_CONVERSATIONS"))
        self.messages = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier("CHAT_MESSAGES"))

    def create(self, conversation: Conversation) -> Conversation:
        query = sql.SQL("""
            INSERT INTO {} ("CONVERSATION_ID","USER_ID","BUILDING_CODE","TITLE","CREATED_AT","UPDATED_AT","IS_DELETED")
            VALUES (%s,%s,%s,%s,%s,%s,FALSE) RETURNING *
        """).format(self.table)
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (
                conversation.conversation_id, conversation.user_id,
                conversation.building_code, conversation.title,
                conversation.created_at, conversation.updated_at,
            ))
            return _map(cursor.fetchone())

    def get_owned(self, conversation_id: UUID, user_id: str) -> Conversation | None:
        query = sql.SQL("""
            SELECT * FROM {} WHERE "CONVERSATION_ID"=%s AND "USER_ID"=%s AND "IS_DELETED"=FALSE
        """).format(self.table)
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (conversation_id, user_id))
            row = cursor.fetchone()
            return _map(row) if row else None

    def touch(self, conversation_id: UUID):
        query = sql.SQL('UPDATE {} SET "UPDATED_AT"=%s WHERE "CONVERSATION_ID"=%s').format(self.table)
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (datetime.now(timezone.utc), conversation_id))

    def list_owned(self, user_id: str, page: int, page_size: int):
        base = sql.SQL(' FROM {} c WHERE c."USER_ID"=%s AND c."IS_DELETED"=FALSE').format(self.table)
        count_query = sql.SQL("SELECT COUNT(*)") + base
        list_query = sql.SQL("""
            SELECT c.*,
              (SELECT m."CONTENT" FROM {} m WHERE m."CONVERSATION_ID"=c."CONVERSATION_ID"
               ORDER BY m."CREATED_AT" DESC LIMIT 1) AS "LAST_MESSAGE",
              (SELECT COUNT(*) FROM {} m WHERE m."CONVERSATION_ID"=c."CONVERSATION_ID") AS "MESSAGE_COUNT"
        """).format(self.messages, self.messages) + base + sql.SQL(
            ' ORDER BY c."UPDATED_AT" DESC LIMIT %s OFFSET %s'
        )
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(count_query, (user_id,))
            total = cursor.fetchone()["count"]
            cursor.execute(list_query, (user_id, page_size, (page - 1) * page_size))
            return [_map(row) for row in cursor.fetchall()], total

    def soft_delete(self, conversation_id: UUID, user_id: str) -> bool:
        query = sql.SQL("""
            UPDATE {} SET "IS_DELETED"=TRUE,"UPDATED_AT"=%s
            WHERE "CONVERSATION_ID"=%s AND "USER_ID"=%s AND "IS_DELETED"=FALSE
        """).format(self.table)
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (datetime.now(timezone.utc), conversation_id, user_id))
            return cursor.rowcount == 1
