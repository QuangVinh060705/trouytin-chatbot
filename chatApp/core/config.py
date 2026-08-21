"""
core/config.py
---------------
Toàn bộ hằng số / cấu hình dùng chung cho core (embedding, LLM, chunking...).
Nếu cần đổi model, đổi chunk size, đổi thư mục DB... chỉ cần sửa ở đây
hoặc trong file .env, KHÔNG cần đụng vào api/.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Console Windows mặc định dùng code page cp1252, không encode được tiếng Việt
# có dấu. Nhiều chỗ trong core/cli in trực tiếp tiếng Việt ra stdout/stderr;
# nếu không reconfigure, một UnicodeEncodeError khi log/print có thể làm crash
# cả request hoặc lệnh CLI. core.config là module nền tảng được import đầu
# tiên ở mọi entrypoint (api/main.py, cli/*), nên fix đặt ở đây áp dụng toàn cục.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ENV = os.getenv("APP_ENV", "development")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

# --- Vector DB ---
CHROMA_DB_DIR = os.path.abspath(
    os.getenv("CHROMA_DB_DIR", os.path.join(BASE_DIR, "chroma_db"))
)
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "chatbot_documents")

# --- Embedding ---
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

# --- LLM (Groq) ---
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# --- Chunking khi ingest ---
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 800))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 100))
SUPPORTED_EXT = (".pdf", ".docx", ".txt", ".md")

# --- PostgreSQL / Prop-Tech ---
# POSTGRES_DSN is preferred. DATABASE_URL and the ASP.NET-style
# ConnectionStrings__DefaultConnection are also accepted.
POSTGRES_DSN = (
    os.getenv("POSTGRES_DSN")
    or os.getenv("DATABASE_URL")
    or os.getenv("ConnectionStrings__DefaultConnection")
)
POSTGRES_SCHEMA = os.getenv("POSTGRES_SCHEMA", os.getenv("Database__Schema", "proptech"))
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", os.getenv("InternalApiKey"))

# Cho phép caller NỘI BỘ (đã có INTERNAL_API_KEY hợp lệ) gọi /api/v1/chat mà
# không mang danh tính người dùng — đây là hình dạng request của ChatService.cs
# bên Prop-Tech: trả LegacyChatResponse và không lưu hội thoại.
#
# LƯU Ý: cờ này KHÔNG còn nghĩa "cho gọi mà không cần xác thực". Internal API
# key giờ LUÔN bắt buộc, xem api/dependencies.py::get_optional_current_user.
# Đặt false khi mọi caller đều đã tiêm đủ X-User-Id / X-User-Role /
# X-Building-Code.
ALLOW_LEGACY_UNAUTHENTICATED_CHAT = (
    os.getenv("ALLOW_LEGACY_UNAUTHENTICATED_CHAT", "true").lower() == "true"
)

# --- Object storage (S3, Cloudflare R2, MinIO, hoặc "local" cho dev) ---
# "local" lưu file trực tiếp trên đĩa (LOCAL_STORAGE_DIR) và không cần thông tin
# đăng nhập cloud - phù hợp cho môi trường chưa cấu hình S3/R2. Nếu S3_* thiếu
# thông tin dù STORAGE_PROVIDER=s3, hệ thống tự rơi về "local" thay vì lỗi cứng.
STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "local")
LOCAL_STORAGE_DIR = os.path.abspath(
    os.getenv("LOCAL_STORAGE_DIR", os.path.join(BASE_DIR, "data", "storage"))
)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_PUBLIC_BASE_URL = (os.getenv("S3_PUBLIC_BASE_URL") or "").rstrip("/")
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
MAX_FILES_PER_UPLOAD = int(os.getenv("MAX_FILES_PER_UPLOAD", "5"))
PRESIGNED_URL_EXPIRES_SECONDS = int(os.getenv("PRESIGNED_URL_EXPIRES_SECONDS", "3600"))

# --- Retrieval ---
DEFAULT_K_VECTOR = 2
DEFAULT_SCORE_THRESHOLD = 0.4
DEFAULT_TOP_K_FINAL = int(os.getenv("RETRIEVAL_TOP_K", "5"))
BM25_TOP_K = 2
