import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.chatbotAppController import router as chatbot_router
from controllers.ingestController import router as ingest_router

app = FastAPI(
    title="Building RAG Chatbot API",
    description="Hệ thống API quản lý Chatbot nội bộ tòa nhà",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chatbot_router)
app.include_router(ingest_router)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "Chatbot API Running"}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
