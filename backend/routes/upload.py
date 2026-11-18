import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from backend.database import db
from backend.services.document_ai import (
    DocumentAIConfigurationError,
    DocumentAIProcessingError,
    is_configured,
    process_invoice,
)
from backend.services.extraction import extract_document_data
from backend.services.ocr_space import (
    OCR_SPACE_DAILY_REQUEST_BUDGET,
    OCR_SPACE_MONTHLY_REQUEST_BUDGET,
    OCRSpaceConfigurationError,
    OCRSpaceProcessingError,
    extract_text,
    is_configured as is_ocr_space_configured,
    pdf_page_count,
    process_pdf,
)

upload_bp = Blueprint("upload", __name__)


def _detect_type(content):
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


@upload_bp.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_error):
    return jsonify({"error": "The file exceeds the 15 MB upload limit."}), 413


@upload_bp.post("/api/upload")
def upload_document():
    provider = request.form.get("provider", "google").strip().lower()
    if provider not in {"google", "ocr_space"}:
        return jsonify({"error": "Unsupported processing provider."}), 400

    file = request.files.get("document")
    if file is None or not file.filename:
        return jsonify({"error": "Choose a PDF, PNG, or JPG document to upload."}), 400

    original_name = secure_filename(file.filename)
    if not original_name:
        return jsonify({"error": "The uploaded filename is invalid."}), 400
    extension = Path(original_name).suffix.lower()
    expected_mime = current_app.config["ALLOWED_MIME_TYPES"].get(extension)
    if not expected_mime:
        return jsonify({"error": "Unsupported file type. Upload a PDF, PNG, or JPG."}), 415

    content = file.read(current_app.config["MAX_UPLOAD_SIZE"] + 1)
    if not content:
        return jsonify({"error": "The uploaded document is empty."}), 400
    if len(content) > current_app.config["MAX_UPLOAD_SIZE"]:
        return jsonify({"error": "The file exceeds the 15 MB upload limit."}), 413

    detected_mime = _detect_type(content)
    if detected_mime != expected_mime:
        return jsonify(
            {"error": "The file content does not match its PDF, PNG, or JPG extension."}
        ), 415
    supplied_mime = file.mimetype
    if supplied_mime and supplied_mime not in (expected_mime, "application/octet-stream"):
        return jsonify({"error": "The uploaded file MIME type does not match its extension."}), 415

    requested_id = request.form.get("document_id", "").strip()
    if requested_id:
        try:
            document_id = str(uuid.UUID(requested_id))
        except ValueError:
            return jsonify({"error": "The document ID is invalid."}), 400
        if db.get_document(current_app.config["DATABASE_PATH"], document_id):
            return jsonify({"error": "The document ID is already in use."}), 409
    else:
        document_id = str(uuid.uuid4())

    stored_path = Path(current_app.config["UPLOAD_FOLDER"]) / f"{document_id}{extension}"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(content)
    document = {
        "id": document_id,
        "original_name": original_name,
        "stored_path": str(stored_path),
        "status": "processing",
        "document_type": "Invoice" if provider == "google" else "Document",
        "mime_type": expected_mime,
        "file_size": len(content),
        "progress": {
            "total_pages": 0,
            "completed_pages": 0,
            "successful_pages": 0,
            "total_chunks": 0,
            "completed_chunks": 0,
            "successful_chunks": [],
            "failed_chunks": [],
            "current_chunk": None,
        },
    }
    db.create_document(current_app.config["DATABASE_PATH"], document)

    if provider == "ocr_space":
        if not is_ocr_space_configured(current_app.config):
            error_message = (
                "OCR.space is not configured. Set OCR_SPACE_API_KEY in the root .env file."
            )
            db.update_document(
                current_app.config["DATABASE_PATH"],
                document_id,
                "failed",
                error_message=error_message,
            )
            return jsonify({"id": document_id, "error": error_message}), 503

        try:
            request_guard = lambda: db.reserve_ocr_space_request(
                current_app.config["DATABASE_PATH"],
                OCR_SPACE_DAILY_REQUEST_BUDGET,
                OCR_SPACE_MONTHLY_REQUEST_BUDGET,
            )
            if expected_mime == "application/pdf":
                total_pages = pdf_page_count(content)
                db.update_progress(
                    current_app.config["DATABASE_PATH"],
                    document_id,
                    {
                        "total_pages": total_pages,
                        "completed_pages": 0,
                        "successful_pages": 0,
                        "total_chunks": 0,
                        "completed_chunks": 0,
                        "successful_chunks": [],
                        "failed_chunks": [],
                        "current_chunk": None,
                    },
                )
                result, processing_error = process_pdf(
                    current_app.config,
                    content,
                    original_name,
                    progress_callback=lambda progress: db.update_progress(
                        current_app.config["DATABASE_PATH"], document_id, progress
                    ),
                    request_guard=request_guard,
                )
            else:
                result = extract_text(
                    current_app.config,
                    content,
                    original_name,
                    expected_mime,
                    request_guard=request_guard,
                )
                page_count = result["page_count"]
                db.update_progress(
                    current_app.config["DATABASE_PATH"],
                    document_id,
                    {
                        "total_pages": page_count,
                        "completed_pages": page_count,
                        "successful_pages": page_count,
                        "total_chunks": 1,
                        "completed_chunks": 1,
                        "successful_chunks": [1],
                        "failed_chunks": [],
                        "current_chunk": None,
                    },
                )
                processing_error = None

            if processing_error:
                db.update_document(
                    current_app.config["DATABASE_PATH"],
                    document_id,
                    "failed",
                    result=result,
                    error_message=processing_error,
                )
                return jsonify(
                    {
                        "id": document_id,
                        "status": "failed",
                        "error": processing_error,
                        "result": result,
                    }
                ), 502

            db.update_document(
                current_app.config["DATABASE_PATH"], document_id, "succeeded", result=result
            )
            return jsonify({"id": document_id, "status": "succeeded", "result": result}), 201
        except OCRSpaceConfigurationError as error:
            db.update_document(
                current_app.config["DATABASE_PATH"],
                document_id,
                "failed",
                error_message=str(error),
            )
            return jsonify({"id": document_id, "error": str(error)}), 503
        except OCRSpaceProcessingError as error:
            db.update_document(
                current_app.config["DATABASE_PATH"],
                document_id,
                "failed",
                error_message=str(error),
            )
            return jsonify({"id": document_id, "error": str(error)}), 502
        except Exception:
            current_app.logger.exception("Unexpected OCR.space processing failure for %s", document_id)
            error_message = "An unexpected processing error occurred. Check the server log for details."
            db.update_document(
                current_app.config["DATABASE_PATH"],
                document_id,
                "failed",
                error_message=error_message,
            )
            return jsonify({"id": document_id, "error": error_message}), 500

    if not is_configured(current_app.config):
        error_message = (
            "Google Cloud Document AI is not configured. Set GOOGLE_CLOUD_PROJECT, "
            "GOOGLE_CLOUD_LOCATION, GOOGLE_CLOUD_PROCESSOR_ID, and Google application credentials."
        )
        db.update_document(
            current_app.config["DATABASE_PATH"], document_id, "failed", error_message=error_message
        )
        return jsonify({"id": document_id, "error": error_message}), 503

    try:
        cloud_document = process_invoice(current_app.config, content, expected_mime)
        if not cloud_document.text and not cloud_document.entities:
            raise DocumentAIProcessingError(
                "Document AI returned no text or entities. The document may be blank or unreadable."
            )
        result = extract_document_data(cloud_document)
        db.update_document(
            current_app.config["DATABASE_PATH"], document_id, "succeeded", result=result
        )
        return jsonify({"id": document_id, "status": "succeeded", "result": result}), 201
    except DocumentAIConfigurationError as error:
        db.update_document(
            current_app.config["DATABASE_PATH"], document_id, "failed", error_message=str(error)
        )
        return jsonify({"id": document_id, "error": str(error)}), 503
    except DocumentAIProcessingError as error:
        db.update_document(
            current_app.config["DATABASE_PATH"], document_id, "failed", error_message=str(error)
        )
        return jsonify({"id": document_id, "error": str(error)}), 502
    except Exception:
        current_app.logger.exception("Unexpected Document AI processing failure for %s", document_id)
        error_message = "An unexpected processing error occurred. Check the server log for details."
        db.update_document(
            current_app.config["DATABASE_PATH"], document_id, "failed", error_message=error_message
        )
        return jsonify({"id": document_id, "error": error_message}), 500
