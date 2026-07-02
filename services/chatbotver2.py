import os
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_groq import ChatGroq

load_dotenv()

CHROMA_DB_DIR = "chroma_db"
# GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

EMBEDDING_MODEL = "BAAI/bge-m3" 

print("Đang khởi tạo các mô hình AI (Embedding, LLM)...")
embeddings = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL,
    model_kwargs={'device': 'cpu'} 
)

vector_db = Chroma(
    persist_directory=CHROMA_DB_DIR,
    embedding_function=embeddings
)

# llm = ChatGoogleGenerativeAI(
#     model="gemini-2.5-pro", 
#     temperature=0.3,
#     google_api_key=GOOGLE_API_KEY
# )
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.3,
    groq_api_key=os.getenv("GROQ_API_KEY") 
)

class RAGRetriever:
    def __init__(self, vector_db, building_code):
        self.vector_db = vector_db
        self.building_code = building_code.strip().upper()
        self.bm25_retriever = None
        
        self._init_bm25()

    def _init_bm25(self):
        """Lấy toàn bộ document của tòa nhà từ Chroma để làm dữ liệu nền cho BM25"""
        all_docs = self.vector_db.get(where={"building_code": self.building_code})
        
        documents = []
        if all_docs and 'documents' in all_docs:
            for content, metadata in zip(all_docs['documents'], all_docs['metadatas']):
                documents.append(Document(page_content=content, metadata=metadata))
        
        if documents:
            self.bm25_retriever = BM25Retriever.from_documents(documents)
            self.bm25_retriever.k = 2  # Lấy top 2 tài liệu khớp từ khóa tốt nhất
        else:
            print(f"[Cảnh báo]: Không tìm thấy dữ liệu cho tòa nhà {self.building_code} để làm BM25.")

    def retrieve(self, query, k_vector=2, score_threshold=0.4):
        """Thực hiện Hybrid Search kết hợp kết quả từ Vector và BM25"""
        # --- 1. VECTOR SEARCH ---
        vector_results = self.vector_db.similarity_search_with_relevance_scores(
            query,
            filter={"building_code": self.building_code},
            k=k_vector
        )
        
        vector_docs = [doc for doc, score in vector_results if score >= score_threshold]
        
        # --- 2. KEYWORD SEARCH (BM25) ---
        bm25_docs = []
        if self.bm25_retriever:
            bm25_docs = self.bm25_retriever.invoke(query)
            
        seen_contents = set()
        combined_docs = []
        
        for doc in vector_docs + bm25_docs:
            if doc.page_content not in seen_contents:
                combined_docs.append(doc)
                seen_contents.add(doc.page_content)
                
        return combined_docs[:3]


# --- GIAI ĐOẠN 4: QUERY REWRITE ---
def rewrite_query(original_query, building_code):
    """Mở rộng câu hỏi tiếng Việt của cư dân để tránh lệch từ khóa khi tìm kiếm"""
    rewrite_prompt = f"""
Bạn là một chuyên gia phân tích ngôn ngữ tối ưu hóa cho hệ thống tìm kiếm (RAG) của tòa nhà {building_code}.
Nhiệm vụ của bạn là chuyển đổi câu hỏi ngắn hoặc ngôn ngữ nói của cư dân thành danh sách các cụm từ khóa/khái niệm tương đương bằng tiếng Việt để hỗ trợ tìm kiếm chính xác trong quy định văn bản.

Yêu cầu:
- Trả về tối đa 2-3 cụm từ/câu ngắn, phân tách bằng dấu phẩy (,).
- Tập trung vào các thuật ngữ hành chính, quy định, danh từ chính liên quan đến câu hỏi.
- Chỉ trả về các cụm từ tìm kiếm, KHÔNG giải thích gì thêm.

Ví dụ:
Người dùng: xe gửi ở đâu
Kết quả: quy định gửi xe, vị trí bãi giữ xe, khu vực đỗ xe

[CÂU HỎI CỦA CƯ DÂN]: {original_query}
[KẾT QUẢ REWRITE]:"""

    try:
        response = llm.invoke(rewrite_prompt)
        expanded_queries = response.content.strip()
        full_search_query = f"{original_query} {expanded_queries.replace(',', ' ')}"
        return full_search_query
    except Exception as e:
        print(f"[Lỗi Rewrite Query]: {e}. Sử dụng query gốc.")
        return original_query


def generate_response(query, retriever, building_code):
    search_query = rewrite_query(query, building_code)
    print(f"   ↳ [Query mở rộng]: {search_query}")
    
    matched_docs = retriever.retrieve(search_query)
    
    if not matched_docs:
        return "Dạ, hiện tại em không tìm thấy thông tin quy định này trong hệ thống dữ liệu của tòa nhà mình. Anh/chị vui lòng liên hệ trực tiếp Hotline Ban quản lý để được hỗ trợ chi tiết ạ."
        
    context = "\n\n---\n\n".join([doc.page_content for doc in matched_docs])
        
    prompt = f"""
Bạn là một trợ lý ảo Chatbot đại diện cho Ban quản lý tòa nhà {building_code}. Bạn đang trò chuyện với cư dân của tòa nhà, hãy luôn giữ thái độ lịch sự, lễ phép, thân thiện và sử dụng ngôn ngữ mượt mà, dễ chịu (ví dụ: xưng "Dạ, Ban quản lý xin thông tin đến anh/chị...", "Xin vui lòng...").

[NGUYÊN TẮC NỘI DUNG (BẮT BUỘC)]:
1. Cung cấp ĐẦY ĐỦ các thông tin, hình thức, mốc thời gian và lưu ý có trong [NGỮ CẢNH QUY ĐỊNH] để hỗ trợ cư dân tốt nhất. Không bỏ sót chi tiết quan trọng nào.
2. TUYỆT ĐỐI KHÔNG tự bịa đặt, không suy diễn thêm bất kỳ quy định hay mốc thời gian nào nằm ngoài văn bản gốc. Chỉ nói những thông tin đã được viết rõ ràng.

[NGỮ CẢNH QUY ĐỊNH]:
{context}

[CÂU HỎI CỦA CƯ DÂN]:
{query}

[CÂU TRẢ LỜI CỦA CHATBOT]:
"""
    
    response = llm.invoke(prompt)
    return response.content.strip()


def main():
    print("\n === HỆ THỐNG CHATBOT HỖ TRỢ CƯ DÂN ===")
    
    while True:
        building_code = input("\nNhập mã tòa nhà của bạn (Ví dụ: A1, A2...): ").strip().upper()
        if building_code:
            break
            
    retriever = RAGRetriever(vector_db, building_code)
    
    print(f"\n[Hệ thống]: Đã kết nối & tối ưu cấu trúc dữ liệu tòa nhà {building_code}.")
    print("Bạn có thể bắt đầu đặt câu hỏi (Gõ 'exit' để thoát).")
    
    while True:
        query = input("\nCư dân: ").strip()
        if query.lower() == 'exit':
            print("Tạm biệt anh/chị cư dân!")
            break
            
        if not query:
            continue
            
        print("Bot đang suy nghĩ và tìm kiếm dữ liệu...")
        reply = generate_response(query, retriever, building_code)
        print(f"Chatbot: {reply}")


if __name__ == "__main__":
    main()