"""Main blueprint: health check and other top-level routes."""

from flask import Blueprint, jsonify

bp = Blueprint("main", __name__)


@bp.route("/health")
def health():
    """Liveness probe. Returns 200 with a small JSON body."""
    return jsonify({"status": "ok"})
