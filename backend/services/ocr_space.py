from io import BytesIO
from pathlib import Path

import pymupdf as fitz
import requests

OCR_SPACE_ENDPOINT = "https://api.ocr.space/parse/image"
MAX_OCR_SPACE_FILE_BYTES = 999_000
MAX_OCR_SPACE_PDF_PAGES = 3
OCR_SPACE_DAILY_REQUEST_BUDGET = 450
OCR_SPACE_MONTHLY_REQUEST_BUDGET = 22_500


class OCRSpaceConfigurationError(RuntimeError):
    pass


class OCRSpaceProcessingError(RuntimeError):
    pass


def is_configured(config):
    return bool(config.get("OCR_SPACE_API_KEY"))


def _messages(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _require_api_key(config):
    api_key = config.get("OCR_SPACE_API_KEY")
    if not api_key:
        raise OCRSpaceConfigurationError(
            "OCR.space is not configured. Set OCR_SPACE_API_KEY in the root .env file."
        )
    return api_key


def pdf_page_count(content):
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise OCRSpaceProcessingError(
            "The PDF is invalid or could not be opened."
        ) from error
    try:
        if document.needs_pass:
            raise OCRSpaceProcessingError(
                "Password-protected PDFs cannot be processed. Remove the password and try again."
            )
        if document.page_count < 1:
            raise OCRSpaceProcessingError("The PDF does not contain any pages.")
        return document.page_count
    finally:
        document.close()


def _save_optimized_pdf(document):
    output = BytesIO()
    document.save(
        output,
        garbage=4,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        clean=True,
    )
    return output.getvalue()


def split_pdf_chunks(content):
    try:
        source = fitz.open(stream=content, filetype="pdf")
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise OCRSpaceProcessingError("The PDF is invalid or could not be opened.") from error

    chunks = []
    try:
        if source.needs_pass:
            raise OCRSpaceProcessingError(
                "Password-protected PDFs cannot be processed. Remove the password and try again."
            )
        if source.page_count < 1:
            raise OCRSpaceProcessingError("The PDF does not contain any pages.")

        page_count = source.page_count
        next_page = 0
        while next_page < page_count:
            chunk_pages = min(MAX_OCR_SPACE_PDF_PAGES, page_count - next_page)
            while chunk_pages:
                first_page = next_page
                last_page = first_page + chunk_pages - 1
                part = fitz.open()
                try:
                    part.insert_pdf(source, from_page=first_page, to_page=last_page)
                    chunk_bytes = _save_optimized_pdf(part)
                finally:
                    part.close()

                if len(chunk_bytes) <= MAX_OCR_SPACE_FILE_BYTES:
                    chunks.append(
                        {
                            "index": len(chunks) + 1,
                            "start_page": first_page + 1,
                            "end_page": last_page + 1,
                            "page_count": chunk_pages,
                            "size_bytes": len(chunk_bytes),
                            "content": chunk_bytes,
                            "status": "pending",
                        }
                    )
                    next_page += chunk_pages
                    break

                if chunk_pages == 1:
                    raise OCRSpaceProcessingError(
                        f"PDF page {first_page + 1} exceeds OCR.space's 1 MB per-request "
                        "file limit after safe PDF optimization. Reduce the page's image "
                        "resolution or split the source document manually."
                    )
                chunk_pages -= 1
    finally:
        source.close()

    return chunks


def _request_parsed_texts(config, content, filename, mime_type, request_guard=None):
    api_key = _require_api_key(config)
    if len(content) > MAX_OCR_SPACE_FILE_BYTES:
        raise OCRSpaceProcessingError(
            "The file exceeds OCR.space's 1 MB per-request limit."
        )
    if request_guard is not None and not request_guard():
        raise OCRSpaceProcessingError(
            "DocuMind's OCR.space request budget for this month or day has been reached. "
            "Wait for the quota window to reset or check the provider account's usage."
        )

    try:
        response = requests.post(
            OCR_SPACE_ENDPOINT,
            headers={"apikey": api_key},
            data={"language": "eng", "isOverlayRequired": "false"},
            files={"file": (filename, BytesIO(content), mime_type)},
            timeout=(10, 90),
        )
    except requests.Timeout as error:
        raise OCRSpaceProcessingError(
            "The OCR.space request timed out. Please try the document again."
        ) from error
    except requests.RequestException as error:
        raise OCRSpaceProcessingError(
            "Could not reach OCR.space. Check the server's network connection and try again."
        ) from error

    if response.status_code in (401, 403):
        raise OCRSpaceConfigurationError(
            "OCR.space rejected the API key. Verify OCR_SPACE_API_KEY and the key's account status."
        )
    if response.status_code == 429:
        raise OCRSpaceProcessingError(
            "OCR.space rate limit reached. Wait before submitting another document."
        )
    if response.status_code >= 500:
        raise OCRSpaceProcessingError(
            "OCR.space is temporarily unavailable. Please try again later."
        )
    if not response.ok:
        raise OCRSpaceProcessingError(
            f"OCR.space returned HTTP {response.status_code} while processing the document."
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise OCRSpaceProcessingError(
            "OCR.space returned an invalid response. Please try again later."
        ) from error
    if not isinstance(payload, dict):
        raise OCRSpaceProcessingError(
            "OCR.space returned an invalid response. Please try again later."
        )

    messages = _messages(payload.get("ErrorMessage")) + _messages(payload.get("ErrorDetails"))
    message_text = " ".join(messages).lower()
    if any(fragment in message_text for fragment in ("invalid api key", "check your api key", "apikey")):
        raise OCRSpaceConfigurationError(
            "OCR.space rejected the API key. Verify OCR_SPACE_API_KEY and the key's account status."
        )
    try:
        exit_code = int(payload.get("OCRExitCode", 0))
    except (TypeError, ValueError):
        exit_code = 0
    if payload.get("IsErroredOnProcessing") or exit_code in (3, 4):
        if any(
            fragment in message_text
            for fragment in ("limit", "quota", "too many requests", "rate")
        ):
            raise OCRSpaceProcessingError(
                "The OCR.space request limit or quota was reached. Check the API plan and try again later."
            )
        raise OCRSpaceProcessingError(
            "OCR.space could not process this document. Check the file and try again."
        )

    parsed_results = payload.get("ParsedResults")
    if not isinstance(parsed_results, list):
        return []
    return [
        result.get("ParsedText", "").strip()
        if isinstance(result, dict) and isinstance(result.get("ParsedText"), str)
        else ""
        for result in parsed_results
    ]


def extract_text(config, content, filename, mime_type, request_guard=None):
    if mime_type not in {"image/png", "image/jpeg", "application/pdf"}:
        raise OCRSpaceProcessingError("OCR.space supports PDF, PNG, and JPG documents only.")
    if mime_type == "application/pdf":
        if len(content) > MAX_OCR_SPACE_FILE_BYTES:
            raise OCRSpaceProcessingError(
                "PDFs larger than 1 MB must be processed through the PDF chunking workflow."
            )
        if pdf_page_count(content) > MAX_OCR_SPACE_PDF_PAGES:
            raise OCRSpaceProcessingError(
                "PDFs with more than 3 pages must be processed through the PDF chunking workflow."
            )

    parsed_texts = _request_parsed_texts(
        config, content, filename, mime_type, request_guard=request_guard
    )
    extracted_text = "\n\n".join(text for text in parsed_texts if text).strip()
    if not extracted_text:
        raise OCRSpaceProcessingError(
            "OCR.space returned no extracted text. The document may be blank or unreadable."
        )

    pages = [
        {"page": index + 1, "status": "succeeded", "text": text}
        for index, text in enumerate(parsed_texts)
        if text
    ]
    return {
        "text": extracted_text,
        "fields": {},
        "line_items": [],
        "page_count": len(parsed_texts) or 1,
        "pages": pages,
        "chunks": [
            {
                "index": 1,
                "start_page": 1,
                "end_page": len(parsed_texts) or 1,
                "page_count": len(parsed_texts) or 1,
                "status": "succeeded",
            }
        ],
        "successful_chunks": [1],
        "failed_chunks": [],
        "unprocessed_chunks": [],
        "processor": "OCR.space OCR API",
        "provider": "ocr_space",
    }


def process_pdf(config, content, filename, progress_callback=None, request_guard=None):
    _require_api_key(config)
    chunks = split_pdf_chunks(content)
    page_count = sum(chunk["page_count"] for chunk in chunks)
    pages = [
        {"page": page, "status": "not_attempted", "text": ""}
        for page in range(1, page_count + 1)
    ]
    successful_chunks = []
    failed_chunks = []
    completed_pages = 0
    completed_chunks = 0
    error_message = None

    def report_progress(current_chunk=None):
        if progress_callback is None:
            return
        progress_callback(
            {
                "total_pages": page_count,
                "completed_pages": completed_pages,
                "successful_pages": sum(page["status"] == "succeeded" for page in pages),
                "total_chunks": len(chunks),
                "completed_chunks": completed_chunks,
                "successful_chunks": list(successful_chunks),
                "failed_chunks": list(failed_chunks),
                "current_chunk": current_chunk,
            }
        )

    report_progress()
    for offset, chunk in enumerate(chunks):
        chunk["status"] = "processing"
        report_progress(chunk["index"])
        chunk_name = (
            f"{Path(filename).stem}_pages_{chunk['start_page']}-{chunk['end_page']}.pdf"
        )
        try:
            parsed_texts = _request_parsed_texts(
                config,
                chunk["content"],
                chunk_name,
                "application/pdf",
                request_guard=request_guard,
            )
            if len(parsed_texts) != chunk["page_count"]:
                error_message = (
                    f"OCR.space returned {len(parsed_texts)} page result(s) for chunk "
                    f"{chunk['index']}; expected {chunk['page_count']}."
                )
            for page_offset in range(chunk["page_count"]):
                page_number = chunk["start_page"] + page_offset
                text = parsed_texts[page_offset] if page_offset < len(parsed_texts) else ""
                page_result = pages[page_number - 1]
                page_result["text"] = text
                if text:
                    page_result["status"] = "succeeded"
                else:
                    page_result["status"] = "failed"
                    page_result["error"] = (
                        "OCR.space returned no text for this page."
                        if page_offset < len(parsed_texts)
                        else "OCR.space returned no result for this page."
                    )
                    if error_message is None:
                        error_message = page_result["error"]
        except OCRSpaceConfigurationError:
            raise
        except OCRSpaceProcessingError as error:
            error_message = str(error)
            for page_number in range(chunk["start_page"], chunk["end_page"] + 1):
                page_result = pages[page_number - 1]
                page_result["status"] = "failed"
                page_result["error"] = error_message

        chunk["status"] = "failed" if error_message else "succeeded"
        if error_message:
            chunk["error"] = error_message
            failed_chunks.append(chunk["index"])
        else:
            successful_chunks.append(chunk["index"])

        completed_pages += chunk["page_count"]
        completed_chunks += 1
        report_progress()
        chunk["content"] = b""

        if error_message:
            for unprocessed in chunks[offset + 1:]:
                unprocessed["status"] = "not_attempted"
                for page_number in range(
                    unprocessed["start_page"], unprocessed["end_page"] + 1
                ):
                    pages[page_number - 1]["error"] = (
                        f"Not attempted because chunk {chunk['index']} failed."
                    )
            break

    combined_text = "\n\n".join(
        f"--- Page {page['page']} ---\n{page['text']}"
        for page in pages
        if page["status"] == "succeeded"
    )
    chunk_results = [
        {key: value for key, value in chunk.items() if key != "content"}
        for chunk in chunks
    ]
    result = {
        "text": combined_text,
        "fields": {},
        "line_items": [],
        "page_count": page_count,
        "pages": pages,
        "chunks": chunk_results,
        "successful_chunks": successful_chunks,
        "failed_chunks": failed_chunks,
        "unprocessed_chunks": [
            chunk["index"] for chunk in chunks if chunk["status"] == "not_attempted"
        ],
        "processor": "OCR.space OCR API",
        "provider": "ocr_space",
    }
    report_progress()
    return result, error_message
