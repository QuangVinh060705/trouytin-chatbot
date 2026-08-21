"""
core/query_rewrite.py
------------------------
GIAI ĐOẠN 4: QUERY REWRITE - Mở rộng câu hỏi tiếng Việt của cư dân
để tránh lệch từ khóa khi tìm kiếm. Giữ nguyên logic gốc.
"""

from core.models import llm


def rewrite_query(original_query, building_code):
    rewrite_prompt = f"""
Bạn là một chuyên gia phân tích ngôn ngữ tối ưu hóa cho hệ thống tìm kiếm (RAG) của tòa nhà {building_code}.
Nhiệm vụ của bạn là chuyển đổi câu hỏi ngắn hoặc ngôn ngữ nói của cư dân thành danh sách các cụm từ khóa/khái niệm tương đương bằng tiếng Việt để hỗ trợ tìm kiếm chính xác trong quy định văn bản.

Yêu cầu:
- Trả về tối đa 2-3 cụm từ/câu ngắn, phân tách bằng dấu phẩy (,).
- Tập trung vào các thuật ngữ hành chính, quy định, danh từ chính liên quan đến câu hỏi.
- Chỉ trả về các cụm từ tìm kiếm, KHÔNG giải thích gì thêm.

Ví dụ:
Người dùng: xe gửi ở đâu
Kết quả: quy định gửi xe, vị trí bãi giữ xe, khu vực đỗ xe

[CÂU HỎI CỦA CƯ DÂN]: {original_query}
[KẾT QUẢ REWRITE]:"""

    try:
        response = llm.invoke(rewrite_prompt)
        expanded_queries = response.content.strip()
        return f"{original_query} {expanded_queries.replace(',', ' ')}"
    except Exception as e:
        print(f"[Lỗi Rewrite Query]: {e}. Sử dụng query gốc.")
        return original_query
