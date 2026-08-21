"""
core/chatbot.py
------------------
Hàm generate_response() - trái tim của chatbot: rewrite query -> retrieve
-> build prompt -> gọi LLM -> trả lời cư dân.
Đây là nơi bạn sẽ sửa nếu muốn đổi văn phong, đổi nguyên tắc trả lời,
hoặc đổi cách xử lý khi không tìm thấy dữ liệu.
"""

from core.models import llm
from core.query_rewrite import rewrite_query
from core.retriever import RAGRetriever

FALLBACK_MESSAGE = (
    "Dạ, hiện tại em không tìm thấy thông tin quy định này trong hệ thống dữ liệu "
    "của tòa nhà mình. Anh/chị vui lòng liên hệ trực tiếp Hotline Ban quản lý để "
    "được hỗ trợ chi tiết ạ."
)


def build_prompt(query, context, building_code, history: str = ""):
    return f"""
Bạn là một trợ lý ảo Chatbot đại diện cho Ban quản lý tòa nhà {building_code}. Bạn đang trò chuyện với cư dân của tòa nhà, hãy luôn giữ thái độ lịch sự, lễ phép, thân thiện và sử dụng ngôn ngữ mượt mà, dễ chịu (ví dụ: xưng "Dạ, Ban quản lý xin thông tin đến anh/chị...", "Xin vui lòng...").

[NGUYÊN TẮC NỘI DUNG (BẮT BUỘC)]:
1. Nếu [CÂU HỎI CỦA CƯ DÂN] không liên quan đến tòa nhà/nhà trọ (ví dụ: hỏi thời tiết, ăn uống, tin tức, chuyện phiếm...), trả lời NGẮN GỌN trong 1-2 câu rằng câu hỏi này ngoài phạm vi hỗ trợ của Ban quản lý, KHÔNG cố dùng [NGỮ CẢNH QUY ĐỊNH] để trả lời cho có, KHÔNG lan man.
2. Nếu câu hỏi liên quan đến tòa nhà, chỉ dùng thông tin có trong [NGỮ CẢNH QUY ĐỊNH]. TUYỆT ĐỐI KHÔNG tự bịa đặt, không suy diễn thêm bất kỳ quy định hay mốc thời gian nào nằm ngoài văn bản gốc.
3. Luôn trả lời NGẮN GỌN, XÚC TÍCH, đi thẳng vào trọng tâm — không lặp lại câu hỏi, không mở đầu/dẫn dắt dài dòng.
4. Khi câu trả lời có từ 2 ý/mốc thời gian/điều kiện trở lên, trình bày bằng gạch đầu dòng (mỗi ý một dòng bắt đầu bằng "-") thay vì viết thành đoạn văn dài.

[NGỮ CẢNH QUY ĐỊNH]:
{context}

[LỊCH SỬ HỘI THOẠI GẦN ĐÂY]:
{history or "Không có"}

[CÂU HỎI CỦA CƯ DÂN]:
{query}

[CÂU TRẢ LỜI CỦA CHATBOT]:
"""


def generate_response_with_sources(
    query: str, retriever: RAGRetriever, building_code: str, history: str = ""
) -> tuple[str, list[dict]]:
    search_query = rewrite_query(query, building_code)
    print(f"   ↳ [Query mở rộng]: {search_query}")

    matched_docs = retriever.retrieve(search_query)

    if not matched_docs:
        return FALLBACK_MESSAGE, []

    context = "\n\n---\n\n".join(doc.page_content for doc in matched_docs)
    prompt = build_prompt(query, context, building_code, history)

    response = llm.invoke(prompt)
    sources = []
    seen = set()
    for doc in matched_docs:
        metadata = doc.metadata
        source_key = (
            metadata.get("document_id"),
            metadata.get("source"),
            metadata.get("page"),
            metadata.get("chunk_index"),
        )
        if source_key in seen:
            continue
        seen.add(source_key)
        sources.append({
            "document_id": metadata.get("document_id"),
            "title": metadata.get("title") or metadata.get("category"),
            "original_file_name": metadata.get("original_file_name"),
            "page": metadata.get("page"),
            "chunk_index": metadata.get("chunk_index"),
            "source": metadata.get("source"),
        })
    return response.content.strip(), sources


def generate_response(query: str, retriever: RAGRetriever, building_code: str) -> str:
    answer, _ = generate_response_with_sources(query, retriever, building_code)
    return answer
