import random
import re
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

import pymupdf as fitz
import requests

from backend.services.ocr_space import (
    MAX_OCR_SPACE_FILE_BYTES,
    MAX_OCR_SPACE_PDF_PAGES,
    OCRSpaceConfigurationError,
    OCRSpaceProcessingError,
    extract_text,
    process_pdf,
    split_pdf_chunks,
)


def make_pdf(page_count, text_factory=None):
    document = fitz.open()
    for page_number in range(1, page_count + 1):
        page = document.new_page()
        page.insert_text(
            (72, 72),
            text_factory(page_number) if text_factory else f"Invoice page {page_number}",
        )
    output = BytesIO()
    document.save(output)
    document.close()
    return output.getvalue()


class OCRSpaceServiceTests(unittest.TestCase):
    def test_invalid_key_response_is_reported_without_echoing_key(self):
        response = Mock(status_code=403, ok=False)
        api_key = "test-key-not-for-production"
        with patch("backend.services.ocr_space.requests.post", return_value=response) as post:
            with self.assertRaises(OCRSpaceConfigurationError) as raised:
                extract_text(
                    {"OCR_SPACE_API_KEY": api_key},
                    b"\x89PNG\r\n\x1a\n",
                    "invoice.png",
                    "image/png",
                )

        self.assertNotIn(api_key, str(raised.exception))
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "https://api.ocr.space/parse/image")
        self.assertEqual(post.call_args.kwargs["headers"], {"apikey": api_key})
        self.assertEqual(post.call_args.kwargs["files"]["file"][2], "image/png")

    def test_network_timeout_is_reported_without_echoing_key(self):
        api_key = "test-key-not-for-production"
        with patch(
            "backend.services.ocr_space.requests.post",
            side_effect=requests.Timeout("connection timed out"),
        ):
            with self.assertRaises(OCRSpaceProcessingError) as raised:
                extract_text(
                    {"OCR_SPACE_API_KEY": api_key},
                    b"\x89PNG\r\n\x1a\n",
                    "invoice.png",
                    "image/png",
                )

        self.assertNotIn(api_key, str(raised.exception))

    def test_rate_limit_response_fails_the_chunk_without_retrying(self):
        response = Mock(status_code=429, ok=False)
        with patch("backend.services.ocr_space.requests.post", return_value=response) as post:
            with self.assertRaisesRegex(OCRSpaceProcessingError, "rate limit"):
                extract_text(
                    {"OCR_SPACE_API_KEY": "test-key"},
                    b"\x89PNG\r\n\x1a\n",
                    "invoice.png",
                    "image/png",
                )
        post.assert_called_once()

    def test_application_quota_guard_prevents_outbound_request(self):
        with patch("backend.services.ocr_space.requests.post") as post:
            with self.assertRaisesRegex(OCRSpaceProcessingError, "request budget"):
                extract_text(
                    {"OCR_SPACE_API_KEY": "test-key"},
                    b"\x89PNG\r\n\x1a\n",
                    "invoice.png",
                    "image/png",
                    request_guard=lambda: False,
                )
        post.assert_not_called()

    def test_empty_ocr_response_is_not_treated_as_success(self):
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {
            "OCRExitCode": 1,
            "IsErroredOnProcessing": False,
            "ParsedResults": [{"ParsedText": ""}],
        }
        with patch("backend.services.ocr_space.requests.post", return_value=response):
            with self.assertRaisesRegex(OCRSpaceProcessingError, "no extracted text"):
                extract_text(
                    {"OCR_SPACE_API_KEY": "test-key"},
                    b"\x89PNG\r\n\x1a\n",
                    "blank.png",
                    "image/png",
                )

    def test_small_pdf_uses_one_chunk_and_stays_within_limits(self):
        chunks = split_pdf_chunks(make_pdf(2))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["page_count"], 2)
        self.assertLessEqual(chunks[0]["size_bytes"], MAX_OCR_SPACE_FILE_BYTES)

    def test_75_page_pdf_is_split_into_ordered_chunks_of_at_most_three_pages(self):
        chunks = split_pdf_chunks(make_pdf(75))

        self.assertEqual(len(chunks), 25)
        self.assertEqual(
            [(chunk["start_page"], chunk["end_page"]) for chunk in chunks],
            [(page, page + 2) for page in range(1, 76, 3)],
        )
        self.assertTrue(
            all(
                chunk["page_count"] <= MAX_OCR_SPACE_PDF_PAGES
                and chunk["size_bytes"] <= MAX_OCR_SPACE_FILE_BYTES
                for chunk in chunks
            )
        )

    def test_75_page_text_is_combined_in_original_page_order(self):
        def fake_chunk_text(_config, _content, filename, _mime_type, request_guard=None):
            match = re.search(r"pages_(\d+)-(\d+)", filename)
            first, last = map(int, match.groups())
            return [f"recognized page {page}" for page in range(first, last + 1)]

        with patch(
            "backend.services.ocr_space._request_parsed_texts",
            side_effect=fake_chunk_text,
        ) as request:
            result, error = process_pdf(
                {"OCR_SPACE_API_KEY": "test-key"}, make_pdf(75), "invoice.pdf"
            )

        self.assertIsNone(error)
        self.assertEqual(request.call_count, 25)
        self.assertEqual(result["successful_chunks"], list(range(1, 26)))
        self.assertEqual(len(result["pages"]), 75)
        self.assertEqual(
            [page["page"] for page in result["pages"] if page["status"] == "succeeded"],
            list(range(1, 76)),
        )
        self.assertLess(
            result["text"].index("--- Page 1 ---"),
            result["text"].index("--- Page 75 ---"),
        )

    def test_oversized_individual_page_fails_clearly_after_optimization_attempt(self):
        pixels = random.Random(17).randbytes(1200 * 900 * 3)
        pixmap = fitz.Pixmap(fitz.csRGB, 1200, 900, pixels, False)
        document = fitz.open()
        page = document.new_page()
        page.insert_image(page.rect, pixmap=pixmap)
        output = BytesIO()
        document.save(output)
        document.close()

        with self.assertRaisesRegex(OCRSpaceProcessingError, "page 1 exceeds OCR.space's 1 MB"):
            split_pdf_chunks(output.getvalue())

    def test_failed_chunk_marks_remaining_pages_unattempted_and_keeps_partial_text(self):
        def fail_second_chunk(_config, _content, filename, _mime_type, request_guard=None):
            if "pages_4-6" in filename:
                raise OCRSpaceProcessingError("OCR.space rate limit reached.")
            return ["recognized page 1", "recognized page 2", "recognized page 3"]

        progress_updates = []
        with patch(
            "backend.services.ocr_space._request_parsed_texts",
            side_effect=fail_second_chunk,
        ) as request:
            result, error = process_pdf(
                {"OCR_SPACE_API_KEY": "test-key"},
                make_pdf(7),
                "invoice.pdf",
                progress_callback=progress_updates.append,
            )

        self.assertIn("rate limit", error)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["successful_chunks"], [1])
        self.assertEqual(result["failed_chunks"], [2])
        self.assertEqual(result["unprocessed_chunks"], [3])
        self.assertEqual(result["pages"][0]["status"], "succeeded")
        self.assertEqual(result["pages"][3]["status"], "failed")
        self.assertEqual(result["pages"][4]["status"], "failed")
        self.assertEqual(result["pages"][6]["status"], "not_attempted")
        self.assertIn("--- Page 1 ---", result["text"])
        self.assertNotIn("--- Page 7 ---", result["text"])
        self.assertEqual(progress_updates[-1]["completed_pages"], 6)
        self.assertEqual(progress_updates[-1]["total_pages"], 7)

    def test_single_page_over_api_limit_raises_instead_of_skipping_it(self):
        with patch(
            "backend.services.ocr_space._save_optimized_pdf",
            return_value=b"x" * (MAX_OCR_SPACE_FILE_BYTES + 1),
        ):
            with self.assertRaisesRegex(OCRSpaceProcessingError, "page 1 exceeds"):
                split_pdf_chunks(make_pdf(1))


if __name__ == "__main__":
    unittest.main()
