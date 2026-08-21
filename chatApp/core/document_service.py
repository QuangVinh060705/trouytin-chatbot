import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
from threading import Lock
from typing import BinaryIO
from uuid import UUID, uuid4

from domain.document import Document, DocumentStatus
from core import config
from core.exceptions import DocumentNotFoundError, DocumentValidationError, IngestionError
from core.ingest import delete_document_vectors, ingest_document
from core.storage_service import StorageService
from repositories.document_repository import DocumentRepository

logger = logging.getLogger(__name__)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_MIME = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
}
_reindex_locks: dict[UUID, Lock] = {}
_reindex_locks_guard = Lock()


def _invalidate(building_code: str) -> None:
    from core.retriever_cache import invalidate
    invalidate(building_code)


class DocumentService:
    def __init__(self, repository: DocumentRepository, storage: StorageService):
        self.repository = repository
        self.storage = storage

    @staticmethod
    def validate_file(file_name: str, content_type: str, size: int) -> None:
        extension = Path(file_name).suffix.lower()
        if extension not in config.SUPPORTED_EXT:
            raise DocumentValidationError(f"Định dạng không hỗ trợ: {extension}")
        if size <= 0:
            raise DocumentValidationError("File rỗng.")
        if size > config.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise DocumentValidationError(
                f"File vượt quá {config.MAX_UPLOAD_SIZE_MB} MB."
            )
        normalized = (content_type or mimetypes.guess_type(file_name)[0] or "").lower()
        if normalized not in _ALLOWED_MIME[extension]:
            raise DocumentValidationError(f"MIME type không hợp lệ: {normalized}")

    @staticmethod
    def validate_signature(stream: BinaryIO, file_name: str) -> None:
        extension = Path(file_name).suffix.lower()
        stream.seek(0)
        header = stream.read(8)
        stream.seek(0)
        if extension == ".pdf" and not header.startswith(b"%PDF-"):
            raise DocumentValidationError("Nội dung file không phải PDF hợp lệ.")
        if extension == ".docx" and not header.startswith(b"PK"):
            raise DocumentValidationError("Nội dung file không phải DOCX hợp lệ.")
        if extension in {".txt", ".md"} and b"\x00" in header:
            raise DocumentValidationError("File text chứa dữ liệu nhị phân.")

    def create_document(
        self, *, stream: BinaryIO, file_name: str, content_type: str, size: int,
        building_code: str, category: str | None, title: str | None, uploaded_by: str,
    ) -> Document:
        self.validate_file(file_name, content_type, size)
        self.validate_signature(stream, file_name)
        document_id = uuid4()
        safe_name = _SAFE_NAME.sub("_", Path(file_name).name).strip("._") or "document"
        storage_key = f"documents/{building_code}/{document_id}/{safe_name}"
        now = datetime.now(timezone.utc)
        document = Document(
            document_id=document_id, original_file_name=Path(file_name).name,
            storage_key=storage_key, storage_url=None, mime_type=content_type,
            file_size=size, building_code=building_code.strip().upper(),
            category=category, title=title, status=DocumentStatus.UPLOADING,
            chunk_count=0, error_message=None, uploaded_by=uploaded_by,
            created_at=now, updated_at=now,
        )
        document = self.repository.create(document)
        try:
            storage_url = self.storage.upload_file(stream, storage_key, content_type)
            document = self.repository.update_status(
                document_id, DocumentStatus.STORED, storage_url=storage_url
            )
        except Exception as exc:
            self.repository.update_status(
                document_id, DocumentStatus.UPLOAD_FAILED, error_message=str(exc)
            )
            setattr(exc, "document_id", document_id)
            raise

        with tempfile.TemporaryDirectory(prefix="chatapp-doc-") as temp_dir:
            local_path = Path(temp_dir) / safe_name
            self.storage.get_file(storage_key, local_path)
            self.repository.update_status(document_id, DocumentStatus.PROCESSING)
            try:
                chunk_count = ingest_document(
                    str(local_path), document_id=str(document_id),
                    building_code=document.building_code,
                    original_file_name=document.original_file_name,
                    storage_key=document.storage_key, category=document.category,
                    uploaded_by=document.uploaded_by,
                )
                document = self.repository.update_status(
                    document_id, DocumentStatus.INDEXED,
                    chunk_count=chunk_count, error_message=None,
                )
                _invalidate(document.building_code)
                logger.info("document_indexed document_id=%s building_code=%s chunks=%s",
                            document_id, document.building_code, chunk_count)
                return document
            except Exception as exc:
                self.repository.update_status(
                    document_id, DocumentStatus.INGEST_FAILED, error_message=str(exc)
                )
                error = IngestionError("Không thể index tài liệu.")
                setattr(error, "document_id", document_id)
                raise error from exc

    def get(self, document_id: UUID) -> Document:
        document = self.repository.get(document_id)
        if not document:
            raise DocumentNotFoundError("Không tìm thấy tài liệu.")
        return document

    def list(self, page: int, page_size: int, building_code: str | None):
        return self.repository.list(page, page_size, building_code)

    def reindex(self, document_id: UUID) -> Document:
        with _reindex_locks_guard:
            lock = _reindex_locks.setdefault(document_id, Lock())
        if not lock.acquire(blocking=False):
            raise IngestionError("Tài liệu đang được reindex.")
        try:
            document = self.get(document_id)
            with tempfile.TemporaryDirectory(prefix="chatapp-reindex-") as temp_dir:
                local_path = Path(temp_dir) / Path(document.original_file_name).name
                self.storage.get_file(document.storage_key, local_path)
                self.repository.update_status(document_id, DocumentStatus.PROCESSING)
                try:
                    count = ingest_document(
                        str(local_path), document_id=str(document_id),
                        building_code=document.building_code,
                        original_file_name=document.original_file_name,
                        storage_key=document.storage_key, category=document.category,
                        uploaded_by=document.uploaded_by,
                    )
                    result = self.repository.update_status(
                        document_id, DocumentStatus.INDEXED,
                        chunk_count=count, error_message=None,
                    )
                    _invalidate(document.building_code)
                    return result
                except Exception as exc:
                    self.repository.update_status(
                        document_id, DocumentStatus.INGEST_FAILED, error_message=str(exc)
                    )
                    raise
        finally:
            lock.release()

    def delete(self, document_id: UUID) -> None:
        document = self.get(document_id)
        delete_document_vectors(str(document_id))
        self.storage.delete_file(document.storage_key)
        self.repository.update_status(document_id, DocumentStatus.DELETED)
        _invalidate(document.building_code)
