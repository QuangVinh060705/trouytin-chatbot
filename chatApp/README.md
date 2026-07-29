# ChatApp — FastAPI RAG cho Prop-Tech Mobile

ChatApp là service Python/FastAPI cung cấp:

- Chatbot RAG theo từng tòa nhà.
- Upload và quản lý tài liệu trên S3/Cloudflare R2/MinIO.
- Metadata và trạng thái xử lý tài liệu trong PostgreSQL.
- Embedding và hybrid retrieval bằng ChromaDB + BM25.
- Conversation/message history có phân trang và ownership.
- API tương thích với Prop-Tech backend hiện tại.

## 1. Kiến trúc

```text
chatApp/
├── core/
│   ├── config.py
│   ├── models.py
│   ├── database.py
│   ├── chatbot.py
│   ├── query_rewrite.py
│   ├── retriever.py
│   ├── retriever_cache.py
│   ├── ingest.py
│   ├── db_ingest.py
│   ├── document_service.py
│   ├── conversation_service.py
│   ├── storage_service.py
│   └── exceptions.py
├── domain/
│   ├── document.py
│   ├── conversation.py
│   └── message.py
├── repositories/
│   ├── database.py
│   ├── document_repository.py
│   ├── conversation_repository.py
│   └── message_repository.py
├── api/
│   ├── main.py
│   ├── dependencies.py
│   ├── schemas.py
│   └── routers/
│       ├── chat.py
│       ├── ingest.py
│       ├── internal_ingest.py
│       ├── documents.py
│       └── conversations.py
├── migrations/
│   └── 001_documents_conversations.sql
├── cli/
│   ├── migrate.py
│   ├── ingest_cli.py
│   └── chatbot_cli.py
├── tests/
├── data/
├── chroma_db/
├── .env.example
└── requirements.txt
```

Quy tắc:

- `core/` chứa toàn bộ nghiệp vụ, RAG, ingest và storage orchestration.
- `repositories/` là nơi duy nhất chứa SQL cho documents/conversations/messages.
- `api/` chỉ validate, authorize, gọi service và trả response.
- API và CLI dùng chung logic từ `core/`.
- Không đặt prompt, chunking, embedding hoặc ChromaDB operation trong router.

## 2. Authentication và trust boundary

Mobile không gọi trực tiếp các endpoint có trusted headers. Luồng đúng:

```text
Mobile --JWT--> Prop-Tech Backend --trusted headers + internal key--> ChatApp
```

Prop-Tech backend phải xác thực JWT, resolve user/building rồi gửi:

```http
X-Internal-Api-Key: <shared-secret>
X-User-Id: 123
X-User-Role: Admin
X-Building-Code: 1
```

ChatApp chỉ tin `X-User-*` khi `X-Internal-Api-Key` hợp lệ. Mobile không được
biết hoặc gửi internal key.

Role được upload/reindex/delete document:

- `Admin`
- `QuanLy`
- `Manager`

`X-Building-Code` phải khớp `building_code` của request.

## 3. Cấu hình

```bash
cp .env.example .env
```

```env
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000

GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
EMBEDDING_MODEL=BAAI/bge-m3

CHROMA_DB_DIR=./chroma_db
CHROMA_COLLECTION_NAME=chatbot_documents

POSTGRES_DSN=postgresql://postgres:password@localhost:5432/postgres
POSTGRES_SCHEMA=proptech

INTERNAL_API_KEY=
ALLOW_LEGACY_UNAUTHENTICATED_CHAT=true

STORAGE_PROVIDER=s3
S3_ENDPOINT_URL=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET_NAME=
S3_REGION=auto
S3_PUBLIC_BASE_URL=
PRESIGNED_URL_EXPIRES_SECONDS=3600

MAX_UPLOAD_SIZE_MB=10
MAX_FILES_PER_UPLOAD=5
CHUNK_SIZE=800
CHUNK_OVERLAP=100
RETRIEVAL_TOP_K=5
```

Provider S3-compatible:

| Provider | `S3_ENDPOINT_URL` |
|---|---|
| AWS S3 | Để trống |
| Cloudflare R2 | `https://<account-id>.r2.cloudflarestorage.com` |
| MinIO | `http://minio:9000` |

Nếu bucket private, để `S3_PUBLIC_BASE_URL` trống; API sẽ tạo presigned URL.

Không commit `.env` hoặc secret.

## 4. Cài đặt, migration và chạy

PowerShell:

```powershell
cd D:\LinkDoAn
.\.venv\Scripts\python.exe -m pip install -r .\chatApp\requirements.txt

$env:PYTHONPATH="D:\LinkDoAn\chatApp"
.\.venv\Scripts\python.exe -m cli.migrate

cd .\chatApp
..\.venv\Scripts\python.exe -m uvicorn api.main:app `
  --host 0.0.0.0 --port 8000 --reload
```

Linux/macOS:

```bash
cd chatApp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m cli.migrate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Lần chạy đầu cần tải model `BAAI/bge-m3`.

Migration tạo:

- `DOCUMENTS`
- `CHAT_CONVERSATIONS`
- `CHAT_MESSAGES`
- Index theo building/status, user/update time và conversation/create time.

## 5. Document lifecycle

```text
UPLOADING
  ↓ cloud upload thành công
STORED
  ↓ bắt đầu extraction/embedding
PROCESSING
  ↓
INDEXED
```

Failure states:

- `UPLOAD_FAILED`
- `INGEST_FAILED`
- `DELETED`

Cloud upload thành công nhưng ingest thất bại không xóa file cloud. File được
giữ để gọi reindex.

Object key:

```text
documents/{building_code}/{document_id}/{safe_file_name}
```

Tên file người dùng không được dùng trực tiếp làm object key. Server loại ký tự
không an toàn và UUID document ngăn trùng tên.

Chunk metadata:

```json
{
  "document_id": "uuid",
  "building_code": "1",
  "original_file_name": "noi_quy_A1.pdf",
  "storage_key": "documents/1/uuid/noi_quy_A1.pdf",
  "category": "Nội quy",
  "uploaded_by": "123",
  "chunk_index": 0,
  "page": 1,
  "source": "document:uuid",
  "origin": "document"
}
```

Vector ID:

```text
{document_id}:{chunk_index}
```

Reindex xóa vector cũ theo `document_id` trước khi ghi lại. Lock in-process ngăn
hai request reindex cùng document chạy đồng thời.

## 6. API

### Health

```http
GET /health
GET /health/database
```

### Legacy chat

Giữ tương thích, không tạo conversation:

```http
POST /chat
Content-Type: application/json

{
  "building_code": "1",
  "query": "Nội quy gửi xe là gì?"
}
```

### Mobile chat có conversation

```http
POST /api/v1/chat
X-Internal-Api-Key: ...
X-User-Id: 123
X-User-Role: CuDan
X-Building-Code: 1
Content-Type: application/json

{
  "conversation_id": null,
  "building_code": "1",
  "question": "Nội quy gửi xe là gì?"
}
```

Response:

```json
{
  "conversation_id": "9ad3c6aa-4d44-4260-a43d-f2b53f42728f",
  "message": {
    "message_id": "aa337afb-f9fd-49c1-af87-a364d9fc73df",
    "role": "assistant",
    "content": "Xe được gửi tại tầng hầm...",
    "created_at": "2026-07-26T08:10:00Z"
  },
  "sources": [
    {
      "document_id": "uuid",
      "title": "Nội quy",
      "original_file_name": "noi_quy_A1.pdf",
      "page": 2,
      "chunk_index": 3,
      "source": "document:uuid"
    }
  ]
}
```

Nếu gửi `conversation_id`, service kiểm tra conversation thuộc đúng user và
building trước khi ghi message.

Để giữ tương thích bridge Prop-Tech cũ, nếu hoàn toàn không có trusted headers
và `ALLOW_LEGACY_UNAUTHENTICATED_CHAT=true`, endpoint chạy stateless và trả
schema cũ có trường `answer`. Sau khi Prop-Tech đã luôn gửi internal key/user
headers, đặt biến này thành `false`.

### Upload documents

```http
POST /api/documents
X-Internal-Api-Key: ...
X-User-Id: 123
X-User-Role: Admin
X-Building-Code: 1
Content-Type: multipart/form-data
```

Fields:

- `files`: 1–`MAX_FILES_PER_UPLOAD` file.
- `building_code`.
- `category` tùy chọn.
- `title` tùy chọn.

Hỗ trợ PDF, DOCX, TXT, MD. API kiểm tra extension, MIME, size, file rỗng và
signature cơ bản.

### List/detail/reindex/delete documents

```http
GET    /api/documents?page=1&page_size=20&building_code=1
GET    /api/documents/{document_id}
POST   /api/documents/{document_id}/reindex
DELETE /api/documents/{document_id}
```

Reindex/delete yêu cầu role quản lý. Delete thực hiện:

1. Kiểm tra ownership building.
2. Xóa vector ChromaDB.
3. Xóa object cloud.
4. Đánh dấu `DELETED` trong PostgreSQL.
5. Invalidate retriever cache.

### Conversations

```http
GET /api/conversations?page=1&page_size=20
GET /api/conversations/{conversation_id}/messages?page=1&page_size=50
DELETE /api/conversations/{conversation_id}
```

Chỉ owner có `X-User-Id` khớp mới xem/xóa được. `page >= 1`,
`1 <= page_size <= 100`.

### Raw file ingest tương thích cũ

```http
POST /ingest
```

Endpoint cũ vẫn hoạt động nhưng chỉ nên dùng nội bộ/CLI. API Documents là lựa
chọn chuẩn vì có cloud storage, PostgreSQL metadata và lifecycle.

### PostgreSQL rebuild tương thích Prop-Tech

```http
POST /api/internal/ingest/rebuild
X-Internal-Api-Key: ...
Content-Type: application/json

{
  "rebuild": true,
  "building_id": null
}
```

Endpoint này rebuild knowledge từ `TOA_NHA` và `KNOWLEDGE_BASE`, chỉ thay các
vector có `origin=postgres`; không xóa vector document upload.

## 7. Standard error response

```json
{
  "success": false,
  "error_code": "INGEST_FAILED",
  "message": "Không thể xử lý tài liệu.",
  "detail": null
}
```

Stack trace chỉ được log ở server, không trả ra client. Log không chứa API key,
password, JWT, nội dung file hoặc toàn bộ prompt.

Mỗi response có header `X-Request-Id`.

## 8. Curl kiểm thử

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/database
```

```bash
curl -X POST http://localhost:8000/api/documents \
  -H "X-Internal-Api-Key: secret" \
  -H "X-User-Id: 123" \
  -H "X-User-Role: Admin" \
  -H "X-Building-Code: 1" \
  -F "building_code=1" \
  -F "category=Nội quy" \
  -F "files=@noi_quy_A1.pdf"
```

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: secret" \
  -H "X-User-Id: 123" \
  -H "X-User-Role: CuDan" \
  -H "X-Building-Code: 1" \
  -d '{"conversation_id":null,"building_code":"1","question":"Nội quy gửi xe là gì?"}'
```

```bash
curl "http://localhost:8000/api/conversations?page=1&page_size=20" \
  -H "X-Internal-Api-Key: secret" \
  -H "X-User-Id: 123" \
  -H "X-User-Role: CuDan" \
  -H "X-Building-Code: 1"
```

## 9. React Native/Expo contract

Mobile thực tế nên gọi Prop-Tech backend bằng JWT. Ví dụ dưới đây thể hiện body;
Prop-Tech chịu trách nhiệm thêm trusted headers khi proxy sang ChatApp.

```typescript
const formData = new FormData();
formData.append("building_code", buildingCode);
formData.append("category", category);
formData.append("files", {
  uri: selectedFile.uri,
  name: selectedFile.name,
  type: selectedFile.mimeType,
} as any);

await propTechApi.post("/api/documents", formData, {
  headers: { "Content-Type": "multipart/form-data" },
});
```

```typescript
const result = await propTechApi.post("/api/v1/chat", {
  conversation_id: conversationId,
  building_code: buildingCode,
  question: inputMessage,
});
```

```typescript
await propTechApi.get("/api/conversations", {
  params: { page: 1, page_size: 20 },
});

await propTechApi.get(
  `/api/conversations/${conversationId}/messages`,
  { params: { page: 1, page_size: 50 } },
);
```

Nếu Prop-Tech chưa expose các route này, cần thêm proxy controller/service ở
Prop-Tech. Không đưa `INTERNAL_API_KEY` vào bundle Expo.

## 10. Docker

Backend chạy Docker, ChatApp chạy host:

```env
Chatbot__BaseUrl=http://host.docker.internal:8000
```

Cùng Docker Compose:

```env
Chatbot__BaseUrl=http://chatapp:8000
```

Mount persistent volume cho:

- `CHROMA_DB_DIR`
- File/database của MinIO nếu tự host.

PostgreSQL và S3/R2 phải dùng endpoint truy cập được từ container, không dùng
`localhost` để trỏ sang container khác.

## 11. Test

```powershell
$env:PYTHONPATH="D:\LinkDoAn\chatApp"
.\.venv\Scripts\python.exe -m unittest discover -s .\chatApp\tests -v
```

Test hiện có:

- Chuyển connection string Npgsql sang psycopg DSN.
- Kiểm tra signature file.
- Xóa vector cũ và deterministic vector IDs.

## 12. Checklist end-to-end

- [ ] Migration chạy thành công.
- [ ] `GET /health/database` trả `200`.
- [ ] R2/S3/MinIO credentials hợp lệ.
- [ ] Upload PDF/DOCX/TXT/MD thành công.
- [ ] Cloud có object key chứa UUID.
- [ ] `DOCUMENTS.STATUS = INDEXED`.
- [ ] `CHUNK_COUNT > 0`.
- [ ] Chroma metadata có `document_id` và `building_code`.
- [ ] Reindex không tạo vector trùng.
- [ ] Delete xóa vector và object cloud.
- [ ] Chat tạo conversation mới.
- [ ] User và assistant message được lưu.
- [ ] Chat trả source document.
- [ ] User khác không đọc/xóa được conversation.
- [ ] Building khác bị từ chối.
- [ ] Pagination validate đúng giới hạn.
- [ ] Internal endpoint từ chối key sai.
- [ ] ChromaDB được mount persistent volume khi deploy.
