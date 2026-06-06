"""Persistencia de reportes de texto (historial por usuaria).

A diferencia de snapshots/demografía, los reportes se ACUMULAN: cada generación
agrega una fila. La lectura siempre se filtra por ``user_id`` (sin filtraciones
entre usuarias).
"""

from ..db import get_db


def save_report(user, content, period_label, model):
    """Inserta un reporte nuevo para la usuaria (no reemplaza: acumula)."""
    db = get_db()
    db.execute(
        "INSERT INTO reports (user_id, period_label, model, content)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], period_label, model, content),
    )
    db.commit()


def latest_reports(user_id, limit=10):
    """Reportes de la usuaria, más nuevo primero (acotado a ``limit``)."""
    return (
        get_db()
        .execute(
            "SELECT id, period_label, model, content, generado_en"
            " FROM reports WHERE user_id = ?"
            " ORDER BY generado_en DESC, id DESC LIMIT ?",
            (user_id, limit),
        )
        .fetchall()
    )
