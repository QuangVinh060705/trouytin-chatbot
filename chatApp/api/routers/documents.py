import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from api.dependencies import (
    CurrentUser, assert_building_access, get_current_user,
    require_document_upload_permission,
)
from api.schemas import (
    DocumentListResponse, DocumentReindexResponse, DocumentResponse,
    DocumentUploadResponse,
)
from core import config
from core.document_service import DocumentService
from core.storage_service import get_storage_service
from domain.document import Document
from repositories.document_repository import DocumentRepository

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _service() -> DocumentService:
    return DocumentService(DocumentRepository(), get_storage_service())


def _response(document: Document, include_url: bool = True) -> DocumentResponse:
    # Luôn trỏ qua endpoint nội bộ /file thay vì URL cloud trực tiếp: hoạt động
    # thống nhất cho cả LocalStorageService (không có public URL) và S3/R2, và
    # được kiểm tra quyền theo building_code như mọi endpoint document khác.
    storage_url = f"/api/documents/{document.document_id}/file" if include_url else None
    return DocumentResponse(
        document_id=document.document_id,
        original_file_name=document.original_file_name,
        storage_url=storage_url,
        status=document.status.value,
        building_code=document.building_code,
        category=document.category,
        title=document.title,
        chunk_count=document.chunk_count,
        error=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.post("", response_model=DocumentUploadResponse)
async def upload_documents(
    files: Annotated[list[UploadFile], File()],
    building_code: Annotated[str, Form()],
    category: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    user: CurrentUser = Depends(require_document_upload_permission),
):
    if not files or len(files) > config.MAX_FILES_PER_UPLOAD:
        from core.exceptions import DocumentValidationError
        raise DocumentValidationError(
            f"Số file phải từ 1 đến {config.MAX_FILES_PER_UPLOAD}."
        )
    assert_building_access(user, building_code)
    service = _service()
    results = []
    success = True
    for upload in files:
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(0)
        try:
            document = await run_in_threadpool(
                service.create_document,
                stream=upload.file,
                file_name=upload.filename or "document",
                content_type=upload.content_type or "application/octet-stream",
                size=size,
                building_code=building_code,
                category=category,
                title=title,
                uploaded_by=user.user_id,
            )
        except Exception as exc:
            success = False
            document_id = getattr(exc, "document_id", None)
            if document_id:
                failed = DocumentRepository().get(document_id, include_deleted=True)
                if failed:
                    results.append(_response(failed, include_url=False))
            continue
        results.append(_response(document))
    return DocumentUploadResponse(success=success, documents=results)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    building_code: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
):
    scope = building_code or user.building_code
    assert_building_access(user, scope)
    items, total = await run_in_threadpool(
        DocumentRepository().list, page, page_size, scope
    )
    return DocumentListResponse(
        items=[_response(item) for item in items],
        page=page, page_size=page_size, total=total,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    document = await run_in_threadpool(_service().get, document_id)
    assert_building_access(user, document.building_code)
    return _response(document)


@router.get("/{document_id}/file")
async def download_document_file(
    document_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Trả về nội dung gốc của file (xem trực tiếp hoặc tải về)."""
    document = await run_in_threadpool(_service().get, document_id)
    assert_building_access(user, document.building_code)
    storage = get_storage_service()
    safe_name = Path(document.original_file_name).name.replace('"', "")
    with tempfile.TemporaryDirectory(prefix="chatapp-dl-") as temp_dir:
        local_path = Path(temp_dir) / safe_name
        await run_in_threadpool(storage.get_file, document.storage_key, local_path)
        data = local_path.read_bytes()
    return Response(
        content=data,
        media_type=document.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.post("/{document_id}/reindex", response_model=DocumentReindexResponse)
async def reindex_document(
    document_id: UUID,
    user: CurrentUser = Depends(require_document_upload_permission),
):
    service = _service()
    existing = await run_in_threadpool(service.get, document_id)
    assert_building_access(user, existing.building_code)
    document = await run_in_threadpool(service.reindex, document_id)
    return DocumentReindexResponse(success=True, document=_response(document))


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    user: CurrentUser = Depends(require_document_upload_permission),
):
    service = _service()
    existing = await run_in_threadpool(service.get, document_id)
    assert_building_access(user, existing.building_code)
    await run_in_threadpool(service.delete, document_id)
    return {"success": True, "message": "Đã xóa tài liệu."}
