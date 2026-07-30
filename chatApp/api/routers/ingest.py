"""
api/routers/ingest.py
-------------------------
Endpoint cho phép upload tài liệu mới -> lưu tạm xuống đĩa -> gọi
core.ingest.ingest_file -> refresh cache retriever cho tòa nhà đó.
"""

import os
import shutil
import tempfile
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from api.schemas import IngestResponse
from core import config
from core.ingest import ingest_file

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Nơi lưu lại bản gốc tài liệu đã upload (tuỳ chọn, để đối chiếu/audit sau này)
DATA_DIR = "data"


@router.post("", response_model=IngestResponse)
async def ingest_documents(
    building_code: str = Form(..., description="Mã tòa nhà, VD: A1"),
    uploaded_by: str = Form(None, description="Người upload (tuỳ chọn)"),
    files: List[UploadFile] = File(...),
):
    building_code = building_code.strip().upper()

    if not files:
        raise HTTPException(status_code=400, detail="Chưa có file nào được upload.")

    building_dir = os.path.join(DATA_DIR, building_code)
    os.makedirs(building_dir, exist_ok=True)

    total_chunks = 0
    received_names = []

    for upload in files:
        ext = os.path.splitext(upload.filename)[1].lower()
        if ext not in config.SUPPORTED_EXT:
            raise HTTPException(
                status_code=400,
                detail=f"Định dạng không hỗ trợ: {upload.filename} ({ext})",
            )

        # Lưu file vào thư mục data/<building_code>/ để giữ bản gốc
        dest_path = os.path.join(building_dir, upload.filename)
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(upload.file, f)

        try:
            total_chunks += ingest_file(dest_path, building_code, uploaded_by=uploaded_by)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi ingest file {upload.filename}: {e}")

        received_names.append(upload.filename)

    # Rất quan trọng: làm mới cache BM25 cho tòa nhà này để câu hỏi tiếp theo
    # thấy được dữ liệu vừa ingest.
    from core.retriever_cache import invalidate
    invalidate(building_code)

    return IngestResponse(
        building_code=building_code,
        files_received=received_names,
        total_chunks=total_chunks,
        message=f"Đã ingest thành công {total_chunks} đoạn tài liệu.",
    )
