import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "local-development-only")
    MAX_UPLOAD_SIZE = 15 * 1024 * 1024
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE + 1024 * 1024
    UPLOAD_FOLDER = PROJECT_ROOT / "uploads"
    DATABASE_PATH = PROJECT_ROOT / "processed" / "documents.sqlite3"
    GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
    GOOGLE_CLOUD_PROCESSOR_ID = os.getenv("GOOGLE_CLOUD_PROCESSOR_ID", "").strip()
    OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_API_KEY", "").strip()
    ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
    ALLOWED_MIME_TYPES = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
