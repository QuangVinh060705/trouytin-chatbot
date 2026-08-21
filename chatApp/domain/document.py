from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DocumentStatus(StrEnum):
    UPLOADING = "UPLOADING"
    STORED = "STORED"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    INGEST_FAILED = "INGEST_FAILED"
    DELETED = "DELETED"


@dataclass(slots=True)
class Document:
    document_id: UUID
    original_file_name: str
    storage_key: str
    storage_url: str | None
    mime_type: str
    file_size: int
    building_code: str
    category: str | None
    title: str | None
    status: DocumentStatus
    chunk_count: int
    error_message: str | None
    uploaded_by: str
    created_at: datetime
    updated_at: datetime
