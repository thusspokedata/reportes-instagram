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
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..db import get_db
from ..insights import service as insights_service
from ..insights.fetch import InsightsError, RateLimitError
from ..reports import generate as reports_generate
from ..reports.store import latest_reports

bp = Blueprint("dashboard", __name__)

# Muestra mínima para conclusiones (horarios, recomendación por tipo, etc.).
MIN_SAMPLE = 12

# Demografía: etiquetas legibles y top-N por corte (resto agrupado).
GENDER_LABELS = {"F": "Femenino", "M": "Masculino", "U": "Desconocido"}
TOP_COUNTRIES = 8
TOP_CITIES = 10

# Mínimo de puntos para dibujar una línea de evolución (no se grafica 1 punto).
EVOLUTION_MIN_POINTS = 2


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


def _sorted_desc(items):
    """Ordena (bucket, value) por value desc; None al final."""
    return sorted(items, key=lambda kv: (kv[1] is None, -(kv[1] or 0)))


def _top_n(items, n, otros_label):
    """Top-N por value; el resto se agrupa en una sola barra etiquetada."""
    ordered = _sorted_desc(items)
    out = [{"label": b, "value": v} for b, v in ordered[:n]]
    rest = ordered[n:]
    if rest:
        rest_values = [v for _, v in rest if v is not None]
        # null != 0: si el resto no tiene valores reales, "Otros" es sin dato.
        out.append(
            {"label": otros_label, "value": sum(rest_values) if rest_values else None}
        )
    return out


def build_demographics(rows):
    """Arma la demografía para el template. None si todavía no hay datos.

    Agregada y anónima; país/ciudad con top-N + 'Otros' (sin recorte silencioso).
    """
    if not rows:
        return None
    by = {}
    for r in rows:
        by.setdefault(r["breakdown"], []).append((r["bucket"], r["value"]))
    return {
        "gender": [
            {"label": GENDER_LABELS.get(b, b), "value": v}
            for b, v in _sorted_desc(by.get("gender", []))
        ],
        # Los rangos etarios ("13-17".."65+") ordenan bien lexicográficamente.
        "age": [
            {"label": b, "value": v} for b, v in sorted(by.get("age", []))
        ],
        "country": _top_n(by.get("country", []), TOP_COUNTRIES, "Otros"),
        "city": _top_n(by.get("city", []), TOP_CITIES, "Otras"),
    }


def build_evolution(snapshots):
    """Serie temporal de la cuenta para los gráficos de evolución.

    ``snapshots`` son las filas ordenadas por fecha ASC (snapshot_date,
    follower_count, reach, views). Preserva ``None`` (NULL≠0: un día sin dato
    queda como hueco, nunca 0). Sólo se grafican los días que existen — no se
    inventan ceros para los faltantes. ``views`` se omite (None) si ningún día
    tiene un dato real (en muchas cuentas Meta no lo devuelve). ``enough`` es
    True con ≥2 puntos (una línea de un solo punto no se dibuja).
    """
    snapshots = list(snapshots)
    views = [s["views"] for s in snapshots]
    return {
        # snapshot_date está declarado DATE: con PARSE_DECLTYPES sqlite lo
        # devuelve como datetime.date, que tojson serializaría como un string
        # HTTP feo ("Wed, 03 Jun 2026 ..."). str() lo normaliza a ISO
        # ("2026-06-03") y es no-op si ya viene como string.
        "labels": [str(s["snapshot_date"]) for s in snapshots],
        "followers": [s["follower_count"] for s in snapshots],
        "reach": [s["reach"] for s in snapshots],
        "views": views if any(v is not None for v in views) else None,
        "enough": len(snapshots) >= EVOLUTION_MIN_POINTS,
    }


@bp.route("/dashboard")
def dashboard():
    """Página del dashboard. Requiere sesión iniciada."""
    user_id = session.get("user_id")
    if not session.get("logged_in") or not user_id:
        return redirect(url_for("auth.login"))

    db = get_db()
    # Serie completa de snapshots (ASC) para los gráficos de evolución; el
    # último elemento es el snapshot más reciente que alimenta las tarjetas.
    snapshots = db.execute(
        "SELECT snapshot_date, follower_count, reach, views FROM account_snapshots"
        " WHERE user_id = ? ORDER BY snapshot_date ASC",
        (user_id,),
    ).fetchall()
    snapshot = snapshots[-1] if snapshots else None
    # Minimización de datos: sólo las columnas que el dashboard usa
    # (caption/permalink no se renderizan, no se traen).
    posts = db.execute(
        "SELECT media_id, media_type, timestamp, likes, comments, reach"
        " FROM post_metrics WHERE user_id = ? ORDER BY timestamp",
        (user_id,),
    ).fetchall()

    demo_rows = db.execute(
        "SELECT breakdown, bucket, value FROM audience_demographics WHERE user_id = ?",
        (user_id,),
    ).fetchall()

    data = build_dashboard_data(snapshot, posts)
    data["demographics"] = build_demographics(demo_rows)
    data["evolution"] = build_evolution(snapshots)

    reports = latest_reports(user_id)
    return render_template("dashboard.html", data=data, reports=reports)


@bp.route("/actualizar", methods=["POST"])
def actualizar_datos():
    """Refresca el snapshot del día (seguidores/reach) + la demografía desde
    Meta, a pedido. Mismas defensas que /reporte: sesión + same-origin. Es
    liviano (no re-baja los posts). Degradación defensiva ante el rate limit o
    fallos de Meta: avisa con un flash y no rompe.
    """
    user_id = session.get("user_id")
    if not session.get("logged_in") or not user_id:
        return redirect(url_for("auth.login"))

    if not _same_origin_request():
        abort(403)

    user = get_db().execute(
        "SELECT * FROM usuarias WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        return redirect(url_for("auth.login"))

    try:
        insights_service.refresh_account_data(user)
        flash("Datos actualizados.", "ok")
    except RateLimitError:
        flash("Meta limitó las solicitudes; probá de nuevo en un rato.", "error")
    except InsightsError:
        flash("No se pudieron actualizar los datos ahora mismo.", "error")
    return redirect(url_for("dashboard.dashboard"))


def _same_origin_request():
    """Defensa CSRF en profundidad: el POST debe venir del propio sitio.

    Capa 1 (cookie SameSite=Lax) ya evita que un POST cross-site mande la
    cookie de sesión. Esta capa 2 valida ``Origin`` (y si falta, ``Referer``)
    contra el host de la request: un form CSRF en otro dominio llega con un
    Origin/Referer ajeno y se rechaza. Si NO viene ninguno de los dos, se
    permite (SameSite ya cubre ese caso y así no rompemos clientes que borran
    esas cabeceras por privacidad). Compara esquema+host con urlparse (no
    substring), igual que el resto del repo.
    """
    host = urlparse(request.host_url)
    origin = request.headers.get("Origin")
    if origin:
        o = urlparse(origin)
        return (o.scheme, o.netloc) == (host.scheme, host.netloc)
    referer = request.headers.get("Referer")
    if referer:
        r = urlparse(referer)
        return (r.scheme, r.netloc) == (host.scheme, host.netloc)
    return True


@bp.route("/reporte", methods=["POST"])
def generar_reporte():
    """Genera un reporte de texto a pedido y vuelve al dashboard.

    Protección CSRF en dos capas: cookie de sesión SameSite=Lax + validación
    same-origin de Origin/Referer (ver ``_same_origin_request``). Degradación
    defensiva: si falta la clave o la API de Claude falla, se avisa con un
    flash y no se rompe.
    """
    user_id = session.get("user_id")
    if not session.get("logged_in") or not user_id:
        return redirect(url_for("auth.login"))

    if not _same_origin_request():
        # Rechazo claro (no se procesa) ante un POST de origen cruzado.
        abort(403)

    user = get_db().execute(
        "SELECT * FROM usuarias WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        return redirect(url_for("auth.login"))

    cfg = current_app.config
    try:
        reports_generate.generate_and_save_report(
            user,
            period_label=reports_generate.ON_DEMAND_LABEL,
            api_key=cfg.get("ANTHROPIC_API_KEY"),
            model=cfg.get("REPORT_MODEL") or reports_generate.DEFAULT_REPORT_MODEL,
        )
        flash("Reporte generado.", "ok")
    except reports_generate.ReportError:
        # El detalle ya quedó logueado en generate (sin secretos). Al usuario,
        # un mensaje genérico y accionable.
        flash(
            "No se pudo generar el reporte ahora mismo. Probá de nuevo en un rato.",
            "error",
        )
    return redirect(url_for("dashboard.dashboard"))
