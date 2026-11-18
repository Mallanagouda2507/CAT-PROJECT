from pathlib import Path

from flask import Blueprint, current_app, jsonify

from backend.database import db

documents_bp = Blueprint("documents", __name__)


@documents_bp.get("/api/documents")
def get_documents():
    return jsonify({"documents": db.list_documents(current_app.config["DATABASE_PATH"])})


@documents_bp.get("/api/documents/<document_id>")
def get_document(document_id):
    document = db.get_document(current_app.config["DATABASE_PATH"], document_id)
    if document is None:
        return jsonify({"error": "Document not found."}), 404
    return jsonify({"document": document})


@documents_bp.delete("/api/documents/<document_id>")
def remove_document(document_id):
    stored_path = db.delete_document(current_app.config["DATABASE_PATH"], document_id)
    if stored_path is None:
        return jsonify({"error": "Document not found."}), 404
    Path(stored_path).unlink(missing_ok=True)
    return jsonify({"deleted": True})
