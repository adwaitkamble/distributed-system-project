"""Flask REST bridge application factory for Distributed Fault-Tolerant Voting System."""

import logging
import os
from typing import Optional
from flask import Flask, send_from_directory
from flask_cors import CORS

from api.errors import register_error_handlers
from api.routes import bp as api_bp

logger = logging.getLogger(__name__)


def create_app(runtime=None, test_config: Optional[dict] = None) -> Flask:
    """Create and configure the Flask REST bridge application."""
    dist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
    static_folder = dist_dir if os.path.exists(dist_dir) else None

    app = Flask(__name__, static_folder=static_folder, static_url_path="")

    # Default configuration
    app.config["JSON_SORT_KEYS"] = False
    app.config["RUNTIME"] = runtime

    if test_config:
        app.config.update(test_config)

    # Enable CORS for React frontend (supports localhost, Vite dev server, etc.)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register standardized error handlers and routes
    register_error_handlers(app)
    app.register_blueprint(api_bp)

    # If production frontend build exists, serve it
    if static_folder:
        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_frontend(path):
            if path and not path.startswith("api"):
                target = os.path.join(dist_dir, path)
                if os.path.exists(target) and os.path.isfile(target):
                    return send_from_directory(dist_dir, path)
            return send_from_directory(dist_dir, "index.html")

    return app
