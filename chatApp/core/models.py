"""
core/models.py
---------------
Khởi tạo 1 LẦN DUY NHẤT các model AI dùng chung: embedding, vector DB, LLM.
Cả api/ và cli/ đều import từ đây để tránh load model nhiều lần
(load embedding model tốn thời gian, không nên load lại mỗi request).
"""

import logging

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_groq import ChatGroq

from core import config

logger = logging.getLogger(__name__)
logger.info("Initializing embedding, LLM and vector database")

embeddings = HuggingFaceEmbeddings(
    model_name=config.EMBEDDING_MODEL,
    model_kwargs={"device": "cpu"},
)

vector_db = Chroma(
    persist_directory=config.CHROMA_DB_DIR,
    embedding_function=embeddings,
    collection_name=config.CHROMA_COLLECTION_NAME,
)

llm = ChatGroq(
    model=config.GROQ_MODEL,
    temperature=0.3,
    groq_api_key=config.GROQ_API_KEY,
)

logger.info("Embedding, LLM and vector database initialized")
