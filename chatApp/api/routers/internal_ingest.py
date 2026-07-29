"""Internal endpoint used by the Prop-Tech backend after knowledge changes."""

from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from api.dependencies import verify_internal_api_key
from core.db_ingest import fetch_building_codes_for_owner, rebuild_from_postgres
from core.document_service import DocumentService
from core.storage_service import get_storage_service
from repositories.document_repository import DocumentRepository


router = APIRouter(prefix="/api/internal/ingest", tags=["internal-ingest"])


def _document_service() -> DocumentService:
    return DocumentService(DocumentRepository(), get_storage_service())


class RebuildRequest(BaseModel):
    rebuild: bool = True
    building_id: int | None = None


@router.post("/rebuild")
async def rebuild(
    payload: RebuildRequest,
    _: None = Depends(verify_internal_api_key),
):
    if not payload.rebuild:
        raise HTTPException(status_code=400, detail="rebuild phải bằng true.")

    result = await run_in_threadpool(rebuild_from_postgres, payload.building_id)
    from core.retriever_cache import invalidate
    for building_code in result["buildings"]:
        invalidate(building_code)
    return {"success": True, "result": result}


@router.post("/document")
async def ingest_uploaded_document(
    file: UploadFile = File(...),
    owner_user_id: int = Form(...),
    uploaded_by: str = Form(...),
    category: str | None = Form(None),
    title: str | None = Form(None),
    _: None = Depends(verify_internal_api_key),
):
    """Persist and vectorize one uploaded file under the owner's shared knowledge scope.

    Building_code dùng "OWNER-{owner_user_id}" - CÙNG quy ước với
    ChatAppProxyService (mobile) - để tài liệu upload từ web và mobile chia sẻ
    chung một kho tri thức theo chủ nhà, thay vì bị tách theo mã tòa nhà thật
    (khiến hai luồng không bao giờ thấy dữ liệu của nhau).
    """
    building_codes = await run_in_threadpool(
        fetch_building_codes_for_owner, owner_user_id
    )
    if not building_codes:
        raise HTTPException(
            status_code=404,
            detail="Chủ tòa nhà chưa có tòa nhà hoạt động để ingest tài liệu.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File upload rỗng.")

    service = _document_service()
    owner_building_code = f"OWNER-{owner_user_id}"
    document = await run_in_threadpool(
        service.create_document,
        stream=BytesIO(content),
        file_name=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        size=len(content),
        building_code=owner_building_code,
        category=category,
        title=title,
        uploaded_by=uploaded_by,
    )

    return {
        "success": True,
        "result": {
            "documents": 1,
            "chunks": document.chunk_count,
            "buildings": building_codes,
            "owner_building_code": owner_building_code,
            "items": [{
                "document_id": str(document.document_id),
                "building_code": document.building_code,
                "status": document.status.value,
                "chunk_count": document.chunk_count,
            }],
        },
    }
