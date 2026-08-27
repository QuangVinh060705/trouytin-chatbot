"""Build the RAG index from active Prop-Tech records in PostgreSQL."""

from datetime import datetime, timezone
import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from psycopg import sql

from core import config
from core.database import connect, get_schema


def fetch_building_codes_for_owner(owner_user_id: int) -> list[str]:
    """Return active building IDs belonging to one Prop-Tech owner."""
    schema = get_schema()
    query = sql.SQL(
        """
        SELECT "TOA_NHA_ID"
        FROM {}."TOA_NHA"
        WHERE "OWNER_USER_ID" = %s
          AND "IS_DELETED" = FALSE
        ORDER BY "TOA_NHA_ID"
        """
    ).format(sql.Identifier(schema))
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (owner_user_id,))
            return [str(row[0]).upper() for row in cursor.fetchall()]


def _fetch_documents(building_id=None):
    schema = get_schema()
    building_filter = sql.SQL("")
    params = []
    if building_id is not None:
        building_filter = sql.SQL(' AND b."TOA_NHA_ID" = %s')
        params.append(building_id)

    # KHÔNG còn JOIN sang KNOWLEDGE_BASE.
    #
    # Bảng đó từng chứa nội dung tri thức dạng text (TIEU_DE / NOI_DUNG /
    # THE_LOAI / TAGS / IS_ACTIVE) và được nạp thẳng vào RAG ở đây. Nay nó chỉ
    # còn 5 cột metadata file (KB_ID, OWNER_USER_ID, TEN_FILE, FILE_URL,
    # CREATED_AT) - các cột text đã bị bỏ ở phía Prop-Tech - nên query cũ chết
    # với 'column kb.IS_ACTIVE does not exist'.
    #
    # Nội dung tài liệu bây giờ vào ChromaDB qua luồng upload
    # (/api/internal/ingest/document, origin="document"), không đi qua Postgres.
    # Việc của rebuild chỉ còn là dựng lại thông tin tòa nhà (origin="postgres").
    query = sql.SQL(
        """
        SELECT
            b."TOA_NHA_ID",
            b."OWNER_USER_ID",
            b."TEN_TOA_NHA",
            b."DIA_CHI",
            b."SO_TANG",
            b."MO_TA"
        FROM {}."TOA_NHA" AS b
        WHERE b."IS_DELETED" = FALSE
        """
    ).format(sql.Identifier(schema))
    query += building_filter
    query += sql.SQL(' ORDER BY b."TOA_NHA_ID"')

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()


def _to_documents(rows):
    """Build RAG documents tagged with building_code="OWNER-{owner_user_id}".

    Cùng quy ước với ChatAppProxyService (mobile) và internal_ingest.py (upload
    file từ web): mọi tòa nhà của một chủ nhà chia sẻ chung một kho tri thức
    thay vì tách theo mã tòa nhà thật.
    """
    documents = []
    seen_buildings = set()
    for row in rows:
        (
            building_id, owner_user_id, building_name, address, floors, description,
        ) = row
        building_code = f"OWNER-{owner_user_id}"

        if building_id not in seen_buildings:
            seen_buildings.add(building_id)
            documents.append(Document(
                page_content=(
                    f"THÔNG TIN CHUNG TÒA NHÀ\n"
                    f"Tên tòa nhà: {building_name}\n"
                    f"Mã tòa nhà: {building_id}\n"
                    f"Địa chỉ: {address}\n"
                    f"Số tầng: {floors}\n"
                    f"Mô tả: {description or 'chưa cập nhật'}"
                ),
                metadata={
                    "building_code": building_code,
                    "source": f"postgres:building:{building_id}",
                    "source_type": "building",
                    "origin": "postgres",
                },
            ))

    return documents


def rebuild_from_postgres(building_id=None, vector_db=None):
    if vector_db is None:
        # Lazy import keeps database diagnostics and unit tests from loading the
        # large embedding model unnecessarily.
        from core.models import vector_db as default_vector_db
        vector_db = default_vector_db
    documents = _to_documents(_fetch_documents(building_id))
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    building_codes = sorted({doc.metadata["building_code"] for doc in documents})
    where = {"origin": "postgres"}
    if building_id is not None and building_codes:
        # building_id chỉ thuộc một chủ nhà nên building_codes ở đây chỉ có
        # đúng 1 giá trị "OWNER-{owner_user_id}".
        where = {
            "$and": [
                {"origin": "postgres"},
                {"building_code": building_codes[0]},
            ]
        }
    old_vectors = vector_db.get(where=where) if (building_id is None or building_codes) else None
    old_ids = old_vectors.get("ids", []) if old_vectors else []
    if old_ids:
        vector_db.delete(ids=old_ids)

    indexed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ids = []
    for index, chunk in enumerate(chunks):
        source = chunk.metadata["source"]
        digest = hashlib.sha256(chunk.page_content.encode("utf-8")).hexdigest()[:20]
        chunk.metadata["chunk_index"] = index
        chunk.metadata["indexed_at"] = indexed_at
        ids.append(f"{source}:{index}:{digest}")

    if chunks:
        vector_db.add_documents(chunks, ids=ids)

    return {
        "documents": len(documents),
        "chunks": len(chunks),
        "buildings": building_codes,
    }
