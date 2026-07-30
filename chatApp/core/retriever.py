"""
core/retriever.py
-------------------
Hybrid Search (Vector + BM25) theo từng tòa nhà (building_code).
Giữ nguyên logic từ file chatbot.py gốc.
"""

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from core import config
from core.models import vector_db as default_vector_db


class RAGRetriever:
    def __init__(self, building_code, vector_db=None):
        self.vector_db = vector_db or default_vector_db
        self.building_code = building_code.strip().upper()
        self.bm25_retriever = None

        self._init_bm25()

    def _init_bm25(self):
        """Lấy toàn bộ document của tòa nhà từ Chroma để làm dữ liệu nền cho BM25"""
        all_docs = self.vector_db.get(where={"building_code": self.building_code})

        documents = []
        if all_docs and "documents" in all_docs:
            for content, metadata in zip(all_docs["documents"], all_docs["metadatas"]):
                documents.append(Document(page_content=content, metadata=metadata))

        if documents:
            self.bm25_retriever = BM25Retriever.from_documents(documents)
            self.bm25_retriever.k = config.BM25_TOP_K
        else:
            print(f"[Cảnh báo]: Không tìm thấy dữ liệu cho tòa nhà {self.building_code} để làm BM25.")

    def refresh(self):
        """Gọi lại sau khi có tài liệu mới được ingest cho tòa nhà này."""
        self._init_bm25()

    def retrieve(self, query, k_vector=config.DEFAULT_K_VECTOR,
                 score_threshold=config.DEFAULT_SCORE_THRESHOLD):
        """Thực hiện Hybrid Search kết hợp kết quả từ Vector và BM25"""
        # --- 1. VECTOR SEARCH ---
        vector_results = self.vector_db.similarity_search_with_relevance_scores(
            query,
            filter={"building_code": self.building_code},
            k=k_vector,
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

        return combined_docs[:config.DEFAULT_TOP_K_FINAL]
