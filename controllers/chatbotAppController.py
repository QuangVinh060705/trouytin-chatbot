from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.chatbotappService import ChatbotService

router = APIRouter(
    prefix="/api/v1/chat",
    tags=["Chatbot"]
)

chatbot_service = ChatbotService()

class ChatRequest(BaseModel):
    building_code: str = Field(..., example="S1.01", description="Mã tòa nhà")
    question: str = Field(..., example="Xe máy gửi ở đâu?", description="Câu hỏi")

class ChatResponse(BaseModel):
    answer: str
    building_code: str

@router.post("", response_model=ChatResponse)
async def ask_chatbot(request: ChatRequest):
    """
    Nhận câu hỏi của cư dân và trả về câu trả lời từ hệ thống RAG.
    """
    try:
        answer = chatbot_service.ask(
            building_code=request.building_code,
            question=request.question
        )
        
        return ChatResponse(
            answer=answer,
            building_code=request.building_code.upper()
        )
        
    except Exception as e:
        print(f"[Controller Error] {e}")
        raise HTTPException(
            status_code=500, 
            detail="Đã xảy ra lỗi hệ thống khi xử lý câu hỏi."
        )