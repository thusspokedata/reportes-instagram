"""Generación del reporte de texto con la API de Claude (Messages API).

El flujo es deliberadamente simple y defensivo:

1. ``build_report_input`` arma un payload **agregado y anónimo** a partir de la
   base, aplicando los MISMOS guardrails que el dashboard (medianas, NULL≠0,
   top-N, gate de muestra N≥12). Reutiliza esos cálculos para no duplicarlos.
   A Claude se le mandan SOLO métricas agregadas: nunca tokens ni IDs internos.
2. ``generate_report_text`` hace UNA llamada a la Messages API con un system
   prompt de guardrails duros (descriptivo, sin causalidad, honesto sobre los
   límites, NULL = sin dato). Es defensiva: si falta la clave o la API falla,
   levanta ``ReportError`` con un mensaje genérico (nunca filtra la clave ni el
   detalle del SDK) y la app degrada con elegancia.
3. ``generate_and_save_report`` orquesta: lee la base, arma el input, llama al
   modelo y persiste el reporte (historial).

La ``ANTHROPIC_API_KEY`` viene de la config (entorno); nunca se loguea ni se
expone en HTML. El SDK ``anthropic`` se importa de forma perezosa para que los
tests (que inyectan un cliente de mentira) no dependan del paquete instalado.
"""

import json
import logging
from datetime import date

from ..db import get_db
from .store import save_report

logger = logging.getLogger(__name__)

# Modelo por defecto si REPORT_MODEL no está seteado. El más económico para esta
# tarea descriptiva (verificado contra el catálogo de modelos vigente).
DEFAULT_REPORT_MODEL = "claude-haiku-4-5"

# Tope de salida: un reporte en prosa de 2-4 párrafos entra holgado. Muy por
# debajo del umbral que exigiría streaming, así que la llamada es no-stream.
MAX_TOKENS = 2000

# Etiqueta de período para los reportes a pedido (vs. "2026-05" del mensual).
ON_DEMAND_LABEL = "a pedido"

# Guardrails DUROS. El modelo describe; no infiere causas ni inventa números.
SYSTEM_PROMPT = (
    "Sos un analista de redes sociales que redacta un reporte BREVE y "
    "DESCRIPTIVO en español rioplatense (claro, sobrio, sin hype) sobre las "
    "métricas de una cuenta de Instagram Business.\n\n"
    "Reglas estrictas (no negociables):\n"
    "1. DESCRIPTIVO, no prescriptivo: describí lo que muestran los datos. NO "
    "afirmes relaciones de causa-efecto (nada de \"creció PORQUE...\"). No "
    "infieras motivos.\n"
    "2. Honestidad sobre los límites: si \"muestra_suficiente\" es false (hay "
    "menos de \"muestra_minima\" posts), decilo explícitamente y NO saques "
    "conclusiones inferenciales (mejores horarios, qué tipo de contenido "
    "conviene, tendencias). Con pocos datos, sólo describí lo que hay. Además, "
    "el campo \"reach_por_tipo\" trae un \"n\" (cantidad de posts de ese tipo): "
    "aunque \"muestra_suficiente\" sea true a nivel cuenta, NO compares ni "
    "rankees tipos de contenido cuando algún \"n\" por tipo es chico (menor a "
    "\"muestra_minima\"). Describí cada tipo por separado sin afirmar cuál "
    "'rinde mejor'.\n"
    "3. NULL = sin dato. Un valor null/None significa que Meta no lo reportó: "
    "NO lo trates como 0 ni como \"cero seguidores/reach\". Si falta, decí "
    "\"sin dato\".\n"
    "4. Usá SOLO los números provistos en el JSON. No inventes métricas, "
    "porcentajes, comparaciones temporales ni datos que no estén. Distinguí "
    "\"reach_ultimo_dia\" (alcance del último día registrado, a nivel cuenta) de "
    "\"medianas.reach\" (mediana de alcance por publicación): son métricas "
    "distintas, no las sumes ni las compares entre sí.\n"
    "5. La demografía es agregada, anónima y con ~48h de delay; con audiencia "
    "chica (sobre todo a nivel ciudad) puede no ser representativa. Mencionala "
    "como referencia, no como verdad absoluta. No nombres seguidores ni "
    "personas (la API no expone identidades).\n\n"
    "Formato: 2 a 4 párrafos cortos en TEXTO PLANO (sin markdown, sin viñetas, "
    "sin títulos, sin tablas). No incluyas el JSON ni código en la respuesta."
)


class ReportError(Exception):
    """Falla controlada al generar un reporte (clave ausente, API caída, etc.).

    El mensaje es siempre genérico y seguro de mostrar: nunca contiene la clave
    ni el detalle interno del SDK.
    """


def build_report_input(snapshot, posts, demo_rows):
    """Arma el payload AGREGADO y anónimo para el modelo.

    Reutiliza los builders del dashboard para aplicar exactamente los mismos
    guardrails (medianas ignorando NULL, NULL≠0, top-N con "Otros", gate de
    muestra). Se EXCLUYE a propósito la lista por-post (que llevaría labels
    derivados del media_id): a Claude sólo le llegan agregados, sin IDs.
    """
    # Import perezoso para evitar un ciclo con el blueprint del dashboard.
    from ..routes.dashboard import build_dashboard_data, build_demographics

    data = build_dashboard_data(snapshot, posts)
    return {
        "seguidores": data["summary"]["followers"],
        "reach_ultimo_dia": data["summary"]["reach"],
        "cantidad_posts": data["summary"]["posts"],
        "medianas": data["medians"],
        "reach_por_tipo": data["reach_by_type"],
        "muestra_suficiente": data["enough_sample"],
        "muestra_minima": data["min_sample"],
        "demografia": build_demographics(demo_rows),
    }


def _user_prompt(report_input):
    """Mensaje de usuario: instrucción + datos agregados como JSON (ordenado)."""
    datos = json.dumps(report_input, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "Generá el reporte descriptivo a partir de estos datos agregados de la "
        "cuenta. Respetá las reglas del sistema al pie de la letra.\n\n"
        f"Datos (JSON):\n{datos}"
    )


def generate_report_text(report_input, *, api_key, model, client=None):
    """Hace UNA llamada a la Messages API y devuelve el reporte en prosa.

    ``client`` se puede inyectar (tests); en producción se construye con
    ``anthropic.Anthropic(api_key=...)``. Levanta ``ReportError`` —con mensaje
    genérico— si falta la clave, si la API falla o si la respuesta viene vacía.
    """
    if not api_key:
        raise ReportError("Falta configurar ANTHROPIC_API_KEY.")

    if client is None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - el SDK está en requirements
            raise ReportError("El SDK de Anthropic no está instalado.") from exc
        client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            # El system prompt es el prefijo estable: se marca cacheable (sólo
            # tiene efecto por encima del mínimo del modelo; es inocuo si no).
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _user_prompt(report_input)}],
        )
    except Exception as exc:  # noqa: BLE001 - frontera de degradación defensiva
        # Logueamos sólo el TIPO de error (nunca el mensaje, que podría contener
        # la clave) y devolvemos un texto genérico al caller.
        logger.warning(
            "Falló la generación del reporte con Claude: %s", type(exc).__name__
        )
        raise ReportError("No se pudo generar el reporte ahora mismo.") from exc

    parts = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    ]
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        raise ReportError("La respuesta del modelo vino vacía.")
    return text


def generate_and_save_report(user, *, period_label, api_key, model, client=None):
    """Lee la base, genera el reporte y lo persiste. Devuelve el texto.

    Propaga ``ReportError`` si la generación falla; en ese caso NO se persiste
    nada (el caller decide cómo avisar: CLI imprime, ruta muestra un flash).
    """
    db = get_db()
    user_id = user["id"]
    snapshot = db.execute(
        "SELECT follower_count, reach FROM account_snapshots"
        " WHERE user_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    posts = db.execute(
        "SELECT media_id, media_type, timestamp, likes, comments, reach"
        " FROM post_metrics WHERE user_id = ? ORDER BY timestamp",
        (user_id,),
    ).fetchall()
    demo_rows = db.execute(
        "SELECT breakdown, bucket, value FROM audience_demographics WHERE user_id = ?",
        (user_id,),
    ).fetchall()

    report_input = build_report_input(snapshot, posts, demo_rows)
    text = generate_report_text(
        report_input, api_key=api_key, model=model, client=client
    )
    save_report(user, text, period_label, model)
    return text


def previous_month_label(today=None):
    """Etiqueta "YYYY-MM" del mes anterior a ``today`` (default: hoy)."""
    today = today or date.today()
    year, month = today.year, today.month
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    return f"{year:04d}-{month:02d}"
