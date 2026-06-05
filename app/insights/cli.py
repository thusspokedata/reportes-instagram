"""Comandos CLI de insights.

- ``flask fetch-insights``: bajada COMPLETA (snapshot de cuenta + métricas de
  todos los posts). Más pesada; correr cuando se quieran refrescar los posts.
- ``flask daily-snapshot``: solo el snapshot de cuenta del día (liviano, sin
  re-bajar posts). Pensado para el cron diario — junta la serie de evolución
  sin gastar el rate limit (~200/h) en posts que no cambian a diario.

Ambos son defensivos y el snapshot es idempotente por día
(upsert por ``(user_id, snapshot_date)``).
"""

import click
from flask.cli import with_appcontext

from . import fetch
from .fetch import InsightsError, RateLimitError
from .store import save_account_snapshot, save_demographics, save_post_metrics
from ..db import get_db


def _capture_account_snapshot(user, ig_id):
    """Baja seguidores (perfil) + insights de cuenta y guarda el snapshot del día.

    Idempotente por ``(user_id, snapshot_date)``. Devuelve el perfil (para
    validar media_count en la bajada completa). Compartido por ambos comandos.
    """
    profile = fetch.fetch_profile(user, ig_id)
    account = fetch.fetch_account_insights(user, ig_id)
    # Seguidores del perfil (no de la métrica de insights, que es un delta).
    account["follower_count"] = profile.get("followers_count")
    save_account_snapshot(user, account)
    return profile


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
            profile = _capture_account_snapshot(user, ig_id)

            posts = []
            for media in fetch.fetch_media_list(user, ig_id):
                insights = fetch.fetch_media_insights(
                    user, media.get("id"), media.get("media_type")
                )
                posts.append(fetch.normalize_post(media, insights))
            save_post_metrics(user, posts)

            # Validar contra el conteo de posts del perfil; loguear discrepancia.
            expected = profile.get("media_count")
            if expected is not None and len(posts) != expected:
                click.echo(
                    f"  aviso: se bajaron {len(posts)} posts pero el perfil "
                    f"reporta {expected} (media_count)."
                )

            click.echo(
                f"OK usuaria {user['id']}: followers="
                f"{profile.get('followers_count')} + {len(posts)} posts"
            )
        except RateLimitError:
            click.echo(
                "Límite de solicitudes de Meta alcanzado; abortando sin reintentos."
            )
            break
        except InsightsError as exc:
            click.echo(f"Falló la bajada para la usuaria {user['id']}: {exc}")


@click.command("daily-snapshot")
@with_appcontext
def daily_snapshot_command():
    """Snapshot diario liviano: solo métricas de cuenta (sin posts)."""
    users = get_db().execute("SELECT * FROM usuarias").fetchall()
    if not users:
        click.echo("No hay usuarias en la base.")
        return

    for user in users:
        try:
            ig_id = fetch.resolve_ig_account(user)
            profile = _capture_account_snapshot(user, ig_id)
            click.echo(
                f"OK snapshot usuaria {user['id']}: "
                f"followers={profile.get('followers_count')}"
            )
        except RateLimitError:
            click.echo("Límite de solicitudes de Meta alcanzado; abortando.")
            break
        except InsightsError as exc:
            click.echo(f"Falló el snapshot para la usuaria {user['id']}: {exc}")


@click.command("fetch-demographics")
@with_appcontext
def fetch_demographics_command():
    """Baja la demografía agregada de la audiencia (género/edad/país/ciudad)."""
    users = get_db().execute("SELECT * FROM usuarias").fetchall()
    if not users:
        click.echo("No hay usuarias en la base.")
        return

    for user in users:
        try:
            ig_id = fetch.resolve_ig_account(user)
            demographics = fetch.fetch_demographics(user, ig_id)
            save_demographics(user, demographics)
            counts = {b: len(v) for b, v in demographics.items()}
            click.echo(f"OK demografía usuaria {user['id']}: {counts}")
        except RateLimitError:
            click.echo("Límite de solicitudes de Meta alcanzado; abortando.")
            break
        except InsightsError as exc:
            click.echo(f"Falló la demografía para la usuaria {user['id']}: {exc}")


def init_app(app):
    app.cli.add_command(fetch_insights_command)
    app.cli.add_command(daily_snapshot_command)
    app.cli.add_command(fetch_demographics_command)
