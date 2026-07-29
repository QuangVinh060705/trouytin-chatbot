# Chatbot RAG cho Prop-Tech — Tài liệu API & Tích hợp

> Tài liệu này mô tả **service chatbot dùng cho Prop-Tech**: các API, chức năng,
> luồng dữ liệu và cách vận hành.
>
> **Phân tách dự án** (theo thống nhất):
> - `chatbotWeb/` (chat_web) → dùng cho **TroUyTin** (tìm phòng / khu vực, nối MySQL). **Không** thuộc phạm vi tài liệu này.
> - Phần còn lại của `chatbotApp` (`app.py` + `controllers/` + `services/` + `ingest_from_db.py`) → dùng cho **Prop-Tech** (RAG hỏi-đáp theo tòa nhà, nối ChromaDB). **Đây là nội dung tài liệu này.**

---

## 1. Chatbot Prop-Tech là gì

Chatbot RAG (Retrieval-Augmented Generation) trả lời câu hỏi của **cư dân/ban quản lý về từng tòa nhà**:
giá thuê, dịch vụ, phí, nội quy, liên hệ BQL, thông tin phòng...

Đặc điểm:
- Dữ liệu tri thức được **cô lập theo từng tòa nhà** qua `building_code` (= `TOA_NHA_ID` dạng chuỗi, ví dụ `"2"`).
- Chatbot **không kết nối DB trực tiếp** — chỉ đọc kho vector `chroma_db/`.
  Dữ liệu được nạp gián tiếp từ Prop-Tech backend qua script/endpoint ingest.
- Nếu không tìm thấy thông tin, chatbot trả về câu chuẩn "chưa tìm thấy... đã ghi nhận để BQL bổ sung"
  → Prop-Tech backend dùng câu này để đánh dấu **knowledge gap**.

### Công nghệ

| Thành phần | Lựa chọn |
|---|---|
| Web framework | FastAPI (Uvicorn), chạy port **8000** |
| LLM | **Groq** — `ChatGroq`, model mặc định `llama-3.3-70b-versatile` (env `GROQ_MODEL`) |
| Embedding | HuggingFace `BAAI/bge-m3` (CPU) |
| Vector store | **ChromaDB** (thư mục `chroma_db/`) |
| Retrieval | **Hybrid**: vector similarity (Chroma, k=3, ngưỡng score 0.35) + **BM25** keyword (k=2), có **rewrite câu hỏi** thành từ khóa bằng Groq trước khi tìm |

---

## 2. Danh sách API

Base URL mặc định: `http://localhost:8000`
Swagger UI: `http://localhost:8000/docs`

| Method | Path | Nhóm | Bảo vệ | Mô tả |
|---|---|---|---|---|
| `POST` | `/api/v1/chat` | Chatbot | — | Hỏi-đáp RAG theo tòa nhà |
| `POST` | `/api/internal/ingest/rebuild` | Internal | Header `X-Internal-Api-Key` | Rebuild ChromaDB từ dữ liệu Prop-Tech + reload vector db |
| `GET` | `/health` | System | — | Health check |

### 2.1. `POST /api/v1/chat` — Hỏi-đáp RAG

Đây là endpoint **Prop-Tech backend gọi vào** để lấy câu trả lời AI (xem mục 4).

**Request body**
```json
{
  "building_code": "2",
  "question": "Giá thuê phòng thế nào?"
}
```
- `building_code` (string, bắt buộc): mã tòa nhà = `TOA_NHA_ID`. Được `.upper()` khi xử lý.
- `question` (string, bắt buộc): câu hỏi của cư dân.

**Response `200`**
```json
{
  "answer": "…câu trả lời tiếng Việt có dấu…",
  "building_code": "2"
}
```
- Nếu không đủ dữ liệu → `answer` = câu chuẩn:
  *"Tôi chưa tìm thấy thông tin này trong hệ thống dữ liệu của tòa nhà. Câu hỏi đã được ghi nhận để ban quản lý bổ sung vào kho tri thức."*
- Lỗi LLM tạm thời → `answer` = *"Hệ thống AI đang bận. Vui lòng thử lại sau ít phút."*

**Response `500`**: `{ "detail": "Đã xảy ra lỗi hệ thống khi xử lý câu hỏi." }`

**Xử lý nội bộ**: `rewrite_query` (Groq sinh 2-3 từ khóa) → hybrid retrieve (vector + BM25) → nếu không có doc trả câu chuẩn, ngược lại dựng prompt "chỉ trả lời dựa trên dữ liệu" → Groq sinh câu trả lời.

### 2.2. `POST /api/internal/ingest/rebuild` — Rebuild kho tri thức (nội bộ)

Prop-Tech backend gọi endpoint này (sau khi chủ nhà/BQL upload/sửa tri thức) để chatbot nạp lại dữ liệu mới.

**Header bắt buộc**
```
X-Internal-Api-Key: dev-internal-key
```
Key phải khớp `CHATBOT_INTERNAL_API_KEY` (ưu tiên) hoặc `PROPTECH_INTERNAL_API_KEY`, mặc định `dev-internal-key`. Sai key → `403`.

**Request body**
```json
{
  "rebuild": true,
  "building_id": 2
}
```
- `rebuild` (bool, mặc định `true`): xóa sạch dữ liệu cũ trong ChromaDB trước khi nạp lại.
- `building_id` (int | null, mặc định `null`): chỉ nạp 1 tòa nhà; để trống = nạp tất cả.

**Response `200`**
```json
{
  "success": true,
  "reloaded": true,
  "result": {
    "rebuild": true,
    "building_id": 2,
    "proptech_base_url": "http://localhost:5052",
    "raw_items": 40,
    "documents": 38,
    "added": 38,
    "deleted": 12,
    "building_count": 1
  }
}
```

**Các mã lỗi khác**
- `403` — internal key sai/thiếu.
- `409` — đang có một tiến trình ingest khác chạy (có khóa `_ingest_lock`, không cho chạy song song).

**Xử lý nội bộ**: gọi `run_ingest()` (chạy trong threadpool) → sau đó `chatbot_service.reload_vector_db()` để nạp lại vector store + xóa cache retriever ngay lập tức.

### 2.3. `GET /health`

```json
{ "status": "ok", "service": "Chatbot API Running" }
```

---

## 3. Luồng nạp dữ liệu (ingest) từ Prop-Tech

```text
Supabase/Postgres  <-  Prop-Tech backend :5052  <-  ingest_from_db.py / endpoint rebuild  ->  chroma_db/  <-  app.py  ->  câu trả lời
```

- Chatbot **không** giữ mật khẩu DB. Prop-Tech backend là bên duy nhất nối Supabase/Postgres.
- Script `ingest_from_db.py` (hoặc endpoint `/api/internal/ingest/rebuild`) gọi:
  ```text
  GET http://localhost:5052/api/internal/chatbot/knowledge-documents
  Header: X-Internal-Api-Key: dev-internal-key
  Query (tùy chọn): ?buildingId=2
  ```
- Endpoint Prop-Tech này trả về **list** các document dạng:
  ```json
  { "content": "…", "buildingCode": "2", "source": "proptech:TOA_NHA_ID=2" }
  ```
  bao gồm: tiểu sử tòa nhà, liên hệ/hotline BQL, từng phòng (giá thuê, tiện nghi, dịch vụ),
  bảng phí dịch vụ, và các mục KnowledgeBase đang active.
- `ingest_from_db.py` chuyển mỗi item thành `Document` với metadata `{building_code, source}`,
  (rebuild → xóa sạch cũ), embed bằng `BAAI/bge-m3`, ghi vào `chroma_db/`.

### Chạy ingest thủ công (CLI)

```powershell
cd D:\Web_TroUyTin\Chatbot\chatbotApp
venv\Scripts\python.exe ingest_from_db.py --rebuild
```

Tham số:
- `--rebuild` — xóa sạch ChromaDB trước khi nạp lại.
- `--building-id 2` — chỉ nạp 1 tòa nhà theo `TOA_NHA_ID`.
- `--proptech-url` — mặc định lấy `PROPTECH_API_BASE_URL` hoặc `http://localhost:5052`.
- `--internal-api-key` — mặc định lấy `PROPTECH_INTERNAL_API_KEY` hoặc `dev-internal-key`.

Chạy lại ingest mỗi khi dữ liệu tòa nhà/phòng/dịch vụ/knowledge base trong Prop-Tech thay đổi.

---

## 4. Tích hợp với hệ Prop-Tech (đã hiện thực)

### 4.1. App cư dân / mobile → backend .NET → chatbot

App cư dân/mobile **không gọi trực tiếp** chatbot. Chuỗi thật:

```text
Mobile/Frontend  --POST /api/Chat/send-->  Prop-Tech backend (.NET :5052)  --POST /api/v1/chat-->  Chatbot (:8000)
```

Prop-Tech backend (`ChatController` + `ChatService`) sẽ:
1. Lưu câu hỏi vào bảng `LICH_SU_CHAT`.
2. Resolve `building_code` từ hợp đồng/phòng của cư dân (admin/chủ nhà fallback về tòa đầu tiên).
3. Gọi chatbot `POST http://localhost:8000/api/v1/chat` với `{ building_code, question, sessionId }`.
4. Lưu câu trả lời AI vào `LICH_SU_CHAT`; nếu trùng câu "chưa tìm thấy…" → đánh dấu `IS_KNOWLEDGE_GAP`.

### 4.2. Frontend chủ nhà / BQL (SmartHomeHub) quản lý tri thức

- `/knowledge-base` — xem/thêm/sửa/xóa tri thức, **upload tài liệu** (PDF/DOCX/TXT).
- `/chat-history` — xem hội thoại, xử lý câu hỏi thiếu tri thức (knowledge gap) → "Trả lời và thêm vào KB".

Sau khi upload/sửa tri thức, nếu `Chatbot:AutoIngestOnKnowledgeUpload=true`, Prop-Tech backend tự gọi:
```text
POST http://localhost:8000/api/internal/ingest/rebuild
Header: X-Internal-Api-Key: dev-internal-key
Body: { "rebuild": true }
```
để chatbot rebuild ChromaDB (thay cho việc chạy `ingest_from_db.py` bằng tay).

### 4.3. Cấu hình phía Prop-Tech backend (`appsettings.json`)

```json
"Chatbot": {
  "BaseUrl": "http://localhost:8000",
  "InternalApiKey": "dev-internal-key",
  "AutoIngestOnKnowledgeUpload": true
}
```
- `Chatbot:InternalApiKey` phải khớp `CHATBOT_INTERNAL_API_KEY` của chatbot.
- `PROPTECH_INTERNAL_API_KEY` (phía chatbot) phải khớp `InternalApiKey` của Prop-Tech (bảo vệ endpoint `knowledge-documents`).

---

## 5. Cài đặt & vận hành

### 5.1. Cài môi trường

```powershell
cd D:\Web_TroUyTin\Chatbot\chatbotApp
py -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Dependency chính: `fastapi`, `uvicorn`, `python-dotenv`, `langchain-*` (core/community/chroma/huggingface/groq), `chromadb`, `sentence-transformers`, `rank-bm25`, `requests`.

### 5.2. Biến môi trường (`.env`)

Chatbot Prop-Tech (`app.py`) chỉ cần các biến sau — theo `.env.example`:

```env
# LLM — bắt buộc
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile   # tùy chọn, đây là mặc định

# Nguồn dữ liệu: Prop-Tech backend
PROPTECH_API_BASE_URL=http://localhost:5052
PROPTECH_INTERNAL_API_KEY=dev-internal-key
CHATBOT_INTERNAL_API_KEY=dev-internal-key
```

> Lưu ý: các biến `MYSQL_*` và `GOOGLE_API_KEY` trong file `.env` hiện tại là của phần
> `chatbotWeb/` (TroUyTin), **không** cần cho chatbot Prop-Tech này.

### 5.3. Thứ tự khởi động (end-to-end)

1. Chạy **Prop-Tech backend** (:5052), đảm bảo đọc Supabase thành công.
2. Chạy **ingest** lần đầu: `venv\Scripts\python.exe ingest_from_db.py --rebuild`.
3. Chạy **chatbot**:
   ```powershell
   $env:PYTHONUTF8="1"
   venv\Scripts\python.exe app.py
   ```
4. Mở app mobile / frontend chủ nhà.

Thử nhanh qua Swagger `http://localhost:8000/docs`:
```json
{ "building_code": "2", "question": "Gửi xe máy ở đâu?" }
```

---

## 6. Lưu ý bảo mật

- **Không** đưa `.env` lên Git. Khóa API thật (`GROQ_API_KEY`...) hiện đang bị commit trong `.env` → cần xoay key và gỡ khỏi tracking.
- Chatbot không cần mật khẩu Supabase riêng.
- Nếu internal key bị lộ: đổi `InternalApiKey` ở Prop-Tech và cập nhật `PROPTECH_INTERNAL_API_KEY` + `CHATBOT_INTERNAL_API_KEY` trong `.env` chatbot cho khớp.

---

## 7. Ghi chú trạng thái mã nguồn

- Phần Prop-Tech (`app.py`, `controllers/chatbotAppController.py`, `controllers/ingestController.py`,
  `services/chatbotappService.py`, `ingest_from_db.py`) là **bản chạy được**, đã nối thật với Prop-Tech backend và mobile.
- Thư mục `chatApp/` (kiến trúc PostgreSQL + S3 + document management) hiện **merge thiếu file, chưa chạy được** — không dùng cho vận hành hiện tại.
- Cả `app.py` và các service khác đều mặc định port **8000**; nếu cần chạy nhiều service cùng lúc phải đổi port.
