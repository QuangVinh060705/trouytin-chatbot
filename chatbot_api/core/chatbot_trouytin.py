import os
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import List, Optional

from dotenv import load_dotenv
from rapidfuzz import process, fuzz
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from langchain_groq import ChatGroq

# IMPORT thuật toán tìm khoảng cách của bạn (Giả sử file cũ tên là area_bot.py)
from .area_bot import AreaRecommendationBot
from .database import create_database_engine, get_database_schema

load_dotenv()

# Thư mục gốc của project (chatbot_api/), dùng để mở file dữ liệu kèm theo code
# bằng đường dẫn TUYỆT ĐỐI thay vì phụ thuộc thư mục làm việc hiện tại.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- CÁC PYDANTIC MODELS ---
# LƯU Ý: Bot xử lý MỖI tin nhắn ĐỘC LẬP (1-1), không cộng dồn tiêu chí giữa
# các lượt chat, nên search_intent chỉ cần phản ánh đúng nội dung của riêng
# tin nhắn hiện tại.
class SearchIntent(BaseModel):
    gia_min: int | None = Field(
        default=None,
        description=(
            "Giá thuê tối thiểu khách yêu cầu (VND). CHỈ điền trường này khi khách "
            "dùng từ chỉ CẬN DƯỚI: 'trên X', 'hơn X', 'từ X trở lên', 'tối thiểu X', "
            "'ít nhất X'. Quy đổi các từ viết tắt như '3t', '3tr', '3 triệu' thành số "
            "nguyên: 3000000."
        ),
    )
    gia_max: int | None = Field(
        default=None,
        description=(
            "Giá thuê tối đa khách yêu cầu (VND). Điền trường này khi khách dùng từ "
            "chỉ CẬN TRÊN: 'dưới X', 'không quá X', 'tối đa X', 'kém hơn X', HOẶC khi "
            "khách chỉ nêu một mức giá mà KHÔNG kèm từ định hướng nào (ngầm hiểu là "
            "mức giá tối đa mong muốn). Quy đổi các từ viết tắt như '3t', '3tr', "
            "'3 triệu' thành số nguyên: 3000000."
        ),
    )
    so_nguoi: int | None = Field(default=None, description="Số lượng người ở tối đa hoặc số người muốn thuê.")
    dien_tich_min: float | None = Field(default=None, description="Diện tích tối thiểu (m2).")
    loai_phong: str | None = Field(default=None, description="Loại vật lý của phòng (STUDIO, PHONG_TRO, 1K1N, 2K1N, ...). Không dùng cho nhu cầu ở ghép.")
    is_shared: bool | None = Field(
        default=None,
        description="True khi người dùng muốn tìm phòng/bài đăng ở ghép, ở chung, share phòng hoặc roommate.",
    )
    dia_chi: str | None = Field(default=None, description="Tên tòa nhà cụ thể, tên đường hoặc tên khu vực/quận huyện muốn thuê phòng.")

    tien_nghi: List[str] = Field(default_factory=list, description="Danh sách tiện nghi khách yêu cầu trong tin nhắn này (VD: 'Điều hòa', 'Mạng'). Nếu không có, trả về mảng rỗng [].")
    dich_vu: List[str] = Field(default_factory=list, description="Danh sách dịch vụ khách yêu cầu trong tin nhắn này. Nếu không có, trả về mảng rỗng [].")

    @field_validator("tien_nghi", "dich_vu", mode="before")
    @classmethod
    def _null_to_empty_list(cls, value):
        """LLM (nhất là openai/gpt-oss-20b) hay trả null thay vì [] cho hai
        trường mảng này, khiến Pydantic từ chối cả câu trả lời và request hỏng
        dù mọi trường khác đã đúng. Quy null về [] ngay ở bước validate."""
        return [] if value is None else value

class BotResponse(BaseModel):
    is_off_topic: bool = Field(description="True nếu tin nhắn KHÔNG liên quan đến phòng trọ, thuê nhà, nội quy.")
    is_qa: bool = Field(description="True nếu người dùng hỏi đáp thông tin, nội quy dựa trên Knowledge Base.")
    is_search: bool = Field(description="True nếu người dùng muốn tìm phòng hoặc thay đổi tiêu chí tìm kiếm.")
    reply_message: str | None = Field(default=None, description="Câu trả lời phản hồi trực tiếp (có thể để trống ở bước này).")
    search_intent: Optional[SearchIntent] = Field(default=None, description="Trích xuất điều kiện lọc nếu is_search = True")


# --- LỚP CHÍNH CỦA CHATBOT ---
class RealEstateBot:
    def __init__(self, area_bot: AreaRecommendationBot | None = None):
        # 1. Khởi tạo Database Engine
        self.engine = create_database_engine()
        self.schema = get_database_schema()
        
        # 2. Khởi tạo LLM
        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            temperature=0.1
        )
        # method="json_schema" thay vì mặc định "function_calling".
        #
        # openai/gpt-oss-20b KHÔNG dùng được function_calling ở đây: model trả
        # markdown ```json thay vì gọi tool ("model did not call a tool"), đặt
        # tên tool là "functions.BotResponse" khiến langchain không khớp được,
        # và emit null cho các trường mảng -> Groq trả 400 tool_use_failed.
        # Đo thực tế: function_calling 0/5 ca, json_schema 5/5.
        #
        # Nếu đổi sang model khác qua GROQ_MODEL mà model đó không hỗ trợ
        # json_schema thì đổi lại thành "function_calling".
        self.structured_llm = self.llm.with_structured_output(
            BotResponse,
            method=os.getenv("GROQ_STRUCTURED_OUTPUT_METHOD", "json_schema"),
        )
        
        # 3. Khởi tạo Area Bot
        self.area_bot = area_bot or AreaRecommendationBot(engine=self.engine, schema=self.schema)
        
        # 4. Load Master Data & Knowledge base
        self.MASTER = self._load_master_data()
        self.kb_content = self._load_kb()
        
        # --- PROMPT 1: INTENT EXTRACTION ---
        self.PROMPT_1_EXTRACTION = """
        Bạn là AI phân tích và trích xuất thực thể cấu trúc (Entity Extraction) từ tin nhắn của khách hàng thuê phòng trọ.
        Nhiệm vụ của bạn là đọc hiểu ngôn ngữ tự nhiên và chuyển đổi chính xác thành cấu trúc dữ liệu định dạng JSON.

        [QUY TẮC BẮT BUỘC TRÍCH XUẤT]:
        0. [QUAN TRỌNG NHẤT] Mỗi tin nhắn được xử lý HOÀN TOÀN ĐỘC LẬP — KHÔNG có bộ nhớ hội thoại,
           KHÔNG cộng dồn tiêu chí với các lượt chat trước. CHỈ được trích xuất đúng những gì tin nhắn
           HIỆN TẠI nêu ra; mọi trường không được nhắc tới trong tin nhắn hiện tại PHẢI để trống (null/[]),
           TUYỆT ĐỐI không suy diễn từ ngữ cảnh trước đó.
        1. Tuyệt đối KHÔNG bỏ sót thông tin về giá tiền trong tin nhắn hiện tại. Quy đổi toàn bộ các từ viết tắt ('3t', '3tr', '8tr') sang số nguyên đầy đủ (Ví dụ: 3000000, 8000000).
           - PHẢI xác định đúng CHIỀU của mức giá dựa trên từ khóa đi kèm, TUYỆT ĐỐI không mặc định nhét mọi con số vào 'gia_max':
             + Từ chỉ CẬN DƯỚI ("trên X", "hơn X", "từ X trở lên", "tối thiểu X", "ít nhất X") => điền vào 'gia_min'.
             + Từ chỉ CẬN TRÊN ("dưới X", "không quá X", "tối đa X", "kém hơn X") hoặc khi khách CHỈ nêu một mức giá mà KHÔNG có từ định hướng nào => điền vào 'gia_max'.
             + Khoảng giá ("từ X đến Y", "X - Y") => điền cả 'gia_min' = X và 'gia_max' = Y.
        2. Trường 'dia_chi' chỉ lưu danh từ riêng đại diện cho địa điểm, khu vực hoặc tòa nhà (Ví dụ: "Hai Bà Trưng", "Thanh Xuân"). Giữ nguyên chính tả khách gõ, KHÔNG tự ý sửa/đoán thành tên gần giống.
        3. Phân loại chuẩn xác: Off-topic => is_off_topic = True; Hỏi nội quy => is_qa = True; Tìm kiếm phòng => is_search = True.
        4. Chào hỏi/xã giao (ví dụ: "hi", "hello", "xin chào") KHÔNG phải tìm kiếm: is_search = False.
        5. Các câu như "có những phòng nào", "xem tất cả phòng", "tìm lại", "còn phòng nào khác" vẫn là
           is_search = True nhưng KHÔNG nêu tiêu chí gì cả — cứ để mọi trường của search_intent trống,
           hệ thống sẽ tự trả về toàn bộ phòng còn trống.
        6. "Ở ghép", "phòng ghép", "ở chung", "share phòng", "roommate" KHÔNG phải loại phòng vật lý.
           Với các câu này phải đặt search_intent.is_shared = true và search_intent.loai_phong = null.
        7. Chỉ điền loai_phong cho loại phòng vật lý như STUDIO, PHONG_TRO, 1K1N, 2K1N.

        [KNOWLEDGE BASE]
        {kb_context}
        """
        
        # --- PROMPT 2: CUSTOMER SERVICE (ĐÃ CHUẨN HÓA THEO THIẾT KẾ CỦA BẠN) ---
        self.PROMPT_2_CS = """
        Bạn là AI Tư vấn Phòng trọ thông minh, nhiệt tình và thân thiện.
        Nhiệm vụ của bạn là dựa vào Thông tin hệ thống cung cấp dưới đây để phản hồi tin nhắn của khách hàng bằng ngôn ngữ tự nhiên.
        
        [TIN NHẮN CỦA KHÁCH]: "{user_input}"

        [PHÂN LOẠI Ý ĐỊNH]:
        - is_off_topic: {is_off_topic}
        - is_qa: {is_qa}
        - is_search: {is_search}
        - reply_message từ bước phân tích: {reply_message}

        [CÂU XÁC NHẬN BẮT BUỘC - ĐÃ TÍNH SẴN, KHÔNG ĐƯỢC TỰ SUY DIỄN LẠI]:
        {opening_line}

        [SỐ LƯỢNG PHÒNG THỰC TẾ TÌM THẤY]: {result_count}

        [KẾT QUẢ TÌM KIẾM SQL TỪ HỆ THỐNG]:
        {sql_results}
        
        [QUAN TRỌNG - QUY TẮC TUÂN THỦ KIẾN TRÚC]:
        0. Nếu is_search = False, KHÔNG được nói "không tìm thấy phòng" vì hệ thống không hề chạy tìm kiếm.
           - Với lời chào/xã giao: trả lời ngắn gọn, thân thiện và hỏi nhu cầu.
           - Với câu hỏi kiến thức/nội quy: trả lời theo Knowledge Base.
           - Chỉ nhận xét có/không có phòng khi is_search = True.
        1. VỀ PHẠM VI ĐỊA LÝ: AreaRecommendationBot đã làm xong nhiệm vụ xác định danh sách các tòa nhà được phép tìm kiếm dựa trên vị trí khách hàng gõ. Nó không đánh giá chất lượng phòng.
        2. VỀ QUYỀN QUYẾT ĐỊNH: Danh sách phòng nằm trong [KẾT QUẢ TÌM KIẾM SQL] là kết quả chính thức đã được hệ thống chấm MATCH_SCORE (Điểm phù hợp) dựa trên các tiêu chí Giá, Diện tích, Số người, Tiện nghi.
        3. KHÔNG ĐƯỢC OVER-STEP (VƯỢT QUYỀN): 
           - Bạn tuyệt đối KHÔNG ĐƯỢC tự ý đánh giá lại, không tự loại bỏ phòng dựa trên cảm tính hoặc suy luận địa lý (Ví dụ: Không được phép nói "phòng này ở Đống Đa nên không phù hợp" hay "khách tìm Cầu Giấy nên phòng này không nên giới thiệu").
           - Nếu SQL trả về phòng, hãy coi đó là các phòng lân cận phù hợp nhất và giới thiệu nhiệt tình cho khách.
           - CHỈ thông báo không tìm thấy phòng khi và chỉ khi [KẾT QUẢ TÌM KIẾM SQL] thực sự trả về mảng rỗng hoặc thông báo trống.
        4. VỀ GIÁ:
           - Mọi mức giá phải lấy đúng tuyệt đối từ trường "gia_thue".
           - Không được làm tròn, ước lượng hoặc thay giá của phòng này bằng phòng khác.
           - Nếu gia_thue = 666667 thì phải đọc là 666.667 đồng, tuyệt đối không được nói 4 triệu.
        5. VỀ CÂU XÁC NHẬN TIÊU CHÍ (RẤT QUAN TRỌNG):
           - Khi is_search = True, câu trả lời BẮT BUỘC phải mở đầu bằng nội dung tương đương [CÂU XÁC NHẬN BẮT BUỘC] ở trên (có thể diễn đạt lại cho tự nhiên, nhưng PHẢI giữ nguyên đầy đủ mọi tiêu chí và con số phòng nêu trong đó).
           - TUYỆT ĐỐI KHÔNG được tự thêm, bớt, hoặc đổi bất kỳ tiêu chí nào không có trong câu xác nhận đó.
           - [SỐ LƯỢNG PHÒNG THỰC TẾ TÌM THẤY] là con số DUY NHẤT đáng tin cậy. Nếu con số này > 0, câu trả lời TUYỆT ĐỐI không được nói "không tìm thấy phòng nào". Nếu con số này = 0, câu trả lời TUYỆT ĐỐI không được liệt kê phòng nào cả.
        """
        
    @staticmethod
    def _empty_filter_state() -> dict:
        """Bộ lọc rỗng dùng cho MỖI tin nhắn — chatbot xử lý độc lập theo
        từng câu hỏi (1-1), KHÔNG lưu/nhớ tiêu chí giữa các lượt chat."""
        return {
            "gia_min": None, "gia_max": None, "so_nguoi": None,
            "dien_tich_min": None, "loai_phong": None, "is_shared": None, "dia_chi": None,
            "tien_nghi": [], "dich_vu": [], "nearby_buildings": [], "matched_buildings": [],
            "area_query": None,
        }

    @staticmethod
    def _format_vnd(amount: int) -> str:
        return f"{int(amount):,}".replace(",", ".") + "đ"

    def _build_filter_summary(self, state: dict) -> str:
        """Tổng hợp các tiêu chí tìm kiếm ĐANG ÁP DỤNG (tích lũy qua các lượt
        chat) thành một câu tiếng Việt tự nhiên, tính toán 100% bằng code chứ
        không giao cho LLM tự suy luận lại — tránh việc LLM bịa/thiếu tiêu chí
        hoặc mâu thuẫn với state thực tế.
        """
        parts = []

        gia_min, gia_max = state.get("gia_min"), state.get("gia_max")
        if gia_min is not None and gia_max is not None:
            parts.append(f"giá từ {self._format_vnd(gia_min)} đến {self._format_vnd(gia_max)}")
        elif gia_max is not None:
            parts.append(f"giá dưới {self._format_vnd(gia_max)}")
        elif gia_min is not None:
            parts.append(f"giá từ {self._format_vnd(gia_min)} trở lên")

        if state.get("so_nguoi") is not None:
            parts.append(f"ở được tối đa {state['so_nguoi']} người")

        if state.get("dien_tich_min") is not None:
            parts.append(f"diện tích từ {state['dien_tich_min']}m² trở lên")

        if state.get("loai_phong"):
            parts.append(f"loại phòng {state['loai_phong']}")

        if state.get("is_shared") is True:
            parts.append("hình thức ở ghép")

        if state.get("dia_chi"):
            parts.append(f"khu vực {state['dia_chi']}")

        if state.get("tien_nghi"):
            parts.append(f"tiện nghi: {', '.join(state['tien_nghi'])}")

        if state.get("dich_vu"):
            parts.append(f"dịch vụ: {', '.join(state['dich_vu'])}")

        if not parts:
            return ""

        return ", ".join(parts)

    def _build_opening_line(self, filter_summary: str, result_count: int) -> str:
        """Câu mở đầu bắt buộc, tính sẵn bằng code dựa trên state + số lượng
        kết quả SQL thực tế, để Prompt 2 không thể tự mâu thuẫn với dữ liệu."""
        if filter_summary:
            if result_count > 0:
                return (
                    f"Với yêu cầu {filter_summary}, hệ thống tìm thấy "
                    f"{result_count} phòng phù hợp:"
                )
            return f"Với yêu cầu {filter_summary}, hiện chưa tìm thấy phòng nào phù hợp."
        if result_count > 0:
            return f"Hệ thống tìm thấy {result_count} phòng phù hợp:"
        return "Hiện chưa tìm thấy phòng nào phù hợp."

    def _load_kb(self):
        # Đường dẫn TUYỆT ĐỐI theo vị trí file code. Trước đây dùng đường dẫn
        # tương đối "knowledge_base.json" nên chỉ nạp được khi uvicorn được
        # chạy đúng từ thư mục chatbot_api/; chạy từ chỗ khác là im lặng rơi
        # về chuỗi fallback và nhánh is_qa mất toàn bộ kiến thức.
        kb_path = BASE_DIR / "knowledge_base.json"
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                return json.dumps(json.load(f), ensure_ascii=False, indent=2)
        except FileNotFoundError:
            print(f"[CẢNH BÁO] Không tìm thấy knowledge_base.json tại {kb_path}")
            return "Nội quy: Giờ giấc tự do. Nuôi thú cưng nhỏ cho phép."
        except json.JSONDecodeError as exc:
            print(f"[CẢNH BÁO] knowledge_base.json không phải JSON hợp lệ: {exc}")
            return "Nội quy: Giờ giấc tự do. Nuôi thú cưng nhỏ cho phép."

    def _load_master_data(self):
        room_types, amenities, services = set(), set(), set()
        sql_room_types = text('SELECT DISTINCT "LOAI_PHONG" FROM "PHONG"')
        sql_amenities = text('SELECT "TIEN_NGHI_JSON" FROM "PHONG"')
        sql_services = text('SELECT "DICH_VU_JSON" FROM "PHONG"')

        with self.engine.connect() as conn:
            for row in conn.execute(sql_room_types):
                if row[0]:
                    room_types.add(row[0])

            for row in conn.execute(sql_amenities):
                if not row[0]:
                    continue
                try:
                    data = row[0] if isinstance(row[0], list) else json.loads(row[0])
                    if isinstance(data, list):
                        amenities.update(data)
                except (TypeError, json.JSONDecodeError):
                    pass

            for row in conn.execute(sql_services):
                if not row[0]:
                    continue
                try:
                    data = row[0] if isinstance(row[0], list) else json.loads(row[0])
                    if isinstance(data, list):
                        services.update(data)
                except (TypeError, json.JSONDecodeError):
                    pass

        return {
            "room_types": sorted(room_types),
            "amenities": sorted(amenities),
            "services": sorted(services),
        }

    def _normalize_term(self, term: str):
        SYNONYMS = {"máy lạnh": "Điều hòa", "tv": "Smart TV", "wifi": "Mạng", "studio": "STUDIO"}
        term = term.lower().strip()
        return SYNONYMS.get(term, term)

    def _best_match(self, value, choices, threshold=55):
        if not value: return None
        result = process.extractOne(value, choices, scorer=fuzz.token_sort_ratio)
        if not result: return None
        match, score, _ = result
        return match if score >= threshold else None

    def _load_public_rooms(self) -> list[dict]:
        """Lấy danh sách public listing mà trang chi tiết thực sự chấp nhận."""
        base_url = os.getenv(
            "TROUYTIN_API_BASE_URL",
            "http://localhost:8090",
        ).rstrip("/")
        request = Request(
            f"{base_url}/api/listings",
            headers={"Accept": "application/json"},
        )
        timeout_seconds = float(os.getenv("TROUYTIN_API_TIMEOUT_SECONDS", "10"))

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                public_rooms = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            # Endpoint này thuộc TroUyTin backend (TROUYTIN_API_BASE_URL, :8090),
            # KHÔNG phải Prop-Tech (:5052). Ghi đúng tên service để khi đọc log
            # không đi kiểm tra sai chỗ.
            raise RuntimeError(
                f"Không thể lấy public listing ID từ TroUyTin ({base_url})."
            ) from exc

        if not isinstance(public_rooms, list):
            raise RuntimeError("TroUyTin trả về danh sách phòng public không hợp lệ.")

        return [item for item in public_rooms if isinstance(item, dict)]

    def _load_public_room_map(self) -> dict[int, dict]:
        public_rooms = self._load_public_rooms()
        room_map: dict[int, dict] = {}
        for public_room in public_rooms:
            if not isinstance(public_room, dict):
                continue
            try:
                room_id = int(public_room["roomId"])
            except (KeyError, TypeError, ValueError):
                continue

            public_id = public_room.get("id")
            if not isinstance(public_id, str) or not public_id.strip():
                continue

            # This public endpoint exposes only listings whose IDs are accepted
            # by GET /api/listings/{id}, so every generated detailRoute works.
            room_map.setdefault(room_id, public_room)

        return room_map

    @staticmethod
    def _format_public_room(room, public_room: dict) -> dict:
        room_id = int(room["PHONG_ID"])
        public_id = str(public_room["id"]).strip()
        images = public_room.get("images")
        thumbnail_url = (
            next(
                (
                    image
                    for image in images
                    if isinstance(image, str) and image.strip()
                ),
                None,
            )
            if isinstance(images, list)
            else None
        )

        return {
            "id": public_id,
            "roomId": room_id,
            "roomCode": str(room["MA_PHONG"]),
            "roomName": str(
                public_room.get("title") or f"Phòng {room['MA_PHONG']}"
            ),
            "buildingName": str(room["TEN_TOA_NHA"]),
            # Giá hiển thị phải lấy từ public listing vì bài đăng có thể
            # có giá khác DON_GIA_THUE_MAC_DINH của phòng gốc.
            "price": int(
                public_room.get("price")
                if public_room.get("price") is not None
                else (room["DON_GIA_THUE_MAC_DINH"] or 0)
            ),
            "thumbnailUrl": thumbnail_url,
            "detailRoute": f"/rooms/{public_id}",
            "matchScore": int(room["MATCH_SCORE"]),
            "roomType": str(
                public_room.get("roomType") or room["LOAI_PHONG"]
            ),
            "status": str(
                public_room.get("roomStatus") or room["TRANG_THAI"]
            ),
            "address": str(
                public_room.get("location") or room["DIA_CHI"] or ""
            ),
        }


    def _shared_search(self, intent_data: dict):
        """Tìm bài đăng ở ghép; không dùng PHONG.LOAI_PHONG để suy ra ở ghép."""
        sql = """
        SELECT
            bd.*,
            u."VAI_TRO",
            p."PHONG_ID",
            p."MA_PHONG",
            p."LOAI_PHONG",
            p."DON_GIA_THUE_MAC_DINH",
            p."TRANG_THAI",
            tn."TEN_TOA_NHA",
            tn."DIA_CHI",
            GREATEST(
                COALESCE(bd."SO_NGUOI_TOI_DA", 0)
                - COALESCE(bd."SO_NGUOI_DANG_O", 0),
                0
            ) AS "AVAILABLE_SLOTS",
            100 AS "MATCH_SCORE"
        FROM "BAI_DANG_TIM_PHONG" bd
        LEFT JOIN "USER" u ON u."USER_ID" = bd."TAO_BOI_ID"
        LEFT JOIN "PHONG" p ON p."PHONG_ID" = bd."PHONG_ID"
        LEFT JOIN "TANG" t ON t."TANG_ID" = p."TANG_ID"
        LEFT JOIN "TOA_NHA" tn ON tn."TOA_NHA_ID" = t."TOA_NHA_ID"
        WHERE (
            LOWER(BTRIM(COALESCE(u."VAI_TRO", ''))) = LOWER('CuDan')
            OR COALESCE(bd."SO_NGUOI_DANG_O", 0) > 0
        )
          AND COALESCE(bd."SO_NGUOI_TOI_DA", 0)
              > COALESCE(bd."SO_NGUOI_DANG_O", 0)
        """
        params = {}

        area_query = intent_data.get("area_query") or intent_data.get("dia_chi")
        if area_query:
            sql += ' AND (tn."DIA_CHI" ILIKE :area_query OR tn."TEN_TOA_NHA" ILIKE :area_query)'
            params["area_query"] = f"%{area_query}%"

        # Nếu schema của bạn dùng tên cột giá khác GIA_THUE, đổi đúng tên tại đây.
        if intent_data.get("gia_max") is not None:
            sql += ' AND COALESCE(bd."GIA_THUE", p."DON_GIA_THUE_MAC_DINH") <= CAST(:gia_max AS NUMERIC)'
            params["gia_max"] = int(intent_data["gia_max"])
        if intent_data.get("gia_min") is not None:
            sql += ' AND COALESCE(bd."GIA_THUE", p."DON_GIA_THUE_MAC_DINH") >= CAST(:gia_min AS NUMERIC)'
            params["gia_min"] = int(intent_data["gia_min"])

        sql += """
        ORDER BY "AVAILABLE_SLOTS" DESC,
                 COALESCE(bd."GIA_THUE", p."DON_GIA_THUE_MAC_DINH") ASC
        LIMIT 5
        """

        print("\n=== [DEBUG] SHARED ROOM SEARCH ===")
        print("is_shared: true")
        print("source: BAI_DANG_TIM_PHONG")
        print(sql)
        print("Parameters:", params)

        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).mappings().all()

    @staticmethod
    def _format_shared_room(row, public_room: dict) -> dict:
        public_id = str(public_room["id"]).strip()
        current_occupants = int(row.get("SO_NGUOI_DANG_O") or 0)
        max_occupants = int(row.get("SO_NGUOI_TOI_DA") or 0)
        available_slots = max(max_occupants - current_occupants, 0)

        raw_price = public_room.get("price")
        if raw_price is None:
            raw_price = row.get("GIA_THUE")
        if raw_price is None:
            raw_price = row.get("DON_GIA_THUE_MAC_DINH")
        price = int(raw_price or 0)

        images = public_room.get("images")
        thumbnail_url = (
            next((x for x in images if isinstance(x, str) and x.strip()), None)
            if isinstance(images, list)
            else None
        )

        return {
            "id": public_id,
            "postId": row.get("BAI_DANG_ID"),
            "roomId": row.get("PHONG_ID"),
            "roomCode": str(row.get("MA_PHONG") or ""),
            "roomName": str(public_room.get("title") or "Bài đăng ở ghép"),
            "buildingName": str(row.get("TEN_TOA_NHA") or ""),
            "price": price,
            "gia_thue": price,
            "currentOccupants": current_occupants,
            "maxOccupants": max_occupants,
            "availableSlots": available_slots,
            "isShared": True,
            "thumbnailUrl": thumbnail_url,
            "detailRoute": f"/rooms/{public_id}",
            "matchScore": int(row.get("MATCH_SCORE") or 100),
            "roomType": str(public_room.get("roomType") or row.get("LOAI_PHONG") or ""),
            "status": str(public_room.get("roomStatus") or row.get("TRANG_THAI") or ""),
            "address": str(public_room.get("location") or row.get("DIA_CHI") or ""),
            "ma_phong": str(row.get("MA_PHONG") or ""),
            "diem_phu_hop": int(row.get("MATCH_SCORE") or 100),
            "loai_phong": str(row.get("LOAI_PHONG") or "Ở ghép"),
            "toa_nha": str(row.get("TEN_TOA_NHA") or ""),
            "dia_chi": str(row.get("DIA_CHI") or ""),
        }

    def _build_deterministic_search_message(
        self,
        opening_line: str,
        rooms: list[dict],
        matched_buildings: list[str] | None = None,
    ) -> str:
        """Sinh message bằng code để LLM không thể đổi sai giá."""
        if not rooms:
            return opening_line

        matched_buildings = matched_buildings or []

        lines = [opening_line]
        for room in rooms:
            name = room.get("roomName") or room.get("ma_phong") or "Phòng"
            price = self._format_vnd(int(room.get("gia_thue") or room.get("price") or 0))
            address = room.get("address") or room.get("dia_chi") or ""
            building = room.get("buildingName") or room.get("toa_nha") or ""
            # Luôn nêu rõ phòng thuộc tòa nào, và đánh dấu "lân cận" khi đây
            # không phải tòa khách hỏi trực tiếp -> khách không hiểu nhầm giá
            # của tòa lân cận là giá của tòa họ hỏi.
            building_note = ""
            if building:
                if matched_buildings and building not in matched_buildings:
                    building_note = f" (tòa {building}, lân cận)"
                else:
                    building_note = f" (tòa {building})"
            if room.get("isShared"):
                lines.append(
                    f"- {name}{building_note}: {room.get('currentOccupants', 0)}/"
                    f"{room.get('maxOccupants', 0)} người, còn "
                    f"{room.get('availableSlots', 0)} chỗ, giá {price}"
                    + (f", địa chỉ {address}." if address else ".")
                )
            else:
                lines.append(
                    f"- {name}{building_note}, giá {price}"
                    + (f", địa chỉ {address}." if address else ".")
                )
        return "\n".join(lines)

    # --- HÀM TÌM KIẾM SQL (ĐÃ LOẠI BỎ ĐIỂM VỊ TRÍ TRÙNG LẶP) ---
    def _unified_search(self, intent_data: dict):
        params = {
            "gia_min": intent_data.get("gia_min"),
            "gia_max": intent_data.get("gia_max"),
            "so_nguoi": intent_data.get("so_nguoi"),
            "dien_tich_min": intent_data.get("dien_tich_min"),
            "loai_phong": intent_data.get("loai_phong"),
        }

        # Tòa nhà khách hỏi TRỰC TIẾP (không phải chỉ "lân cận") phải luôn
        # được ưu tiên xếp lên trước, nếu không các tòa lân cận có giá rẻ
        # hơn sẽ chiếm hết chỗ trong LIMIT và khách sẽ không thấy phòng của
        # đúng tòa họ hỏi -> hiểu nhầm là "chatbot trả sai giá của tòa này".
        matched_buildings = intent_data.get("matched_buildings", [])
        building_priority_expr = "0"
        if matched_buildings:
            mb_placeholders = [f":mb{i}" for i in range(len(matched_buildings))]
            building_priority_expr = (
                f'CASE WHEN tn."TEN_TOA_NHA" IN ({", ".join(mb_placeholders)}) '
                "THEN 1 ELSE 0 END"
            )
            for i, building_name in enumerate(matched_buildings):
                params[f"mb{i}"] = building_name

        sql = f"""
        WITH ranked_rooms AS (
            SELECT
                p.*,
                tn."TEN_TOA_NHA",
                tn."DIA_CHI",
                ({building_priority_expr}) AS "BUILDING_PRIORITY",
                (
                    CASE
                        WHEN CAST(:gia_min AS NUMERIC) IS NULL
                             AND CAST(:gia_max AS NUMERIC) IS NULL THEN 30
                        WHEN CAST(:gia_min AS NUMERIC) IS NOT NULL
                             AND p."DON_GIA_THUE_MAC_DINH" < CAST(:gia_min AS NUMERIC) THEN 10
                        WHEN CAST(:gia_max AS NUMERIC) IS NULL THEN 30
                        WHEN p."DON_GIA_THUE_MAC_DINH" <= CAST(:gia_max AS NUMERIC) THEN 30
                        WHEN p."DON_GIA_THUE_MAC_DINH" - CAST(:gia_max AS NUMERIC) <= 1000000 THEN 20
                        ELSE 0
                    END +
                    CASE
                        WHEN CAST(:so_nguoi AS INTEGER) IS NULL THEN 25
                        WHEN p."SO_NGUOI_TOI_DA" >= CAST(:so_nguoi AS INTEGER) THEN 25
                        ELSE 0
                    END +
                    CASE
                        WHEN CAST(:dien_tich_min AS NUMERIC) IS NULL THEN 20
                        WHEN p."DIEN_TICH" >= CAST(:dien_tich_min AS NUMERIC) THEN 20
                        WHEN CAST(:dien_tich_min AS NUMERIC) - p."DIEN_TICH" <= 5 THEN 10
                        ELSE 0
                    END +
                    CASE
                        WHEN CAST(:loai_phong AS VARCHAR) IS NULL THEN 25
                        WHEN LOWER(p."LOAI_PHONG") = LOWER(CAST(:loai_phong AS VARCHAR)) THEN 25
                        ELSE 0
                    END
                ) AS "MATCH_SCORE"
            FROM "PHONG" p
            JOIN "TANG" t ON p."TANG_ID" = t."TANG_ID"
            JOIN "TOA_NHA" tn ON t."TOA_NHA_ID" = tn."TOA_NHA_ID"
            WHERE LOWER(BTRIM(p."TRANG_THAI")) = LOWER('Trống')
              AND COALESCE(t."IS_DELETED", FALSE) = FALSE
              AND COALESCE(tn."IS_DELETED", FALSE) = FALSE
        """

        nearby_buildings = intent_data.get("nearby_buildings", [])
        area_query = intent_data.get("area_query")

        if nearby_buildings:
            # AreaBot đã tự tin match được tòa/khu vực -> lọc chính xác theo
            # danh sách tòa (gốc + lân cận) đã xác định.
            placeholders = [f":b{i}" for i in range(len(nearby_buildings))]
            sql += f' AND tn."TEN_TOA_NHA" IN ({", ".join(placeholders)})'
            for i, building_name in enumerate(nearby_buildings):
                params[f"b{i}"] = building_name
        elif area_query:
            # AreaBot KHÔNG match được tòa cụ thể nào -> không được ép so
            # khớp tuyệt đối bằng chuỗi thô (luôn fail). Thay vào đó lọc gần
            # đúng theo địa chỉ/tên tòa để vẫn còn cơ hội tìm ra kết quả thật
            # sự có trong DB.
            sql += ' AND (tn."DIA_CHI" ILIKE :area_query OR tn."TEN_TOA_NHA" ILIKE :area_query)'
            params["area_query"] = f"%{area_query}%"

        if intent_data.get("gia_max") is not None:
            sql += ' AND p."DON_GIA_THUE_MAC_DINH" <= CAST(:gia_max_hard AS NUMERIC)'
            params["gia_max_hard"] = int(intent_data["gia_max"])

        if intent_data.get("gia_min") is not None:
            sql += ' AND p."DON_GIA_THUE_MAC_DINH" >= CAST(:gia_min_hard AS NUMERIC)'
            params["gia_min_hard"] = int(intent_data["gia_min"])

        if intent_data.get("so_nguoi") is not None:
            sql += ' AND p."SO_NGUOI_TOI_DA" >= CAST(:so_nguoi_hard AS INTEGER)'
            params["so_nguoi_hard"] = int(intent_data["so_nguoi"])

        for idx, item in enumerate(intent_data.get("tien_nghi", [])):
            sql += f" AND COALESCE(NULLIF(p.\"TIEN_NGHI_JSON\", '')::jsonb, '[]'::jsonb) @> CAST(:tn_{idx} AS jsonb)"
            params[f"tn_{idx}"] = json.dumps([item], ensure_ascii=False)

        for idx, item in enumerate(intent_data.get("dich_vu", [])):
            sql += f" AND COALESCE(NULLIF(p.\"DICH_VU_JSON\", '')::jsonb, '[]'::jsonb) @> CAST(:dv_{idx} AS jsonb)"
            params[f"dv_{idx}"] = json.dumps([item], ensure_ascii=False)

        sql += """
        )
        SELECT *
        FROM ranked_rooms
        WHERE "MATCH_SCORE" >= 50
        ORDER BY "BUILDING_PRIORITY" DESC, "MATCH_SCORE" DESC, "DON_GIA_THUE_MAC_DINH" ASC
        LIMIT 20
        """

        print("\n=== [DEBUG] PostgreSQL QUERY ===")
        print(sql)
        print("Parameters:", params)

        statement = text(sql)

        with self.engine.connect() as conn:
            result = conn.execute(statement, params)
            return result.mappings().all()

    def process_message(self, user_input: str) -> dict:
        print(f"\n==================== [DEBUG CONSOLE START] ====================")
        print(f"📥 Tin nhắn thô nhập vào: '{user_input}'")

        # Mỗi tin nhắn được xử lý ĐỘC LẬP (1-1): không còn bộ nhớ hội thoại/
        # cộng dồn tiêu chí giữa các lượt chat — state chỉ tồn tại trong
        # phạm vi xử lý của riêng tin nhắn này.
        state = self._empty_filter_state()

        if user_input.lower() == "clear":
            return {"type": "system", "message": "Đã dọn dẹp bộ nhớ ngữ cảnh hội thoại thành công!"}

        normalized_message = user_input.strip().casefold().strip(" .,!?")
        if normalized_message in {"hi", "hello", "hey", "xin chào", "chào", "chào bạn"}:
            return {
                "type": "result",
                "message": "Xin chào! Mình có thể giúp bạn tìm phòng theo khu vực, giá, số người, diện tích hoặc tiện nghi. Bạn đang cần phòng như thế nào?",
                "data": [],
                "current_filters": state,
            }

        # ---------------------------------------------------------
        # BƯỚC 1: PROMPT 1 (INTENT EXTRACTION) -> STRUCTURED OUTPUT
        # ---------------------------------------------------------
        prompt_1 = self.PROMPT_1_EXTRACTION.format(kb_context=self.kb_content)

        try:
            raw_response = self.structured_llm.invoke(prompt_1 + f"\n\nNgười dùng hiện tại nói: {user_input}")
            print("\n=== [DEBUG] BƯỚC 1: KẾT QUẢ TRÍCH XUẤT TỪ PROMPT 1 ===")
            print(f" - Is Search (Tìm kiếm): {raw_response.is_search}")
            if raw_response.search_intent:
                print(f" - Search Intent Extracted: {raw_response.search_intent.model_dump_json(indent=2)}")
        except Exception as e:
            print(f"❌ [DEBUG ERROR] Lỗi tại Bước 1 Gọi LLM: {e}")
            return {"type": "error", "message": f"Đã xảy ra lỗi hệ thống. Thử lại sau nhé! ({e})"}

        rooms = []
        formatted_rooms = []

        # ---------------------------------------------------------
        # BƯỚC 2: XÂY DỰNG BỘ LỌC & AREA BOT (BỘ LỌC PHẠM VI) CHO TIN NHẮN NÀY
        # ---------------------------------------------------------
        if raw_response.is_search and raw_response.search_intent:
            ext = raw_response.search_intent

            if ext.dia_chi:
                print(f"\n=== [DEBUG] BƯỚC 2.1: TRIGGER AREA BOT (CHỈ LỌC CANDIDATE BUILDINGS) ===")
                state["dia_chi"] = ext.dia_chi

                matched_places = self.area_bot.find_places(ext.dia_chi)

                if not matched_places:
                    # Fallback: nới lỏng ngưỡng fuzzy-match để tăng khả năng
                    # nhận diện các cách gõ khác nhau (thiếu dấu, viết tắt,
                    # tên khu vực thay vì tên tòa cụ thể...).
                    matched_places = self.area_bot.find_places(ext.dia_chi, threshold=50)

                origin = matched_places[0] if matched_places else None

                if origin is None:
                    # QUAN TRỌNG: TUYỆT ĐỐI không dùng chuỗi thô người dùng gõ
                    # làm điều kiện so khớp CHÍNH XÁC (=) với TEN_TOA_NHA trong
                    # SQL, vì gần như chắc chắn sẽ không bao giờ trùng khớp và
                    # khiến hệ thống báo "không tìm thấy" dù DB thực sự có dữ
                    # liệu phù hợp. Thay vào đó chuyển sang lọc gần đúng
                    # (ILIKE) trong _unified_search thông qua "area_query".
                    state["area_query"] = ext.dia_chi
                    print(
                        " -> AreaBot chưa match được tòa gốc; "
                        "chuyển sang lọc gần đúng (ILIKE) theo địa chỉ/tên tòa."
                    )
                else:
                    print(
                        " -> AreaBot matched origin: "
                        f"{origin['name']} | {origin['address']}"
                    )

                    nearby_data = self.area_bot.find_nearby(
                        ext.dia_chi,
                        radius_meters=5000,
                    )

                    # matched_buildings: các tòa THỰC SỰ khớp tên/địa chỉ khách
                    # gõ -> dùng để ưu tiên hiển thị trước trong kết quả, tránh
                    # bị các tòa lân cận (chỉ để gợi ý thêm) có giá rẻ hơn
                    # chiếm hết chỗ trong LIMIT.
                    matched_names = [place["name"] for place in matched_places]
                    state["matched_buildings"] = list(dict.fromkeys(matched_names))

                    building_names = [
                        *matched_names,
                        *[place["place"] for place in nearby_data],
                    ]

                    state["nearby_buildings"] = list(dict.fromkeys(building_names))

                    print(
                        " -> Matched buildings (ưu tiên): "
                        + json.dumps(state["matched_buildings"], ensure_ascii=False)
                    )
                    print(
                        " -> Candidate buildings: "
                        + json.dumps(state["nearby_buildings"], ensure_ascii=False)
                    )
                    print(
                        " -> AreaBot recommendation: tìm kiếm trong "
                        f"{len(state['nearby_buildings'])} tòa nhà "
                        "(các tòa khớp địa chỉ và các tòa lân cận)."
                    )

            for field in ["gia_min", "gia_max", "so_nguoi", "dien_tich_min", "loai_phong", "is_shared"]:
                val = getattr(ext, field)
                if val is not None:
                    state[field] = val

            if ext.is_shared is True:
                state["loai_phong"] = None

            for field, values in (("tien_nghi", ext.tien_nghi), ("dich_vu", ext.dich_vu)):
                normalized_list = []
                master_key = "services" if field == "dich_vu" else "amenities"
                for item in values:
                    match = self._best_match(self._normalize_term(item), self.MASTER[master_key])
                    if match:
                        normalized_list.append(match)
                state[field] = list(set(normalized_list))

            print("\n=== [DEBUG] BƯỚC 2.2: BỘ LỌC CỦA TIN NHẮN NÀY (Trước khi Query) ===")
            print(json.dumps(state, ensure_ascii=False, indent=2))

            # ---------------------------------------------------------
            # BƯỚC 3: SQL RANKING & SORTING (QUYỀN QUYẾT ĐỊNH THUỘC VỀ ĐÂY)
            # ---------------------------------------------------------
            if state.get("is_shared") is True:
                rooms = self._shared_search(state)
            else:
                rooms = self._unified_search(state)

            print(f"\n=== [DEBUG] BƯỚC 3.2: KẾT QUẢ ĐẦU RA TỪ DATABASE (Số lượng phòng tìm thấy: {len(rooms)}) ===")

            try:
                public_rooms = self._load_public_rooms() if rooms else []
                public_room_map = {}
                for item in public_rooms:
                    try:
                        mapped_room_id = int(item.get("roomId"))
                    except (TypeError, ValueError):
                        continue
                    public_room_map.setdefault(mapped_room_id, item)
            except RuntimeError as exc:
                print(f"[DEBUG ERROR] Public listing resolution failed: {exc}")
                return {
                    "type": "error",
                    "message": (
                        "Hệ thống đã tìm thấy phòng nhưng chưa thể tải thông tin "
                        "điều hướng. Bạn vui lòng thử lại sau."
                    ),
                    "data": [],
                    "current_filters": state,
                }

            for room in rooms:
                room_id_raw = room.get("PHONG_ID")
                room_id = int(room_id_raw) if room_id_raw is not None else None

                if state.get("is_shared") is True:
                    # Bắt buộc resolve theo BAI_DANG_ID trước. Một PHONG_ID có thể
                    # có nhiều bài đăng với các mức giá khác nhau, nên ghép theo
                    # roomId có thể lấy nhầm giá của bài đăng khác.
                    post_id = room.get("BAI_DANG_ID")
                    expected_public_id = (
                        f"post-{int(post_id)}"
                        if post_id is not None
                        else None
                    )

                    public_room = next(
                        (
                            item
                            for item in public_rooms
                            if item.get("source") == "post"
                            and expected_public_id is not None
                            and str(item.get("id")) == expected_public_id
                        ),
                        None,
                    )

                    # Chỉ fallback theo roomId khi dữ liệu không có BAI_DANG_ID.
                    # Không fallback theo roomId nếu đã có postId nhưng không match,
                    # vì điều đó sẽ lấy nhầm bài đăng và sai giá.
                    if public_room is None and post_id is None and room_id is not None:
                        public_room = next(
                            (
                                item
                                for item in public_rooms
                                if item.get("source") == "post"
                                and item.get("roomId") == room_id
                            ),
                            None,
                        )
                else:
                    public_room = public_room_map.get(room_id) if room_id is not None else None

                if public_room is None:
                    print(
                        " -> Bỏ qua kết quả không có bản ghi public: "
                        f"PHONG_ID={room_id}, MA_PHONG={room.get('MA_PHONG')}"
                    )
                    continue

                if state.get("is_shared") is True:
                    formatted_room = self._format_shared_room(room, public_room)
                    print(
                        " 👉 Shared match: "
                        f"post={formatted_room.get('postId')} | "
                        f"room={formatted_room.get('roomId')} | "
                        f"current={formatted_room['currentOccupants']} | "
                        f"max={formatted_room['maxOccupants']} | "
                        f"available={formatted_room['availableSlots']} | "
                        f"price={formatted_room['gia_thue']}"
                    )
                    formatted_rooms.append(formatted_room)
                    continue

                formatted_room = self._format_public_room(room, public_room)
                formatted_room.update({
                    "ma_phong": room['MA_PHONG'],
                    "diem_phu_hop": int(room['MATCH_SCORE']),
                    "building_priority": int(room.get('BUILDING_PRIORITY') or 0),
                    "loai_phong": room['LOAI_PHONG'],
                    # Đồng bộ với giá public listing đang hiển thị trên frontend.
                    "gia_thue": int(formatted_room["price"]),
                    "toa_nha": room['TEN_TOA_NHA'],
                    "dia_chi": room['DIA_CHI']
                })
                print(f" 👉 Match: {formatted_room['ma_phong']} | Tòa: {formatted_room['toa_nha']} | Giá: {formatted_room['gia_thue']} VND | MATCH_SCORE: {formatted_room['diem_phu_hop']}")
                formatted_rooms.append(formatted_room)

            if state.get("is_shared") is not True and formatted_rooms:
                # SQL đã lọc/xếp hạng theo PHONG.DON_GIA_THUE_MAC_DINH, nhưng
                # giá THỰC SỰ hiển thị cho khách (gia_thue) lấy từ bài đăng
                # public, có thể khác. Nếu không lọc/sắp xếp lại theo đúng
                # giá hiển thị này, khách có thể thấy phòng "lệch" khỏi tiêu
                # chí giá họ yêu cầu -> hiểu nhầm là chatbot báo sai giá.
                gia_min = state.get("gia_min")
                gia_max = state.get("gia_max")

                def _in_price_range(r):
                    price = r.get("gia_thue", 0)
                    if gia_min is not None and price < gia_min:
                        return False
                    if gia_max is not None and price > gia_max:
                        return False
                    return True

                if gia_min is not None or gia_max is not None:
                    formatted_rooms = [r for r in formatted_rooms if _in_price_range(r)]

                formatted_rooms.sort(
                    key=lambda r: (
                        -int(r.get("building_priority", 0)),
                        -int(r.get("diem_phu_hop", 0)),
                        int(r.get("gia_thue", 0)),
                    )
                )
                formatted_rooms = formatted_rooms[:5]

        # ---------------------------------------------------------
        # BƯỚC 4: PROMPT 2 (LLM DIỄN GIẢI KẾT QUẢ THÀNH CÂU TRẢ LỜI TỰ NHIÊN)
        # ---------------------------------------------------------
        if not raw_response.is_search:
            sql_context_str = "Không thực hiện tìm kiếm phòng cho tin nhắn này."
            opening_line = ""
        elif formatted_rooms:
            sql_context_str = json.dumps(formatted_rooms, ensure_ascii=False, indent=2)
            filter_summary = self._build_filter_summary(state)
            opening_line = self._build_opening_line(filter_summary, len(formatted_rooms))
        else:
            sql_context_str = "Hệ thống không tìm thấy phòng nào phù hợp."
            filter_summary = self._build_filter_summary(state)
            opening_line = self._build_opening_line(filter_summary, 0)

        prompt_2 = self.PROMPT_2_CS.format(
            user_input=user_input,
            is_off_topic=raw_response.is_off_topic,
            is_qa=raw_response.is_qa,
            is_search=raw_response.is_search,
            reply_message=raw_response.reply_message or "Không có",
            opening_line=opening_line or "Không có (is_search = False, bỏ qua quy tắc 4).",
            result_count=len(formatted_rooms),
            sql_results=sql_context_str,
            kb_context=self.kb_content
        )

        if raw_response.is_search:
            final_message = self._build_deterministic_search_message(
                opening_line,
                formatted_rooms,
                matched_buildings=state.get("matched_buildings"),
            )
        else:
            final_message = self.llm.invoke(prompt_2).content

        print(f"\n=== [DEBUG] BƯỚC 4: CÂU TRẢ LỜI CUỐI ===")
        print(final_message)
        print(f"==================== [DEBUG CONSOLE END] ====================\n")

        return {
            "type": "result",
            "message": final_message,
            "data": formatted_rooms,
            "current_filters": state
        }
        
if __name__ == "__main__":
    bot = RealEstateBot()

    print("=== Chatbot thuê phòng thông minh ===")
    print("Gõ exit để thoát.\n")

    while True:
        user = input("Bạn: ")

        if user.lower() == "exit":
            break

        result = bot.process_message(user)

        print("\nBot:", result["message"])
        if result.get("data") and len(result["data"]) > 0:
            print("--- KẾT QUẢ TÌM KIẾM CỤ THỂ ---")
            for room in result["data"]:
                print(f"👉 {room['ma_phong']} | {room['toa_nha']} | {room['gia_thue']} VND")
        print("---------------------------\n")
