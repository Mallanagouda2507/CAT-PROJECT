from flask import Blueprint, current_app, jsonify

from backend.database import db

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.get("/api/analytics")
def get_analytics():
    return jsonify(db.analytics(current_app.config["DATABASE_PATH"]))
