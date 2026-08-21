import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.admin_chatbot_controller import router as admin_chatbot_router
from controllers.area_controller import router as area_router
from controllers.chatbot_controller import router as chatbot_router

app = FastAPI(
    title="TroUyTin Chatbot API",
    version="1.0.0",
    description="API chatbot tìm phòng và tìm tòa nhà theo khoảng cách.",
)

# Frontend Next.js gọi trực tiếp API này từ browser nên vẫn cần CORS, nhưng
# KHÔNG được mở "*": /api/chatbot/message tiêu thụ quota Groq, mở hết nghĩa là
# mọi website đều gọi được và làm cạn quota. Khai báo origin được phép qua biến
# môi trường CHATBOT_CORS_ORIGINS (phân tách bằng dấu phẩy).
_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CHATBOT_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chatbot_router)
app.include_router(area_router)
app.include_router(admin_chatbot_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.head("/health")
def health_head():
    """Uptime monitor thường dùng HEAD; @app.get không tự nhận HEAD nên phải
    khai báo riêng, nếu không sẽ trả 405."""
    return
