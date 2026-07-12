import os
import json
from enum import Enum
from typing import Optional, List

from dotenv import load_dotenv
from rapidfuzz import process, fuzz
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from langchain_groq import ChatGroq

# IMPORT thuật toán tìm khoảng cách của bạn (Giả sử file cũ tên là area_bot.py)
from chatbotWeb.area_bot import AreaRecommendationBot

load_dotenv()

# --- CÁC PYDANTIC MODELS ---
class ModifierAction(str, Enum):
    ADD = "add"
    REMOVE = "remove"
    CLEAR = "clear"

class ModifiedField(BaseModel):
    values: List[str] = Field(default_factory=list, description="Danh sách các mục được chỉ định")
    action: ModifierAction = Field(default=ModifierAction.ADD, description="Hành động cụ thể tác động lên danh sách")

class SearchIntent(BaseModel):
    gia_min: int | None = Field(default=None, description="Giá thuê tối thiểu khách yêu cầu (VND).")
    gia_max: int | None = Field(
        default=None, 
        description="Giá thuê tối đa khách yêu cầu (VND). Quy đổi các từ viết tắt như '3t', '3tr', '3 triệu' thành số nguyên: 3000000."
    )
    so_nguoi: int | None = Field(default=None, description="Số lượng người ở tối đa hoặc số người muốn thuê.")
    dien_tich_min: float | None = Field(default=None, description="Diện tích tối thiểu (m2).")
    loai_phong: str | None = Field(default=None, description="Type phòng trọ (STUDIO, ban công, duplex, ...).")
    dia_chi: str | None = Field(default=None, description="Tên tòa nhà cụ thể, tên đường hoặc tên khu vực/quận huyện muốn thuê phòng.")
    
    tien_nghi_mod: Optional[ModifiedField] = Field(default=None, description="Hành động cập nhật danh sách tiện nghi")
    dich_vu_mod: Optional[ModifiedField] = Field(default=None, description="Hành động cập nhật danh sách dịch vụ")

class BotResponse(BaseModel):
    is_off_topic: bool = Field(description="True nếu tin nhắn KHÔNG liên quan đến phòng trọ, thuê nhà, nội quy.")
    is_qa: bool = Field(description="True nếu người dùng hỏi đáp thông tin, nội quy dựa trên Knowledge Base.")
    is_search: bool = Field(description="True nếu người dùng muốn tìm phòng hoặc thay đổi tiêu chí tìm kiếm.")
    reply_message: str | None = Field(default=None, description="Câu trả lời phản hồi trực tiếp (có thể để trống ở bước này).")
    search_intent: Optional[SearchIntent] = Field(default=None, description="Trích xuất điều kiện lọc nếu is_search = True")


# --- LỚP CHÍNH CỦA CHATBOT ---
class RealEstateBot:
    def __init__(self):
        # 1. Khởi tạo Database Engine
        self.engine = create_engine(
            f"mysql+pymysql://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}@"
            f"{os.getenv('MYSQL_HOST')}:{os.getenv('MYSQL_PORT')}/{os.getenv('MYSQL_DATABASE')}"
        )
        
        # 2. Khởi tạo LLM
        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.3-70b-versatile",
            temperature=0.1
        )
        self.structured_llm = self.llm.with_structured_output(BotResponse)
        
        # 3. Khởi tạo Area Bot
        self.area_bot = AreaRecommendationBot()
        
        # 4. Load Master Data & Knowledge base
        self.MASTER = self._load_master_data()
        self.kb_content = self._load_kb()
        
        # --- PROMPT 1: INTENT EXTRACTION ---
        self.PROMPT_1_EXTRACTION = """
        Bạn là AI phân tích và trích xuất thực thể cấu trúc (Entity Extraction) từ tin nhắn của khách hàng thuê phòng trọ.
        Nhiệm vụ của bạn là đọc hiểu ngôn ngữ tự nhiên và chuyển đổi chính xác thành cấu trúc dữ liệu định dạng JSON.

        [QUY TẮC BẮT BUỘC TRÍCH XUẤT]:
        1. Tuyệt đối KHÔNG bỏ sót thông tin về giá tiền. Quy đổi toàn bộ các từ viết tắt ('3t', '3tr', '8tr') sang số nguyên đầy đủ (Ví dụ: 3000000, 8000000) và điền vào trường 'gia_max'.
        2. Trường 'dia_chi' chỉ lưu danh từ riêng đại diện cho địa điểm, khu vực hoặc tòa nhà (Ví dụ: "Hai Bà Trưng", "Thanh Xuân").
        3. Phân loại chuẩn xác: Off-topic => is_off_topic = True; Hỏi nội quy => is_qa = True; Tìm kiếm phòng => is_search = True.
        
        [KNOWLEDGE BASE]
        {kb_context}
        """
        
        # --- PROMPT 2: CUSTOMER SERVICE (ĐÃ CHUẨN HÓA THEO THIẾT KẾ CỦA BẠN) ---
        self.PROMPT_2_CS = """
        Bạn là AI Tư vấn Phòng trọ thông minh, nhiệt tình và thân thiện.
        Nhiệm vụ của bạn là dựa vào Thông tin hệ thống cung cấp dưới đây để phản hồi tin nhắn của khách hàng bằng ngôn ngữ tự nhiên.
        
        [TIN NHẮN CỦA KHÁCH]: "{user_input}"
        
        [KẾT QUẢ TÌM KIẾM SQL TỪ HỆ THỐNG]:
        {sql_results}
        
        [QUAN TRỌNG - QUY TẮC TUÂN THỦ KIẾN TRÚC]:
        1. VỀ PHẠM VI ĐỊA LÝ: AreaRecommendationBot đã làm xong nhiệm vụ xác định danh sách các tòa nhà được phép tìm kiếm dựa trên vị trí khách hàng gõ. Nó không đánh giá chất lượng phòng.
        2. VỀ QUYỀN QUYẾT ĐỊNH: Danh sách phòng nằm trong [KẾT QUẢ TÌM KIẾM SQL] là kết quả chính thức đã được hệ thống chấm MATCH_SCORE (Điểm phù hợp) dựa trên các tiêu chí Giá, Diện tích, Số người, Tiện nghi.
        3. KHÔNG ĐƯỢC OVER-STEP (VƯỢT QUYỀN): 
           - Bạn tuyệt đối KHÔNG ĐƯỢC tự ý đánh giá lại, không tự loại bỏ phòng dựa trên cảm tính hoặc suy luận địa lý (Ví dụ: Không được phép nói "phòng này ở Đống Đa nên không phù hợp" hay "khách tìm Cầu Giấy nên phòng này không nên giới thiệu").
           - Nếu SQL trả về phòng, hãy coi đó là các phòng lân cận phù hợp nhất và giới thiệu nhiệt tình cho khách.
           - CHỈ thông báo không tìm thấy phòng khi và chỉ khi [KẾT QUẢ TÌM KIẾM SQL] thực sự trả về mảng rỗng hoặc thông báo trống.
        """
        
        # 5. Bộ nhớ ngữ cảnh (State) của người dùng
        self.state = {
            "gia_min": None, "gia_max": None, "so_nguoi": None,
            "dien_tich_min": None, "loai_phong": None, "dia_chi": None,
            "tien_nghi": [], "dich_vu": [], "nearby_buildings": [] 
        }

    def _load_kb(self):
        try:
            with open("knowledge_base.json", "r", encoding="utf-8") as f:
                return json.dumps(json.load(f), ensure_ascii=False, indent=2)
        except FileNotFoundError:
            return "Nội quy: Giờ giấc tự do. Nuôi thú cưng nhỏ cho phép."

    def _load_master_data(self):
        room_types, amenities, services = set(), set(), set()
        with self.engine.connect() as conn:
            for row in conn.execute(text("SELECT DISTINCT LOAI_PHONG FROM PHONG")):
                if row[0]: room_types.add(row[0])
            for row in conn.execute(text("SELECT TIEN_NGHI_JSON FROM PHONG")):
                if row[0]:
                    try:
                        data = json.loads(row[0])
                        if isinstance(data, list): amenities.update(data)
                    except: pass
        return {"room_types": sorted(room_types), "amenities": sorted(amenities), "services": sorted(services)}

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

    # --- HÀM TÌM KIẾM SQL (ĐÃ LOẠI BỎ ĐIỂM VỊ TRÍ TRÙNG LẶP) ---
    def _unified_search(self, intent_data: dict):
        sql = """
        SELECT p.*, tn.TEN_TOA_NHA, tn.DIA_CHI,
        (
            -- QUYỀN QUYẾT ĐỊNH CỦA MATCH_SCORE: Chỉ chấm điểm dựa trên thông số phòng, không cộng điểm vị trí nữa
            (CASE WHEN :gia_max IS NULL THEN 30 WHEN p.DON_GIA_THUE_MAC_DINH <= :gia_max THEN 30 WHEN p.DON_GIA_THUE_MAC_DINH - :gia_max <= 1000000 THEN 20 ELSE 0 END) +
            (CASE WHEN :so_nguoi IS NULL THEN 25 WHEN p.SO_NGUOI_TOI_DA >= :so_nguoi THEN 25 ELSE 0 END) +
            (CASE WHEN :dien_tich_min IS NULL THEN 20 WHEN p.DIEN_TICH >= :dien_tich_min THEN 20 WHEN :dien_tich_min - p.DIEN_TICH <= 5 THEN 10 ELSE 0 END) +
            (CASE WHEN :loai_phong IS NULL THEN 25 WHEN LOWER(p.LOAI_PHONG) = LOWER(:loai_phong) THEN 25 ELSE 0 END)
        ) AS MATCH_SCORE
        FROM PHONG p
        JOIN TANG t ON p.TANG_ID = t.TANG_ID
        JOIN TOA_NHA tn ON t.TOA_NHA_ID = tn.TOA_NHA_ID
        WHERE p.TRANG_THAI = 'TRONG'
        """
        
        params = {
            "gia_max": intent_data.get("gia_max"), 
            "so_nguoi": intent_data.get("so_nguoi"),
            "dien_tich_min": intent_data.get("dien_tich_min"), 
            "loai_phong": intent_data.get("loai_phong")
        }

        # AreaRecommendationBot quyết định giới hạn phạm vi các tòa nhà cho phép quét ở mệnh đề WHERE cứng
        nearby_buildings = intent_data.get("nearby_buildings", [])
        if nearby_buildings:
            placeholders = [f":b{i}" for i in range(len(nearby_buildings))]
            sql += f" AND tn.TEN_TOA_NHA IN ({', '.join(placeholders)})"
            for i, building_name in enumerate(nearby_buildings):
                params[f"b{i}"] = building_name

        # Bộ lọc cứng giá (Hard Filter) ngăn chặn lọt phòng sai phân khúc lớn
        if intent_data.get("gia_max"):
            sql += " AND p.DON_GIA_THUE_MAC_DINH <= :gia_max_hard"
            params["gia_max_hard"] = int(intent_data.get("gia_max")) + 1500000

        for idx, item in enumerate(intent_data.get("tien_nghi", [])):
            sql += f" AND JSON_SEARCH(p.TIEN_NGHI_JSON, 'one', :tn_{idx}) IS NOT NULL"
            params[f"tn_{idx}"] = item

        # Điều kiện sàn lọc chất lượng
        sql += "\nHAVING MATCH_SCORE >= 50"
        sql += "\nORDER BY MATCH_SCORE DESC, p.DON_GIA_THUE_MAC_DINH ASC LIMIT 5"

        # --- DEBUG CONSOLE LỆNH SQL THỰC TẾ ---
        print("\n=== [DEBUG] BƯỚC 3.1: RAW SQL QUERY EXECUTING ===")
        print(sql)
        print("Parameters:", params)

        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params)
            return result.mappings().all()

    def process_message(self, user_input: str) -> dict:
        print(f"\n==================== [DEBUG CONSOLE START] ====================")
        print(f"📥 Tin nhắn thô nhập vào: '{user_input}'")

        if user_input.lower() == "clear":
            self.state = {k: None if k not in ["tien_nghi", "dich_vu", "nearby_buildings"] else [] for k in self.state}
            return {"type": "system", "message": "Đã dọn dẹp bộ nhớ ngữ cảnh hội thoại thành công!"}

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
        # BƯỚC 2: UPDATE STATE & AREA BOT (BỘ LỌC PHẠM VI)
        # ---------------------------------------------------------
        if raw_response.is_search and raw_response.search_intent:
            ext = raw_response.search_intent

            if ext.dia_chi and ext.dia_chi != self.state.get("dia_chi"):
                print(f"\n=== [DEBUG] BƯỚC 2.1: TRIGGER AREA BOT (CHỈ LỌC CANDIDATE BUILDINGS) ===")
                self.state["dia_chi"] = ext.dia_chi
                self.state["tien_nghi"] = [] 
                
                nearby_data = self.area_bot.find_nearby(ext.dia_chi, radius_meters=5000)
                if nearby_data:
                    building_names = [ext.dia_chi] + [place['place'] for place in nearby_data]
                    self.state["nearby_buildings"] = building_names
                    print(f" -> Thu hẹp phạm vi tìm kiếm trong {len(nearby_data)} tòa nhà của AreaBot.")
                else:
                    self.state["nearby_buildings"] = [ext.dia_chi]

            # Đồng bộ bộ lọc vào Session State
            for field in ["gia_min", "gia_max", "so_nguoi", "dien_tich_min", "loai_phong"]:
                val = getattr(ext, field)
                if val is not None: self.state[field] = val
                
            if ext.tien_nghi_mod:
                mod = ext.tien_nghi_mod
                curr_tn = self.state["tien_nghi"]
                if mod.action == ModifierAction.ADD: self.state["tien_nghi"] = list(set(curr_tn + mod.values))
                elif mod.action == ModifierAction.REMOVE: self.state["tien_nghi"] = [x for x in curr_tn if x not in mod.values]
                elif mod.action == ModifierAction.CLEAR: self.state["tien_nghi"] = []

            for field in ["tien_nghi", "dich_vu"]:
                normalized_list = []
                for item in self.state.get(field, []):
                    match = self._best_match(self._normalize_term(item), self.MASTER[f"{field if field == 'services' else 'amenities'}"])
                    if match: normalized_list.append(match)
                self.state[field] = list(set(normalized_list))

            print("\n=== [DEBUG] BƯỚC 2.2: TRẠNG THÁI FILTER STATE HIỆN TẠI (Trước khi Query) ===")
            print(json.dumps(self.state, ensure_ascii=False, indent=2))

            # ---------------------------------------------------------
            # BƯỚC 3: SQL RANKING & SORTING (QUYỀN QUYẾT ĐỊNH THUỘC VỀ ĐÂY)
            # ---------------------------------------------------------
            rooms = self._unified_search(self.state)
            print(f"\n=== [DEBUG] BƯỚC 3.2: KẾT QUẢ ĐẦU RA TỪ DATABASE (Số lượng phòng tìm thấy: {len(rooms)}) ===")

            for room in rooms:
                formatted_room = {
                    "ma_phong": room['MA_PHONG'],
                    "diem_phu_hop": int(room['MATCH_SCORE']),
                    "loai_phong": room['LOAI_PHONG'],
                    "gia_thue": int(room['DON_GIA_THUE_MAC_DINH']) if room['DON_GIA_THUE_MAC_DINH'] is not None else 0,
                    "toa_nha": room['TEN_TOA_NHA'],
                    "dia_chi": room['DIA_CHI']
                }
                print(f" 👉 Match: {formatted_room['ma_phong']} | Tòa: {formatted_room['toa_nha']} | Giá: {formatted_room['gia_thue']} VND | MATCH_SCORE: {formatted_room['diem_phu_hop']}")
                formatted_rooms.append(formatted_room)

        # ---------------------------------------------------------
        # BƯỚC 4: PROMPT 2 (LLM DIỄN GIẢI KẾT QUẢ THÀNH CÂU TRẢ LỜI TỰ NHIÊN)
        # ---------------------------------------------------------
        sql_context_str = "Hệ thống không tìm thấy phòng nào phù hợp."
        if formatted_rooms:
            sql_context_str = json.dumps(formatted_rooms, ensure_ascii=False, indent=2)

        prompt_2 = self.PROMPT_2_CS.format(
            user_input=user_input,
            is_off_topic=raw_response.is_off_topic,
            is_qa=raw_response.is_qa,
            is_search=raw_response.is_search,
            sql_results=sql_context_str,
            kb_context=self.kb_content
        )
        
        final_chat_response = self.llm.invoke(prompt_2)
        print(f"\n=== [DEBUG] BƯỚC 4: CÂU TRẢ LỜI NGÔN NGỮ TỰ NHIÊN (PROMPT 2) ===")
        print(final_chat_response.content)
        print(f"==================== [DEBUG CONSOLE END] ====================\n")

        return {
            "type": "result",
            "message": final_chat_response.content,
            "data": formatted_rooms, 
            "current_filters": self.state
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