"""
cli/chatbot_cli.py
----------------------
Bản CLI tương tác (giữ nguyên trải nghiệm như file chatbot.py gốc),
nhưng toàn bộ logic đã chuyển vào core/.
Chạy: python -m cli.chatbot_cli
"""

from core.retriever import RAGRetriever
from core.chatbot import generate_response


def main():
    print("\n === HỆ THỐNG CHATBOT HỖ TRỢ CƯ DÂN ===")

    while True:
        building_code = input("\nNhập mã tòa nhà của bạn (Ví dụ: A1, A2...): ").strip().upper()
        if building_code:
            break

    retriever = RAGRetriever(building_code)

    print(f"\n[Hệ thống]: Đã kết nối & tối ưu cấu trúc dữ liệu tòa nhà {building_code}.")
    print("Bạn có thể bắt đầu đặt câu hỏi (Gõ 'exit' để thoát).")

    while True:
        query = input("\nCư dân: ").strip()
        if query.lower() == "exit":
            print("Tạm biệt anh/chị cư dân!")
            break

        if not query:
            continue

        print("Bot đang suy nghĩ và tìm kiếm dữ liệu...")
        reply = generate_response(query, retriever, building_code)
        print(f"Chatbot: {reply}")


if __name__ == "__main__":
    main()
