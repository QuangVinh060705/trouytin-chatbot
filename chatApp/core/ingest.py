"""
core/ingest.py
------------------
Logic nạp tài liệu vào ChromaDB, gắn metadata building_code + ingested_at.
Đây là nơi bạn sửa nếu muốn: đổi chunk size, thêm định dạng file mới,
đổi cách gắn metadata...
"""

import os
from datetime import datetime
from typing import Any

from core import config
from core.exceptions import IngestionError


def _get_vector_db(vector_db=None):
    if vector_db is not None:
        return vector_db
    from core.models import vector_db as default_vector_db
    return default_vector_db


def get_loader(file_path: str):
    from langchain_community.document_loaders import (
        Docx2txtLoader, PyPDFLoader, TextLoader,
    )
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return PyPDFLoader(file_path)
    elif ext == ".docx":
        return Docx2txtLoader(file_path)
    elif ext in (".txt", ".md"):
        return TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError(f"Định dạng file không được hỗ trợ: {ext}")


def extract_text(file_path: str):
    """Load source documents while preserving loader metadata such as PDF page."""
    return get_loader(file_path).load()


def split_documents(raw_docs):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(raw_docs)


def load_and_split(file_path: str):
    return split_documents(extract_text(file_path))


def delete_document_vectors(document_id: str, vector_db=None) -> int:
    vector_db = _get_vector_db(vector_db)
    result = vector_db.get(where={"document_id": document_id})
    ids = result.get("ids", []) if result else []
    if ids:
        vector_db.delete(ids=ids)
    return len(ids)


def ingest_document(
    file_path: str,
    *,
    document_id: str,
    building_code: str,
    original_file_name: str,
    storage_key: str,
    category: str | None,
    uploaded_by: str,
    vector_db=None,
) -> int:
    """Index a managed document with deterministic IDs and complete metadata."""
    vector_db = _get_vector_db(vector_db)
    try:
        chunks = load_and_split(file_path)
    except Exception as exc:
        raise IngestionError("Không thể đọc hoặc chia tài liệu.") from exc
    if not chunks or not any(chunk.page_content.strip() for chunk in chunks):
        raise IngestionError("Tài liệu không chứa nội dung text có thể index.")

    delete_document_vectors(document_id, vector_db)
    building_code = building_code.strip().upper()
    ids: list[str] = []
    clean_chunks = []
    for index, chunk in enumerate(chunks):
        if not chunk.page_content.strip():
            continue
        page: Any = chunk.metadata.get("page")
        chunk.metadata = {
            "document_id": document_id,
            "building_code": building_code,
            "original_file_name": original_file_name,
            "storage_key": storage_key,
            "category": category or "",
            "uploaded_by": uploaded_by,
            "chunk_index": index,
            "page": int(page) + 1 if isinstance(page, int) else 0,
            "source": f"document:{document_id}",
            "origin": "document",
        }
        ids.append(f"{document_id}:{index}")
        clean_chunks.append(chunk)
    if not clean_chunks:
        raise IngestionError("Tài liệu không tạo được chunk hợp lệ.")
    vector_db.add_documents(clean_chunks, ids=ids)
    return len(clean_chunks)


def reindex_document(file_path: str, **metadata) -> int:
    return ingest_document(file_path, **metadata)


def ingest_file(file_path, building_code, vector_db=None, uploaded_by=None):
    vector_db = _get_vector_db(vector_db)
    building_code = building_code.strip().upper()
    print(f"\n[Ingest] Đang xử lý file: {file_path}")

    try:
        chunks = load_and_split(file_path)
    except Exception as e:
        print(f"[Lỗi] Không đọc được file {file_path}: {e}")
        return 0

    if not chunks:
        print(f"[Cảnh báo] Không trích xuất được nội dung nào từ {file_path}.")
        return 0

    ingested_at = datetime.now().isoformat(timespec="seconds")
    file_name = os.path.basename(file_path)

    for chunk in chunks:
        chunk.metadata["building_code"] = building_code
        chunk.metadata["source"] = file_name
        chunk.metadata["ingested_at"] = ingested_at
        if uploaded_by:
            chunk.metadata["uploaded_by"] = uploaded_by

        chunk.metadata = {
            k: v for k, v in chunk.metadata.items()
            if isinstance(v, (str, int, float, bool))
        }

    vector_db.add_documents(chunks)
    print(
        f"[Ingest] Đã thêm {len(chunks)} đoạn (chunks) vào ChromaDB "
        f"- Tòa nhà {building_code} - Mốc thời gian: {ingested_at}"
    )
    return len(chunks)


def ingest_path(path, building_code, vector_db=None, uploaded_by=None):
    vector_db = _get_vector_db(vector_db)
    total_chunks = 0

    if os.path.isdir(path):
        files = [
            os.path.join(path, f) for f in sorted(os.listdir(path))
            if f.lower().endswith(config.SUPPORTED_EXT)
        ]
        if not files:
            print(f"[Cảnh báo] Không tìm thấy file hợp lệ trong thư mục: {path}")
        for f in files:
            total_chunks += ingest_file(f, building_code, vector_db, uploaded_by)

    elif os.path.isfile(path):
        if not path.lower().endswith(config.SUPPORTED_EXT):
            print(f"[Lỗi] Định dạng file không được hỗ trợ: {path}")
        else:
            total_chunks += ingest_file(path, building_code, vector_db, uploaded_by)
    else:
        print(f"[Lỗi] Đường dẫn không tồn tại: {path}")

    return total_chunks
