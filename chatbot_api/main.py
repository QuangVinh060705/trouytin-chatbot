from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.area_controller import router as area_router
from controllers.chatbot_controller import router as chatbot_router

app = FastAPI(
    title="TroUyTin Chatbot API",
    version="1.0.0",
    description="API chatbot tìm phòng và tìm tòa nhà theo khoảng cách.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chatbot_router)
app.include_router(area_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.head("/health")
def health_head():
    return
