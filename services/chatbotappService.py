import os
from typing import List, Optional
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_groq import ChatGroq

# Load environment variables
load_dotenv()

CHROMA_DB_DIR = "chroma_db"
EMBEDDING_MODEL = "BAAI/bge-m3"

class RAGRetriever:
    def __init__(self, vector_db: Chroma, building_code: str):
        self.vector_db = vector_db
        self.building_code = building_code.strip().upper()
        self.bm25_retriever: Optional[BM25Retriever] = None

        self._init_bm25()

    def _init_bm25(self) -> None:
        """Khởi tạo BM25 Retriever dựa trên dữ liệu của tòa nhà từ ChromaDB."""
        all_docs = self.vector_db.get(
            where={"building_code": self.building_code}
        )

        documents: List[Document] = []

        if all_docs and "documents" in all_docs:
            for content, metadata in zip(all_docs["documents"], all_docs["metadatas"]):
                documents.append(Document(page_content=content, metadata=metadata))

        if documents:
            self.bm25_retriever = BM25Retriever.from_documents(documents)
            self.bm25_retriever.k = 2
        else:
            print(f"[WARNING] Không tìm thấy dữ liệu cho tòa nhà {self.building_code}")

    def retrieve(self, query: str, k_vector: int = 2, score_threshold: float = 0.4) -> List[Document]:
        """Thực hiện tìm kiếm kết hợp (Hybrid Search) giữa Vector và BM25."""
        # 1. Tìm kiếm bằng Vector (Semantic Search)
        vector_results = self.vector_db.similarity_search_with_relevance_scores(
            query,
            filter={"building_code": self.building_code},
            k=k_vector
        )

        vector_docs = [
            doc for doc, score in vector_results if score >= score_threshold
        ]

        # 2. Tìm kiếm bằng từ khóa (BM25)
        bm25_docs = []
        if self.bm25_retriever:
            bm25_docs = self.bm25_retriever.invoke(query)

        # 3. Kết hợp và loại bỏ tài liệu trùng lặp
        seen_contents = set()
        combined_docs = []

        for doc in vector_docs + bm25_docs:
            if doc.page_content not in seen_contents:
                combined_docs.append(doc)
                seen_contents.add(doc.page_content)

        return combined_docs[:3]


class ChatbotService:
    def __init__(self):
        print("Đang khởi tạo Embedding, Chroma, LLM...")
        
        self.embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"}
        )

        self.vector_db = Chroma(
            persist_directory=CHROMA_DB_DIR,
            embedding_function=self.embeddings
        )

        self.llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            groq_api_key=os.getenv("GROQ_API_KEY")
        )

        self.retriever_cache: dict[str, RAGRetriever] = {}

    def get_retriever(self, building_code: str) -> RAGRetriever:
        """Lấy hoặc khởi tạo retriever cho một tòa nhà cụ thể (Caching logic)."""
        building_code = building_code.strip().upper()

        if building_code not in self.retriever_cache:
            self.retriever_cache[building_code] = RAGRetriever(
                self.vector_db, 
                building_code
            )

        return self.retriever_cache[building_code]

    def rewrite_query(self, original_query: str, building_code: str) -> str:
        """Sử dụng LLM để mở rộng câu hỏi truy vấn."""
        rewrite_prompt = f"""Bạn là một chuyên gia phân tích ngôn ngữ tối ưu hóa cho hệ thống tìm kiếm (RAG) của tòa nhà {building_code}.

Nhiệm vụ:
Chuyển đổi câu hỏi của cư dân thành 2-3 cụm từ khóa liên quan.
Chỉ trả về từ khóa.

Ví dụ:
Người dùng: xe gửi ở đâu
Kết quả: quy định gửi xe, vị trí bãi giữ xe, khu vực đỗ xe

[CÂU HỎI]: {original_query}
[KẾT QUẢ]:"""

        try:
            response = self.llm.invoke(rewrite_prompt)
            expanded_queries = response.content.strip()
            # Ghép chuỗi tinh gọn bằng f-string
            return f"{original_query} {expanded_queries.replace(',', ' ')}"
        except Exception as e:
            print(f"[Rewrite Error] {e}")
            return original_query

    def generate_response(self, query: str, retriever: RAGRetriever, building_code: str) -> str:
        """Sinh ra câu trả lời cuối cùng cho người dùng."""
        search_query = self.rewrite_query(query, building_code)
        print(f"[Search Query]: {search_query}")

        matched_docs = retriever.retrieve(search_query)

        if not matched_docs:
            return "Dạ, hiện tại em không tìm thấy thông tin quy định này trong hệ thống dữ liệu của tòa nhà."

        context = "\n\n---\n\n".join([doc.page_content for doc in matched_docs])

        prompt = f"""Bạn là chatbot đại diện Ban quản lý tòa nhà {building_code}.

[NGUYÊN TẮC NỘI DUNG]:
1. Cung cấp đầy đủ thông tin có trong dữ liệu.
2. Không bỏ sót thời gian, quy trình, biểu mẫu.
3. Không suy diễn ngoài dữ liệu.
4. Nếu không tìm thấy thông tin thì nói rõ không có trong hệ thống.

[DỮ LIỆU]: 
{context}

[CÂU HỎI]: {query}
[CÂU TRẢ LỜI]:"""

        try:
            response = self.llm.invoke(prompt)
            return response.content.strip()

        except Exception as e:
            print(e)

            return (
                "Dạ, hệ thống AI hiện đang bận. "
                "Anh/chị vui lòng thử lại sau ít phút."
            )

    def ask(self, building_code: str, question: str) -> str:
        """Hàm chính để giao tiếp với Chatbot."""
        retriever = self.get_retriever(building_code)
        return self.generate_response(question, retriever, building_code)

# Khởi tạo Service
# chatbot_service = ChatbotService()