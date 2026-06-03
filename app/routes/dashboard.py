"""Blueprint del dashboard.

Lee las métricas de la usuaria logueada desde la base y las pasa al template
para Chart.js. Los agregados (medianas, conteos) se calculan ACÁ, en el backend,
respetando los guardrails de datos:

- NULL = ausencia (nunca 0); no se grafica como 0.
- Medianas (no promedios) para engagement de cuentas de bajo volumen.
- N >= MIN_SAMPLE para cualquier conclusión inferencial; por debajo, "datos
  insuficientes".
- Descriptivo, sin causalidad.
"""

from statistics import median

from flask import Blueprint, redirect, render_template, session, url_for

from ..db import get_db

bp = Blueprint("dashboard", __name__)

# Muestra mínima para conclusiones (horarios, recomendación por tipo, etc.).
MIN_SAMPLE = 12


def _median(values):
    """Mediana ignorando NULL (None). Devuelve None si no hay datos reales."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return median(nums)


def _post_label(post):
    """Etiqueta corta para el eje X: fecha del post o sufijo del media_id."""
    ts = post["timestamp"]
    if ts:
        return str(ts)[:10]
    media_id = post["media_id"] or ""
    return media_id[-4:] if media_id else "?"


def _reach_by_media_type(posts):
    """Reach MEDIANO por tipo de media, con el tamaño de muestra por tipo."""
    groups = {}
    for post in posts:
        groups.setdefault(post["media_type"] or "—", []).append(post["reach"])
    return [
        {"type": mtype, "median_reach": _median(reaches), "n": len(reaches)}
        for mtype, reaches in groups.items()
    ]


def build_dashboard_data(snapshot, posts):
    """Arma el dict de datos para el template (todo calculado en backend).

    ``snapshot`` puede ser None (sin snapshot todavía). Las métricas ausentes
    quedan como None y el front las muestra como "sin dato", nunca 0.
    """
    posts = list(posts)
    engagement = [
        {
            "label": _post_label(p),
            "likes": p["likes"],
            "comments": p["comments"],
            "reach": p["reach"],
        }
        for p in posts
    ]
    return {
        "summary": {
            "followers": snapshot["follower_count"] if snapshot else None,
            "reach": snapshot["reach"] if snapshot else None,
            "posts": len(posts),
        },
        "engagement": engagement,
        "reach_by_type": _reach_by_media_type(posts),
        "medians": {
            "likes": _median([p["likes"] for p in posts]),
            "comments": _median([p["comments"] for p in posts]),
            "reach": _median([p["reach"] for p in posts]),
        },
        "min_sample": MIN_SAMPLE,
        # Gatekeeper de lo inferencial: por debajo, nada concluyente.
        "enough_sample": len(posts) >= MIN_SAMPLE,
    }


@bp.route("/dashboard")
def dashboard():
    """Página del dashboard. Requiere sesión iniciada."""
    user_id = session.get("user_id")
    if not session.get("logged_in") or not user_id:
        return redirect(url_for("auth.login"))

    db = get_db()
    snapshot = db.execute(
        "SELECT follower_count, reach, views, snapshot_date FROM account_snapshots"
        " WHERE user_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    posts = db.execute(
        "SELECT media_id, media_type, permalink, caption, timestamp, likes, comments, reach"
        " FROM post_metrics WHERE user_id = ? ORDER BY timestamp",
        (user_id,),
    ).fetchall()

    data = build_dashboard_data(snapshot, posts)
    return render_template("dashboard.html", data=data)
