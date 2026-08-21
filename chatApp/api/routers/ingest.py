"""
api/routers/ingest.py
-------------------------
Endpoint cho phép upload tài liệu mới -> lưu tạm xuống đĩa -> gọi
core.ingest.ingest_file -> refresh cache retriever cho tòa nhà đó.

Đây là endpoint LEGACY (giữ để tương thích client cũ). Với luồng mới nên dùng
POST /api/documents (DocumentService) vì có vòng đời tài liệu đầy đủ, ID vector
tiền định và kiểm tra file 3 tầng.
"""

import os
import re
import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from api.dependencies import verify_internal_api_key
from api.schemas import IngestResponse
from core import config
from core.ingest import ingest_file

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Nơi lưu lại bản gốc tài liệu đã upload (tuỳ chọn, để đối chiếu/audit sau này).
# Đường dẫn TUYỆT ĐỐI theo config.BASE_DIR: trước đây là "data" tương đối theo
# thư mục làm việc, nên chạy uvicorn từ chỗ khác sẽ ghi file ra ngoài project.
DATA_DIR = Path(config.BASE_DIR) / "data"

# Chỉ giữ ký tự an toàn cho cả tên file và building_code -> chặn path traversal.
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_segment(value: str, fallback: str) -> str:
    """Chuẩn hóa một đoạn đường dẫn về dạng an toàn.

    Path(...).name bỏ mọi thành phần thư mục ("../../x" -> "x"), regex loại bỏ
    ký tự lạ, rồi strip "." đầu/cuối để không tạo ra ".." hay file ẩn.
    """
    cleaned = _SAFE_SEGMENT.sub("_", Path(value).name).strip("._")
    return cleaned or fallback


@router.post("", response_model=IngestResponse)
async def ingest_documents(
    building_code: str = Form(..., description="Mã tòa nhà, VD: A1"),
    uploaded_by: str = Form(None, description="Người upload (tuỳ chọn)"),
    files: List[UploadFile] = File(...),
    _: None = Depends(verify_internal_api_key),
):
    """Trước đây endpoint này KHÔNG xác thực nhưng lại GHI dữ liệu vào kho tri
    thức: ai cũng có thể bơm "quy định" giả mà chatbot sẽ trích dẫn như thật
    (đầu độc RAG), và tên file được dùng thô nên ghi được ra ngoài thư mục dự
    kiến. Giờ bắt buộc internal API key + làm sạch mọi đoạn đường dẫn.
    """
    building_code = building_code.strip().upper()
    if not building_code:
        raise HTTPException(status_code=400, detail="Thiếu building_code.")

    if not files:
        raise HTTPException(status_code=400, detail="Chưa có file nào được upload.")

    if len(files) > config.MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Số file phải từ 1 đến {config.MAX_FILES_PER_UPLOAD}.",
        )

    safe_building = _safe_segment(building_code, "UNKNOWN")
    building_dir = DATA_DIR / safe_building
    building_dir.mkdir(parents=True, exist_ok=True)

    max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    total_chunks = 0
    received_names = []

    for upload in files:
        original_name = upload.filename or "document"
        ext = os.path.splitext(original_name)[1].lower()
        if ext not in config.SUPPORTED_EXT:
            raise HTTPException(
                status_code=400,
                detail=f"Định dạng không hỗ trợ: {original_name} ({ext})",
            )

        upload.file.seek(0, os.SEEK_END)
        size = upload.file.tell()
        upload.file.seek(0)
        if size <= 0:
            raise HTTPException(status_code=400, detail=f"File rỗng: {original_name}")
        if size > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File {original_name} vượt quá {config.MAX_UPLOAD_SIZE_MB} MB.",
            )

        # Giữ nguyên đuôi file (loader chọn theo đuôi), chỉ làm sạch phần tên.
        safe_name = _safe_segment(Path(original_name).stem, "document") + ext
        dest_path = building_dir / safe_name

        # Chốt an toàn cuối: đường dẫn kết quả phải nằm trong building_dir.
        resolved = dest_path.resolve()
        if not resolved.is_relative_to(building_dir.resolve()):
            raise HTTPException(
                status_code=400, detail=f"Tên file không hợp lệ: {original_name}"
            )

        with open(resolved, "wb") as f:
            shutil.copyfileobj(upload.file, f)

        try:
            total_chunks += ingest_file(
                str(resolved), building_code, uploaded_by=uploaded_by
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Lỗi ingest file {original_name}: {e}"
            )

        received_names.append(original_name)

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
