"""Comando CLI ``flask generate-monthly-report``.

Genera (y persiste) un reporte mensual descriptivo por usuaria, etiquetado con
el mes ANTERIOR (el cron corre a principios de mes y reporta el mes cerrado).
Pensado para el cron mensual del deploy. Es defensivo: si una usuaria falla
(clave ausente, API caída), se avisa y se sigue con las demás.
"""

import click
from flask import current_app
from flask.cli import with_appcontext

from . import generate
from .generate import DEFAULT_REPORT_MODEL, ReportError
from ..db import get_db


@click.command("generate-monthly-report")
@with_appcontext
def generate_monthly_report_command():
    """Genera el reporte mensual de cada usuaria con la API de Claude."""
    cfg = current_app.config
    api_key = cfg.get("ANTHROPIC_API_KEY")
    model = cfg.get("REPORT_MODEL") or DEFAULT_REPORT_MODEL
    period = generate.previous_month_label()

    users = get_db().execute("SELECT * FROM usuarias").fetchall()
    if not users:
        click.echo("No hay usuarias en la base.")
        return

    for user in users:
        try:
            generate.generate_and_save_report(
                user, period_label=period, api_key=api_key, model=model
            )
            click.echo(f"OK reporte usuaria {user['id']} ({period}).")
        except ReportError as exc:
            # exc es siempre un mensaje genérico y seguro (sin clave ni detalle).
            click.echo(f"Falló el reporte de la usuaria {user['id']}: {exc}")


def init_app(app):
    app.cli.add_command(generate_monthly_report_command)
