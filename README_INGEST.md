# Chatbot RAG - Nap du lieu tu Prop-Tech

## Kien truc du lieu

```text
Supabase/Postgres <- Prop-Tech backend :5052 <- ingest_from_db.py -> chroma_db/ <- app.py -> cau tra loi
```

- Chatbot luc chay (`app.py`) khong ket noi DB truc tiep, chi doc `chroma_db/`.
- Script ingest goi Prop-Tech backend qua internal API.
- Prop-Tech backend la noi ket noi Supabase/Postgres va xuat snapshot du lieu cho chatbot.
- `building_code` trong API chat van la `TOA_NHA_ID` dang chuoi, vi du `"2"`.

## Chuan bi

```powershell
cd D:\Web_TroUyTin\Chatbot\chatbotApp
py -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Tao file `.env` tu `.env.example`:

```env
GROQ_API_KEY=
PROPTECH_API_BASE_URL=http://localhost:5052
PROPTECH_INTERNAL_API_KEY=dev-internal-key
CHATBOT_INTERNAL_API_KEY=dev-internal-key
```

`PROPTECH_INTERNAL_API_KEY` phai khop voi `InternalApiKey` cua Prop-Tech backend. Neu Prop-Tech khong set rieng thi mac dinh la `dev-internal-key`.
`CHATBOT_INTERNAL_API_KEY` phai khop voi `Chatbot:InternalApiKey` cua Prop-Tech backend de Prop-Tech co the goi API ingest noi bo.

## Nap du lieu that

Chay Prop-Tech backend truoc, dam bao backend dang doc Supabase thanh cong.

```powershell
cd D:\Web_TroUyTin\Chatbot\chatbotApp
venv\Scripts\python.exe ingest_from_db.py --rebuild
```

Chi nap mot toa nha:

```powershell
venv\Scripts\python.exe ingest_from_db.py --rebuild --building-id 2
```

Script se goi:

```text
GET http://localhost:5052/api/internal/chatbot/knowledge-documents
```

Endpoint nay tra ve tieu su toa nha, lien he BQL, phong, gia thue, dich vu va knowledge base active.

## Chay chatbot

```powershell
$env:PYTHONUTF8="1"
venv\Scripts\python.exe app.py
```

Swagger:

```text
http://localhost:8000/docs
```

Thu nhanh:

```json
{"building_code": "2", "question": "Gia thue phong the nao?"}
```

## Ket noi voi app cu dan va frontend chu nha

App cu dan/mobile khong goi truc tiep Chatbot API. App goi Prop-Tech backend:

```text
POST http://localhost:5052/api/Chat/send
```

Prop-Tech backend se:

1. Luu cau hoi vao `LICH_SU_CHAT`.
2. Tim toa nha cua cu dan tu hop dong/phong hien tai.
3. Goi Chatbot API `POST http://localhost:8000/api/v1/chat` voi `building_code`.
4. Luu cau tra loi AI vao `LICH_SU_CHAT`.

Frontend chu nha/BQL dung:

```text
/knowledge-base  - them/sua/upload tri thuc
/chat-history    - xem hoi thoai va xu ly cau hoi thieu tri thuc
```

Sau khi chu nha/BQL upload tai lieu, Prop-Tech backend se goi API noi bo cua Chatbot de rebuild ChromaDB neu `Chatbot:AutoIngestOnKnowledgeUpload=true`.

API noi bo:

```text
POST http://localhost:8000/api/internal/ingest/rebuild
Header: X-Internal-Api-Key: dev-internal-key
Body: {"rebuild": true}
```

Neu can chay lai thu cong:

```powershell
venv\Scripts\python.exe ingest_from_db.py --rebuild
```

## Cap nhat du lieu ve sau

Moi khi du lieu toa nha, phong, dich vu hoac knowledge base trong Prop-Tech thay doi, chay lai:

```powershell
venv\Scripts\python.exe ingest_from_db.py --rebuild
```

## Luu y bao mat

- Khong dua `.env` len Git.
- Chatbot khong can Supabase password rieng.
- Neu internal key bi lo, doi `InternalApiKey` o Prop-Tech va cap nhat `PROPTECH_INTERNAL_API_KEY` trong `.env` chatbot.
