"""
cli/ingest_cli.py
---------------------
Bản CLI ingest (giữ nguyên trải nghiệm như file ingest.py gốc),
nhưng toàn bộ logic đã chuyển vào core/.
Chạy: python -m cli.ingest_cli <path> <building_code> [--uploaded-by ten]
"""

import argparse

from core.ingest import ingest_path


def main():
    parser = argparse.ArgumentParser(
        description="Ingest tài liệu quy định vào ChromaDB cho hệ thống Chatbot cư dân."
    )
    parser.add_argument("path", help="Đường dẫn tới file hoặc thư mục chứa tài liệu (.pdf, .docx, .txt, .md)")
    parser.add_argument("building_code", help="Mã tòa nhà (VD: A1, A2...)")
    parser.add_argument("--uploaded-by", default=None, help="Tên/ID người upload tài liệu (tuỳ chọn)")
    args = parser.parse_args()

    total = ingest_path(args.path, args.building_code, uploaded_by=args.uploaded_by)

    print(
        f"\n=== HOÀN TẤT: Đã ingest tổng cộng {total} đoạn tài liệu vào ChromaDB "
        f"(Tòa nhà: {args.building_code.strip().upper()}) ==="
    )


if __name__ == "__main__":
    main()
