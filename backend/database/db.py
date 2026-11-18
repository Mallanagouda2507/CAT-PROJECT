import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


@contextmanager
def connect(database_path):
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path):
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                stored_path TEXT,
                uploaded_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('processing', 'succeeded', 'failed')),
                document_type TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                result_json TEXT,
                error_message TEXT,
                progress_json TEXT
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "progress_json" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN progress_json TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ocr_space_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requested_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ocr_space_requests_requested_at "
            "ON ocr_space_requests(requested_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_uploaded_at ON documents(uploaded_at DESC)"
        )


def create_document(database_path, document):
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO documents (
                id, original_name, stored_path, uploaded_at, status, document_type,
                mime_type, file_size, result_json, error_message, progress_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document["id"],
                document["original_name"],
                document.get("stored_path"),
                datetime.now(timezone.utc).isoformat(),
                document["status"],
                document["document_type"],
                document["mime_type"],
                document["file_size"],
                json.dumps(document.get("result")) if document.get("result") is not None else None,
                document.get("error_message"),
                json.dumps(document.get("progress"))
                if document.get("progress") is not None
                else None,
            ),
        )


def update_document(database_path, document_id, status, result=None, error_message=None):
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE documents
            SET status = ?, result_json = ?, error_message = ?
            WHERE id = ?
            """,
            (
                status,
                json.dumps(result) if result is not None else None,
                error_message,
                document_id,
            ),
        )


def update_progress(database_path, document_id, progress):
    with connect(database_path) as connection:
        connection.execute(
            "UPDATE documents SET progress_json = ? WHERE id = ?",
            (json.dumps(progress), document_id),
        )


def reserve_ocr_space_request(database_path, daily_limit, monthly_limit):
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    month = day[:7]
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM ocr_space_requests WHERE requested_at < ?",
            (f"{month}-01T00:00:00+00:00",),
        )
        daily_count = connection.execute(
            "SELECT COUNT(*) FROM ocr_space_requests WHERE substr(requested_at, 1, 10) = ?",
            (day,),
        ).fetchone()[0]
        monthly_count = connection.execute(
            "SELECT COUNT(*) FROM ocr_space_requests WHERE substr(requested_at, 1, 7) = ?",
            (month,),
        ).fetchone()[0]
        if daily_count >= daily_limit or monthly_count >= monthly_limit:
            return False
        connection.execute(
            "INSERT INTO ocr_space_requests(requested_at) VALUES (?)",
            (now.isoformat(),),
        )
        return True


def _serialize(row, include_result=False):
    document = dict(row)
    if include_result:
        document["result"] = json.loads(document.pop("result_json")) if document["result_json"] else None
    else:
        document.pop("result_json", None)
    progress_json = document.pop("progress_json", None)
    document["progress"] = json.loads(progress_json) if progress_json else None
    document.pop("stored_path", None)
    return document


def list_documents(database_path, limit=100):
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, original_name, uploaded_at, status, document_type, mime_type,
                   file_size, result_json, error_message, progress_json
            FROM documents ORDER BY uploaded_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_serialize(row) for row in rows]


def get_document(database_path, document_id):
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    return _serialize(row, include_result=True) if row else None


def delete_document(database_path, document_id):
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if not row:
            return None
        connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return row["stored_path"]


def analytics(database_path):
    with connect(database_path) as connection:
        totals = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM documents
            """
        ).fetchone()
        by_type = connection.execute(
            """
            SELECT document_type AS type, COUNT(*) AS count
            FROM documents GROUP BY document_type ORDER BY count DESC
            """
        ).fetchall()
        daily = connection.execute(
            """
            SELECT substr(uploaded_at, 1, 10) AS date, COUNT(*) AS count
            FROM documents
            WHERE substr(uploaded_at, 1, 10) >= date('now', '-6 days')
            GROUP BY substr(uploaded_at, 1, 10) ORDER BY date
            """
        ).fetchall()
    return {
        "total": totals["total"] or 0,
        "succeeded": totals["succeeded"] or 0,
        "failed": totals["failed"] or 0,
        "success_rate": round((totals["succeeded"] or 0) * 100 / totals["total"], 1)
        if totals["total"]
        else 0,
        "by_type": [dict(row) for row in by_type],
        "daily": [dict(row) for row in daily],
    }
