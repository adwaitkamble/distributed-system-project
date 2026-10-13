"""Standardized JSON error handlers and custom exceptions for the REST API bridge."""

import logging
from flask import jsonify

logger = logging.getLogger(__name__)


def make_error_response(error_code: str, message: str, status_code: int = 400, **kwargs):
    """Return a uniform JSON error response."""
    payload = {
        "success": False,
        "error": error_code,
        "message": message,
    }
    payload.update(kwargs)
    return jsonify(payload), status_code


def register_error_handlers(app):
    """Register standard HTTP error handlers on Flask application."""

    @app.errorhandler(400)
    def bad_request(e):
        msg = getattr(e, "description", "Bad request")
        return make_error_response("bad_request", str(msg), 400)

    @app.errorhandler(404)
    def not_found(e):
        msg = getattr(e, "description", "Resource not found")
        return make_error_response("not_found", str(msg), 404)

    @app.errorhandler(405)
    def method_not_allowed(e):
        return make_error_response("method_not_allowed", "HTTP method not allowed for this endpoint", 405)

    @app.errorhandler(409)
    def conflict(e):
        msg = getattr(e, "description", "Conflict with current state")
        return make_error_response("conflict", str(msg), 409)

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("Unhandled 500 server error: %s", e)
        return make_error_response("internal_error", "An internal server error occurred", 500)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e):
        logger.exception("Unexpected exception caught by API bridge: %s", e)
        return make_error_response("internal_error", "An unexpected server error occurred", 500)
