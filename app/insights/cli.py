"""Comando CLI ``flask fetch-insights``.

Punto de entrada manual para probar la bajada ahora; la automatización por cron
es otra spec (Fase 3). Baja, de forma defensiva, los insights de cada usuaria
guardada y los persiste en ``account_snapshots`` y ``post_metrics``.
"""

import click
from flask.cli import with_appcontext

from . import fetch
from .fetch import InsightsError, RateLimitError
from .store import save_account_snapshot, save_post_metrics
from ..db import get_db


@click.command("fetch-insights")
@with_appcontext
def fetch_insights_command():
    users = get_db().execute("SELECT * FROM usuarias").fetchall()
    if not users:
        click.echo("No hay usuarias en la base.")
        return

    for user in users:
        try:
            # Resolver la cuenta IG una sola vez por usuaria (rate limit).
            ig_id = fetch.resolve_ig_account(user)

            save_account_snapshot(user, fetch.fetch_account_insights(user, ig_id))

            posts = []
            for media in fetch.fetch_media_list(user, ig_id):
                insights = fetch.fetch_media_insights(
                    user, media.get("id"), media.get("media_type")
                )
                posts.append(fetch.normalize_post(media, insights))
            save_post_metrics(user, posts)

            click.echo(f"OK usuaria {user['id']}: cuenta + {len(posts)} posts")
        except RateLimitError:
            click.echo(
                "Límite de solicitudes de Meta alcanzado; abortando sin reintentos."
            )
            break
        except InsightsError as exc:
            click.echo(f"Falló la bajada para la usuaria {user['id']}: {exc}")


def init_app(app):
    app.cli.add_command(fetch_insights_command)
