from flask import Flask, jsonify, send_from_directory

from backend.config import Config
from backend.database.db import initialize_database
from backend.routes.analytics import analytics_bp
from backend.routes.documents import documents_bp
from backend.routes.upload import upload_bp
from backend.services.document_ai import is_configured


def create_app(config_object=Config):
    app = Flask(
        __name__,
        static_folder="../frontend",
        static_url_path="/assets",
    )
    app.config.from_object(config_object)
    app.config["UPLOAD_FOLDER"] = str(app.config["UPLOAD_FOLDER"])
    app.config["DATABASE_PATH"] = str(app.config["DATABASE_PATH"])
    initialize_database(app.config["DATABASE_PATH"])

    app.register_blueprint(upload_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(analytics_bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/status")
    def status():
        return jsonify(
            {
                "service": "AI-Based Smart Document Processing System",
                "document_ai_configured": is_configured(app.config),
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
