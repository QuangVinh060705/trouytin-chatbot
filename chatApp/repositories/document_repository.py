from datetime import datetime, timezone
from uuid import UUID

from psycopg import sql
from psycopg.rows import dict_row

from domain.document import Document, DocumentStatus
from repositories.database import connect, get_schema


def _map(row: dict) -> Document:
    return Document(
        document_id=row["DOCUMENT_ID"],
        original_file_name=row["ORIGINAL_FILE_NAME"],
        storage_key=row["STORAGE_KEY"],
        storage_url=row["STORAGE_URL"],
        mime_type=row["MIME_TYPE"],
        file_size=row["FILE_SIZE"],
        building_code=row["BUILDING_CODE"],
        category=row["CATEGORY"],
        title=row["TITLE"],
        status=DocumentStatus(row["STATUS"]),
        chunk_count=row["CHUNK_COUNT"],
        error_message=row["ERROR_MESSAGE"],
        uploaded_by=row["UPLOADED_BY"],
        created_at=row["CREATED_AT"],
        updated_at=row["UPDATED_AT"],
    )


class DocumentRepository:
    def __init__(self):
        self.table = sql.SQL("{}.{}").format(
            sql.Identifier(get_schema()), sql.Identifier("DOCUMENTS")
        )

    def create(self, document: Document) -> Document:
        query = sql.SQL("""
            INSERT INTO {} (
                "DOCUMENT_ID","ORIGINAL_FILE_NAME","STORAGE_KEY","STORAGE_URL",
                "MIME_TYPE","FILE_SIZE","BUILDING_CODE","CATEGORY","TITLE",
                "STATUS","CHUNK_COUNT","ERROR_MESSAGE","UPLOADED_BY",
                "CREATED_AT","UPDATED_AT"
            ) VALUES (
                %(document_id)s,%(original_file_name)s,%(storage_key)s,%(storage_url)s,
                %(mime_type)s,%(file_size)s,%(building_code)s,%(category)s,%(title)s,
                %(status)s,%(chunk_count)s,%(error_message)s,%(uploaded_by)s,
                %(created_at)s,%(updated_at)s
            ) RETURNING *
        """).format(self.table)
        params = {
            field: getattr(document, field)
            for field in document.__dataclass_fields__
        }
        params["status"] = document.status.value
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return _map(cursor.fetchone())

    def get(self, document_id: UUID, include_deleted: bool = False) -> Document | None:
        deleted_filter = sql.SQL("") if include_deleted else sql.SQL(' AND "STATUS" <> %s')
        params = [document_id]
        if not include_deleted:
            params.append(DocumentStatus.DELETED.value)
        query = sql.SQL('SELECT * FROM {} WHERE "DOCUMENT_ID" = %s').format(self.table)
        query += deleted_filter
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            return _map(row) if row else None

    def update_status(
        self, document_id: UUID, status: DocumentStatus, *,
        chunk_count: int | None = None, error_message: str | None = None,
        storage_url: str | None = None,
    ) -> Document:
        query = sql.SQL("""
            UPDATE {} SET
                "STATUS"=%s,
                "CHUNK_COUNT"=COALESCE(%s,"CHUNK_COUNT"),
                "ERROR_MESSAGE"=%s,
                "STORAGE_URL"=COALESCE(%s,"STORAGE_URL"),
                "UPDATED_AT"=%s
            WHERE "DOCUMENT_ID"=%s
            RETURNING *
        """).format(self.table)
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (
                status.value, chunk_count, error_message, storage_url,
                datetime.now(timezone.utc), document_id,
            ))
            row = cursor.fetchone()
            if not row:
                raise KeyError(str(document_id))
            return _map(row)

    def list(self, page: int, page_size: int, building_code: str | None = None):
        where = sql.SQL('WHERE "STATUS" <> %s')
        params: list = [DocumentStatus.DELETED.value]
        if building_code:
            where += sql.SQL(' AND "BUILDING_CODE" = %s')
            params.append(building_code)
        count_query = sql.SQL("SELECT COUNT(*) FROM {} ").format(self.table) + where
        list_query = (
            sql.SQL("SELECT * FROM {} ").format(self.table)
            + where
            + sql.SQL(' ORDER BY "CREATED_AT" DESC LIMIT %s OFFSET %s')
        )
        with connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(count_query, params)
            total = cursor.fetchone()["count"]
            cursor.execute(list_query, [*params, page_size, (page - 1) * page_size])
            return [_map(row) for row in cursor.fetchall()], total
