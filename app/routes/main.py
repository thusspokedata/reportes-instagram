"""Main blueprint: health check and other top-level routes."""

from flask import Blueprint, jsonify, redirect, url_for

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    """Raíz: redirige al dashboard (que a su vez manda a login si no hay sesión).

    Evita el 404 del dominio pelado: no hay landing propia, el punto de entrada
    es el dashboard / login.
    """
    return redirect(url_for("dashboard.dashboard"))


@bp.route("/health")
def health():
    """Liveness probe. Returns 200 with a small JSON body."""
    return jsonify({"status": "ok"})
