import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from langchain_core.documents import Document
from core.ingest import ingest_document


class FakeVectorDb:
    def __init__(self):
        self.deleted = []
        self.ids = []
        self.documents = []

    def get(self, where):
        return {"ids": ["old:0"]} if where.get("document_id") == "doc-1" else {"ids": []}

    def delete(self, ids):
        self.deleted.extend(ids)

    def add_documents(self, documents, ids):
        self.documents.extend(documents)
        self.ids.extend(ids)


class ManagedDocumentIngestTests(unittest.TestCase):
    def test_replaces_old_vectors_and_uses_deterministic_ids(self):
        vector_db = FakeVectorDb()
        chunks = [
            Document(page_content="Nội quy tòa nhà.", metadata={}),
            Document(page_content="Giờ mở cửa.", metadata={}),
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.ingest.load_and_split", return_value=chunks
        ):
            file_path = Path(temp_dir) / "rules.txt"
            file_path.write_text("unused", encoding="utf-8")
            count = ingest_document(
                str(file_path),
                document_id="doc-1",
                building_code="1",
                original_file_name="rules.txt",
                storage_key="documents/1/doc-1/rules.txt",
                category="Nội quy",
                uploaded_by="123",
                vector_db=vector_db,
            )

        self.assertGreater(count, 0)
        self.assertEqual(vector_db.deleted, ["old:0"])
        self.assertEqual(vector_db.ids, [f"doc-1:{i}" for i in range(count)])
        self.assertEqual(vector_db.documents[0].metadata["document_id"], "doc-1")
        self.assertEqual(vector_db.documents[0].metadata["building_code"], "1")


if __name__ == "__main__":
    unittest.main()
