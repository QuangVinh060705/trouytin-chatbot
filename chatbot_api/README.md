# TroUyTin Chatbot API

## Cấu trúc

```text
chatbot_api/
├── main.py
├── dependencies.py
├── controllers/
│   ├── chatbot_controller.py
│   └── area_controller.py
├── services/
│   ├── chatbot_web_service.py
│   └── area_bot_service.py
├── core/
│   ├── chatbot_trouytin.py
│   └── area_bot.py
└── models/
    ├── chatbot_models.py
    └── area_models.py
```

## Chạy

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Swagger: `http://localhost:8000/docs`

## API

### Chatbot web

`POST /api/chatbot/message`

```json
{
  "session_id": "user-01",
  "message": "Tìm phòng khoảng 5 triệu gần tòa A1"
}
```

`DELETE /api/chatbot/session`

```json
{
  "session_id": "user-01"
}
```

### Area bot

`POST /api/areas/nearby`

```json
{
  "place_name": "Tòa A1",
  "radius_meters": 5000,
  "top_k": 5
}
```
