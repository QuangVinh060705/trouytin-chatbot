import os
from typing import List, Optional
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_groq import ChatGroq

load_dotenv()

CHROMA_DB_DIR = "chroma_db"
EMBEDDING_MODEL = "BAAI/bge-m3"
NO_DATA_MESSAGE = (
    "Tôi chưa tìm thấy thông tin này trong hệ thống dữ liệu của tòa nhà. "
    "Câu hỏi đã được ghi nhận để ban quản lý bổ sung vào kho tri thức."
)


class RAGRetriever:
    def __init__(self, vector_db: Chroma, building_code: str):
        self.vector_db = vector_db
        self.building_code = building_code.strip().upper()
        self.bm25_retriever: Optional[BM25Retriever] = None
        self._init_bm25()

    def _init_bm25(self) -> None:
        all_docs = self.vector_db.get(where={"building_code": self.building_code})
        documents: List[Document] = []

        if all_docs and "documents" in all_docs:
            metadatas = all_docs.get("metadatas") or []
            for content, metadata in zip(all_docs["documents"], metadatas):
                documents.append(Document(page_content=content, metadata=metadata or {}))

        if documents:
            self.bm25_retriever = BM25Retriever.from_documents(documents)
            self.bm25_retriever.k = 2
        else:
            print(f"[WARNING] Không tìm thấy dữ liệu cho tòa nhà {self.building_code}")

    def retrieve(self, query: str, k_vector: int = 3, score_threshold: float = 0.35) -> List[Document]:
        vector_results = self.vector_db.similarity_search_with_relevance_scores(
            query,
            filter={"building_code": self.building_code},
            k=k_vector,
        )
        vector_docs = [doc for doc, score in vector_results if score >= score_threshold]

        bm25_docs: List[Document] = []
        if self.bm25_retriever:
            bm25_docs = self.bm25_retriever.invoke(query)

        seen_contents = set()
        combined_docs: List[Document] = []
        for doc in vector_docs + bm25_docs:
            if doc.page_content not in seen_contents:
                combined_docs.append(doc)
                seen_contents.add(doc.page_content)

        return combined_docs[:4]


class ChatbotService:
    def __init__(self):
        print("Dang khoi tao Embedding, Chroma, LLM...")

        self.embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
        )
        self.vector_db = Chroma(
            persist_directory=CHROMA_DB_DIR,
            embedding_function=self.embeddings,
        )
        self.llm = ChatGroq(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=0.3,
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
        self.retriever_cache: dict[str, RAGRetriever] = {}

    def reload_vector_db(self) -> None:
        self.vector_db = Chroma(
            persist_directory=CHROMA_DB_DIR,
            embedding_function=self.embeddings,
        )
        self.retriever_cache.clear()

    def get_retriever(self, building_code: str) -> RAGRetriever:
        normalized = building_code.strip().upper()
        if normalized not in self.retriever_cache:
            self.retriever_cache[normalized] = RAGRetriever(self.vector_db, normalized)
        return self.retriever_cache[normalized]

    def rewrite_query(self, original_query: str, building_code: str) -> str:
        rewrite_prompt = f"""
Bạn là bộ phận tối ưu truy vấn cho chatbot tòa nhà {building_code}.

Hãy chuyển câu hỏi của cư dân thành 2-3 cụm từ khóa ngắn gọn, bằng tiếng Việt có dấu, liên quan đến dữ liệu tòa nhà.
Chỉ trả về các từ khóa, không giải thích.

Ví dụ:
Người dùng: xe gửi ở đâu
Kết quả: quy định gửi xe, bãi giữ xe, phí gửi xe

Câu hỏi: {original_query}
Từ khóa:
"""

        try:
            response = self.llm.invoke(rewrite_prompt)
            expanded = response.content.strip()
            return f"{original_query} {expanded.replace(',', ' ')}"
        except Exception as exc:
            print(f"[Rewrite Error] {exc}")
            return original_query

    def generate_response(self, query: str, retriever: RAGRetriever, building_code: str) -> str:
        search_query = self.rewrite_query(query, building_code)
        print(f"[Search Query]: {search_query}")

        matched_docs = retriever.retrieve(search_query)
        if not matched_docs:
            return NO_DATA_MESSAGE

        context = "\n\n---\n\n".join(doc.page_content for doc in matched_docs)
        prompt = f"""
Bạn là trợ lý AI đại diện ban quản lý tòa nhà {building_code}.

Nguyên tắc:
1. Chỉ trả lời dựa trên dữ liệu được cung cấp.
2. Không suy diễn ngoài dữ liệu.
3. Nếu dữ liệu không có thông tin cần thiết, trả lời đúng câu: "{NO_DATA_MESSAGE}"
4. Trả lời ngắn gọn, rõ ràng, lịch sự, bằng tiếng Việt có dấu.
5. Tuyệt đối không trả lời tiếng Việt không dấu.

Dữ liệu:
{context}

Câu hỏi của cư dân:
{query}

Câu trả lời:
"""

        try:
            response = self.llm.invoke(prompt)
            answer = response.content.strip()
            return answer or NO_DATA_MESSAGE
        except Exception as exc:
            print(f"[LLM Error] {exc}")
            return "Hệ thống AI đang bận. Vui lòng thử lại sau ít phút."

    def ask(self, building_code: str, question: str) -> str:
        retriever = self.get_retriever(building_code)
        return self.generate_response(question, retriever, building_code)
