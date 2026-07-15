import asyncio
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from controllers.chatbotAppController import chatbot_service
from ingest_from_db import DEFAULT_INTERNAL_API_KEY, run_ingest

router = APIRouter(
    prefix="/api/internal/ingest",
    tags=["Internal Ingest"],
)

_ingest_lock = asyncio.Lock()


class IngestRequest(BaseModel):
    rebuild: bool = Field(default=True)
    building_id: int | None = Field(default=None)


class IngestResponse(BaseModel):
    success: bool
    reloaded: bool
    result: dict[str, Any]


def _expected_internal_key() -> str:
    return (
        os.getenv("CHATBOT_INTERNAL_API_KEY")
        or os.getenv("PROPTECH_INTERNAL_API_KEY")
        or DEFAULT_INTERNAL_API_KEY
    )


def _verify_internal_key(api_key: str | None) -> None:
    if not api_key or api_key != _expected_internal_key():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal API key",
        )


@router.post("/rebuild", response_model=IngestResponse)
async def rebuild_ingest(
    request: IngestRequest,
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-Api-Key"),
) -> IngestResponse:
    _verify_internal_key(x_internal_api_key)

    if _ingest_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ingest is already running",
        )

    async with _ingest_lock:
        result = await run_in_threadpool(
            run_ingest,
            rebuild=request.rebuild,
            building_id=request.building_id,
        )
        chatbot_service.reload_vector_db()

    return IngestResponse(
        success=True,
        reloaded=True,
        result=result,
    )
