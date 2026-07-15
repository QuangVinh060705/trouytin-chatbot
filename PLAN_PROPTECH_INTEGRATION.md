# Plan ket noi Chatbot voi Prop-Tech

## Muc tieu

- App cu dan mobile hoi chatbot qua Prop-Tech backend `/api/Chat/send`.
- Prop-Tech backend lay dung `building_code` tu toa nha/phong cua cu dan.
- Prop-Tech backend goi Chatbot RAG local `/api/v1/chat`.
- Chu nha/BQL quan ly tri thuc trong Prop-Tech frontend qua `/knowledge-base` va `/chat-history`.
- Script ingest lay du lieu tu Prop-Tech/Supabase qua internal API roi ghi vao `chroma_db`.

## Tinh nang chatbot hien co

- Hoi dap RAG theo toa nha bang `building_code`.
- Hybrid search: vector ChromaDB + BM25.
- Rewrite cau hoi bang Groq de tang kha nang truy van.
- Luu lich su chat trong Prop-Tech DB qua `LICH_SU_CHAT`.
- Danh dau cau hoi thieu tri thuc bang `IS_KNOWLEDGE_GAP`.
- Chu nha/BQL xem hoi thoai va them cau tra loi vao `KNOWLEDGE_BASE`.
- Ingest du lieu toa nha, phong, gia thue, dich vu, lien he BQL, knowledge base vao ChromaDB.

## Task thuc hien

1. Prop-Tech backend them config `Chatbot:BaseUrl`.
2. `ChatService` resolve `building_code` theo user:
   - Cu dan: lay hop dong/chi tiet o hien tai -> phong -> toa nha.
   - Chu nha/admin: fallback ve toa nha dau tien thuoc owner.
3. `ChatService` goi Chatbot RAG local thay cho n8n.
4. Neu Chatbot khong chay hoac khong co du lieu, luu assistant message dang knowledge gap.
5. Cap nhat frontend chu nha khong con noi "n8n", upload tai lieu luu vao Prop-Tech `KNOWLEDGE_BASE`.
6. Cap nhat docs/env de chay 3 service: Prop-Tech backend, Chatbot API, mobile/frontend.

## Cach van hanh

1. Chay Prop-Tech backend ket noi Supabase.
2. Chay ingest:
   `venv\Scripts\python.exe ingest_from_db.py --rebuild`
3. Chay Chatbot API:
   `venv\Scripts\python.exe app.py`
4. Chay app mobile/front-end.
5. Khi chu nha cap nhat kho tri thuc, chay lai ingest de chatbot dung du lieu moi.
