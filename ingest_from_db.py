"""
Ingest du lieu that tu Prop-Tech backend vao ChromaDB cho chatbot RAG.

Prop-Tech backend doc Supabase/Postgres. Script nay khong ket noi DB truc tiep,
chi goi internal API cua Prop-Tech:
    GET /api/internal/chatbot/knowledge-documents

Chay moi khi du lieu toa nha/phong/dich vu/knowledge base thay doi:
    python ingest_from_db.py
    python ingest_from_db.py --rebuild
"""

import argparse
import os
from typing import Any

import requests
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

# Phai khop voi services/chatbotappService.py
CHROMA_DB_DIR = "chroma_db"
EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_PROPTECH_BASE_URL = "http://localhost:5052"
DEFAULT_INTERNAL_API_KEY = "dev-internal-key"


def normalize_base_url(value: str) -> str:
    return (value or DEFAULT_PROPTECH_BASE_URL).strip().rstrip("/")


def fetch_documents(base_url: str, internal_api_key: str, building_id: int | None) -> list[dict[str, Any]]:
    url = f"{normalize_base_url(base_url)}/api/internal/chatbot/knowledge-documents"
    headers = {"X-Internal-Api-Key": internal_api_key}
    params = {"buildingId": building_id} if building_id is not None else None

    response = requests.get(url, headers=headers, params=params, timeout=90)
    if response.status_code == 403:
        raise RuntimeError("Prop-Tech tu choi internal key. Kiem tra PROPTECH_INTERNAL_API_KEY.")
    if response.status_code >= 400:
        raise RuntimeError(f"Prop-Tech API loi {response.status_code}: {response.text[:500]}")

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Prop-Tech API tra ve payload khong dung dang list.")

    return payload


def build_documents(items: list[dict[str, Any]]) -> list[Document]:
    documents: list[Document] = []
    for item in items:
        content = str(item.get("content") or "").strip()
        building_code = str(item.get("buildingCode") or "").strip().upper()
        source = str(item.get("source") or "proptech").strip()
        if not content or not building_code:
            continue

        documents.append(
            Document(
                page_content=content,
                metadata={
                    "building_code": building_code,
                    "source": source,
                },
            )
        )

    return documents


def clear_vector_db(vector_db: Chroma) -> None:
    existing = vector_db.get()
    ids = existing.get("ids", [])
    if ids:
        vector_db.delete(ids=ids)
        print(f"  -> da xoa {len(ids)} doan cu.")


def run_ingest(
    rebuild: bool = False,
    building_id: int | None = None,
    proptech_url: str | None = None,
    internal_api_key: str | None = None,
    vector_db: Chroma | None = None,
) -> dict[str, Any]:
    base_url = normalize_base_url(
        proptech_url or os.getenv("PROPTECH_API_BASE_URL", DEFAULT_PROPTECH_BASE_URL)
    )
    api_key = internal_api_key or os.getenv("PROPTECH_INTERNAL_API_KEY", DEFAULT_INTERNAL_API_KEY)

    print(f"Goi Prop-Tech backend: {base_url}")
    raw_items = fetch_documents(base_url, api_key, building_id)
    documents = build_documents(raw_items)
    print(f"  -> nhan {len(raw_items)} item, tao {len(documents)} document.")

    if vector_db is None:
        print("Khoi tao embedding (BAAI/bge-m3, CPU)...")
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
        )
        vector_db = Chroma(
            persist_directory=CHROMA_DB_DIR,
            embedding_function=embeddings,
        )

    deleted_count = 0
    if rebuild:
        print("Xoa sach du lieu cu trong chroma_db...")
        try:
            existing = vector_db.get()
            deleted_count = len(existing.get("ids", []))
            clear_vector_db(vector_db)
        except Exception as exc:
            print(f"  [Canh bao] khong xoa duoc du lieu cu: {exc}")

    added_count = 0
    if documents:
        print("Embed va ghi vao Chroma...")
        vector_db.add_documents(documents)
        added_count = len(documents)
    else:
        print("Khong co du lieu de nap.")

    building_count = len({doc.metadata["building_code"] for doc in documents})
    print(f"HOAN TAT: da nap {added_count} doan cho {building_count} toa nha.")

    return {
        "rebuild": rebuild,
        "building_id": building_id,
        "proptech_base_url": base_url,
        "raw_items": len(raw_items),
        "documents": len(documents),
        "added": added_count,
        "deleted": deleted_count,
        "building_count": building_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Xoa sach du lieu cu trong chroma_db truoc khi nap lai.",
    )
    parser.add_argument(
        "--building-id",
        type=int,
        default=None,
        help="Chi ingest mot toa nha theo TOA_NHA_ID. Bo trong de ingest tat ca.",
    )
    parser.add_argument(
        "--proptech-url",
        default=os.getenv("PROPTECH_API_BASE_URL", DEFAULT_PROPTECH_BASE_URL),
        help="Base URL Prop-Tech backend, mac dinh lay PROPTECH_API_BASE_URL hoac localhost:5052.",
    )
    parser.add_argument(
        "--internal-api-key",
        default=os.getenv("PROPTECH_INTERNAL_API_KEY", DEFAULT_INTERNAL_API_KEY),
        help="Internal API key de goi Prop-Tech.",
    )
    args = parser.parse_args()

    run_ingest(
        rebuild=args.rebuild,
        building_id=args.building_id,
        proptech_url=args.proptech_url,
        internal_api_key=args.internal_api_key,
    )


if __name__ == "__main__":
    main()
