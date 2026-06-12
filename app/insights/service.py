"""Bajada on-demand: refresca el snapshot de cuenta + la demografía de una
usuaria en una sola pasada (resuelve la cuenta IG una vez).

Lo usa el botón "Actualizar datos" del dashboard. La captura del snapshot vive
acá (y la reusa el CLI) para no duplicar el guardrail de ``follower_count`` (que
sale del PERFIL, no del delta de insights).

Es liviano a propósito: NO re-baja los posts (eso es ``fetch-insights``, mucho
más pesado). Propaga ``RateLimitError`` / ``InsightsError`` para que el caller
decida cómo avisar.
"""

from . import fetch
from .store import save_account_snapshot, save_demographics


def capture_account_snapshot(user, ig_id):
    """Baja perfil + insights de cuenta y guarda el snapshot del día.

    Idempotente por ``(user_id, snapshot_date)``. ``follower_count`` viene del
    perfil (``followers_count``), no de la métrica de insights (que es un delta).
    Devuelve el perfil (el CLI lo usa para validar ``media_count``).
    """
    profile = fetch.fetch_profile(user, ig_id)
    account = fetch.fetch_account_insights(user, ig_id)
    account["follower_count"] = profile.get("followers_count")
    save_account_snapshot(user, account)
    return profile


def refresh_account_data(user):
    """Refresca snapshot de cuenta + demografía en una pasada.

    Resuelve la cuenta IG una sola vez y la reusa. No toca los posts.
    """
    ig_id = fetch.resolve_ig_account(user)
    capture_account_snapshot(user, ig_id)
    save_demographics(user, fetch.fetch_demographics(user, ig_id))
