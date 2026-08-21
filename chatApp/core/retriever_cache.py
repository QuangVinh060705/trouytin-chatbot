"""
core/retriever_cache.py
-------------------------
API sẽ nhận nhiều request cho cùng 1 building_code liên tục -> không nên
tạo RAGRetriever (build lại BM25 từ đầu) mỗi request. File này cache lại
theo building_code, và cho phép "làm mới" (refresh) sau khi ingest tài liệu mới.
"""

from threading import Lock

from core.retriever import RAGRetriever

_cache = {}
_lock = Lock()


def get_retriever(building_code: str) -> RAGRetriever:
    building_code = building_code.strip().upper()
    with _lock:
        if building_code not in _cache:
            _cache[building_code] = RAGRetriever(building_code)
        return _cache[building_code]


def invalidate(building_code: str):
    """Gọi hàm này ngay sau khi ingest xong tài liệu mới cho 1 tòa nhà,
    để lần hỏi tiếp theo BM25 thấy được dữ liệu mới."""
    building_code = building_code.strip().upper()
    with _lock:
        if building_code in _cache:
            _cache[building_code].refresh()
        else:
            _cache[building_code] = RAGRetriever(building_code)
