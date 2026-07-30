"""FastAPI entrypoint. Business logic lives outside the HTTP layer."""

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.routers import chat, conversations, documents, ingest, internal_ingest
from core.database import check_connection
from core.exceptions import AppError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Chatbot Hỗ Trợ Cư Dân - API",
    description="Chatbot RAG, document management và conversation history.",
    version="2.0.0",
)

app.include_router(chat.router)
app.include_router(chat.compat_router)
app.include_router(ingest.router)
app.include_router(internal_ingest.router)
app.include_router(documents.router)
app.include_router(conversations.router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request_completed request_id=%s method=%s path=%s duration_ms=%s",
            request_id, request.method, request.url.path, elapsed_ms,
        )
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    logger.exception("unhandled_error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống.",
            "detail": None,
        },
    )


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}


@app.get("/health/database", tags=["health"])
def database_health_check():
    return {"status": "ok", **check_connection()}
