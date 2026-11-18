import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from backend.app import create_app
from backend.config import Config
from backend.database import db


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        config = type(
            "TestConfig",
            (Config,),
            {
                "TESTING": True,
                "UPLOAD_FOLDER": root / "uploads",
                "DATABASE_PATH": root / "processed" / "test.sqlite3",
                "GOOGLE_CLOUD_PROJECT": "",
                "GOOGLE_CLOUD_LOCATION": "",
                "GOOGLE_CLOUD_PROCESSOR_ID": "",
                "OCR_SPACE_API_KEY": "",
            },
        )
        self.client = create_app(config).test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_dashboard_and_unconfigured_status(self):
        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        dashboard.close()
        status = self.client.get("/api/status").get_json()
        self.assertFalse(status["document_ai_configured"])

    def test_upload_rejects_extension_and_signature_mismatch(self):
        unsupported = self.client.post(
            "/api/upload",
            data={"document": (io.BytesIO(b"content"), "notes.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(unsupported.status_code, 415)

        mismatch = self.client.post(
            "/api/upload",
            data={"document": (io.BytesIO(b"not a PDF"), "invoice.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(mismatch.status_code, 415)

    def test_upload_rejects_empty_and_oversized_documents(self):
        empty = self.client.post(
            "/api/upload",
            data={"document": (io.BytesIO(b""), "invoice.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(empty.status_code, 400)

        oversized_pdf = b"%PDF-" + b"x" * (15 * 1024 * 1024)
        oversized = self.client.post(
            "/api/upload",
            data={"document": (io.BytesIO(oversized_pdf), "large.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(oversized.status_code, 413)

    def test_unconfigured_upload_is_recorded_as_failed_not_successful(self):
        response = self.client.post(
            "/api/upload",
            data={"document": (io.BytesIO(b"%PDF-1.4\n"), "invoice.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.get_json()["error"].lower())

        history = self.client.get("/api/documents").get_json()["documents"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "failed")
        self.assertEqual(history[0]["document_type"], "Invoice")

        detail = self.client.get(f"/api/documents/{history[0]['id']}").get_json()["document"]
        self.assertIsNone(detail["result"])
        self.assertEqual(self.client.get("/api/analytics").get_json()["failed"], 1)

    def test_ocr_space_upload_without_key_is_recorded_as_failed(self):
        response = self.client.post(
            "/api/upload",
            data={
                "provider": "ocr_space",
                "document": (io.BytesIO(b"%PDF-1.4\n"), "invoice.pdf", "application/pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("OCR_SPACE_API_KEY", response.get_json()["error"])
        self.assertNotIn("result", response.get_json())

        history = self.client.get("/api/documents").get_json()["documents"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertEqual(history[0]["document_type"], "Document")
        self.assertIsNone(
            self.client.get(f"/api/documents/{history[0]['id']}").get_json()["document"]["result"]
        )

    def test_ocr_space_unsupported_file_is_rejected(self):
        response = self.client.post(
            "/api/upload",
            data={
                "provider": "ocr_space",
                "document": (io.BytesIO(b"not an image"), "notes.txt", "text/plain"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.client.get("/api/documents").get_json()["documents"], [])

    def test_partial_pdf_result_and_page_progress_are_saved_on_failure(self):
        self.client.application.config["OCR_SPACE_API_KEY"] = "test-key"
        document_id = str(uuid.uuid4())
        progress = {
            "total_pages": 2,
            "completed_pages": 1,
            "successful_pages": 1,
            "total_chunks": 2,
            "completed_chunks": 1,
            "successful_chunks": [1],
            "failed_chunks": [],
            "current_chunk": None,
        }
        result = {
            "text": "--- Page 1 ---\nrecognized page",
            "page_count": 2,
            "provider": "ocr_space",
            "pages": [
                {"page": 1, "status": "succeeded", "text": "recognized page"},
                {"page": 2, "status": "not_attempted", "text": ""},
            ],
            "chunks": [{"index": 1, "start_page": 1, "end_page": 1, "status": "succeeded"}],
            "successful_chunks": [1],
            "failed_chunks": [],
            "unprocessed_chunks": [2],
        }

        def partial_result(
            _config, _content, _filename, progress_callback, request_guard=None
        ):
            progress_callback(progress)
            return result, "OCR.space rate limit reached."

        with patch("backend.routes.upload.pdf_page_count", return_value=2), patch(
            "backend.routes.upload.process_pdf", side_effect=partial_result
        ):
            response = self.client.post(
                "/api/upload",
                data={
                    "provider": "ocr_space",
                    "document_id": document_id,
                    "document": (
                        io.BytesIO(b"%PDF-1.4\n"),
                        "invoice.pdf",
                        "application/pdf",
                    ),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 502)
        detail = self.client.get(f"/api/documents/{document_id}").get_json()["document"]
        self.assertEqual(detail["status"], "failed")
        self.assertEqual(detail["result"]["pages"][0]["status"], "succeeded")
        self.assertEqual(detail["progress"]["completed_pages"], 1)
        self.assertIn("rate limit", detail["error_message"])

    def test_upload_rejects_non_uuid_document_id(self):
        response = self.client.post(
            "/api/upload",
            data={
                "provider": "ocr_space",
                "document_id": "not-a-uuid",
                "document": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "invoice.png", "image/png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/documents").get_json()["documents"], [])

    def test_ocr_space_request_budget_is_reserved_in_sqlite(self):
        database_path = self.client.application.config["DATABASE_PATH"]
        self.assertTrue(db.reserve_ocr_space_request(database_path, 1, 10))
        self.assertFalse(db.reserve_ocr_space_request(database_path, 1, 10))

    def test_delete_removes_document_record_and_uploaded_file(self):
        response = self.client.post(
            "/api/upload",
            data={"document": (io.BytesIO(b"%PDF-1.4\n"), "invoice.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        document_id = response.get_json()["id"]
        history = self.client.get("/api/documents").get_json()["documents"]
        stored_files = list((Path(self.temporary_directory.name) / "uploads").iterdir())
        self.assertEqual(len(stored_files), 1)

        deleted = self.client.delete(f"/api/documents/{document_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/documents").get_json()["documents"], [])
        self.assertEqual(list((Path(self.temporary_directory.name) / "uploads").iterdir()), [])
        self.assertNotEqual(history[0]["id"], "")


if __name__ == "__main__":
    unittest.main()
