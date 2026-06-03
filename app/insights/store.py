"""Persistencia de insights: upserts de snapshots de cuenta y métricas de post.

Las métricas ausentes se guardan como NULL (nunca 0): un cero falso arruinaría
promedios y gráficos en la fase siguiente.
"""

from datetime import date

from ..db import get_db


def save_account_snapshot(user, data: dict, snapshot_date=None):
    """Upsert del snapshot diario de cuenta (uno por usuaria por día).

    Correr dos veces el mismo día actualiza la fila, no la duplica.
    """
    if snapshot_date is None:
        snapshot_date = date.today().isoformat()

    db = get_db()
    db.execute(
        """
        INSERT INTO account_snapshots
            (user_id, snapshot_date, views, reach, follower_count,
             reposts, accounts_engaged, total_interactions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, snapshot_date) DO UPDATE SET
            views              = excluded.views,
            reach              = excluded.reach,
            follower_count     = excluded.follower_count,
            reposts            = excluded.reposts,
            accounts_engaged   = excluded.accounts_engaged,
            total_interactions = excluded.total_interactions,
            actualizado_en     = CURRENT_TIMESTAMP
        """,
        (
            user["id"],
            snapshot_date,
            data.get("views"),
            data.get("reach"),
            data.get("follower_count"),
            data.get("reposts"),
            data.get("accounts_engaged"),
            data.get("total_interactions"),
        ),
    )
    db.commit()


def save_post_metrics(user, posts):
    """Upsert de métricas por post (una fila por ``(user_id, media_id)``).

    Re-bajar un post actualiza la fila, no la duplica. ``posts`` son dicts ya
    normalizados (ver ``fetch.normalize_post``).
    """
    db = get_db()
    for p in posts:
        db.execute(
            """
            INSERT INTO post_metrics
                (user_id, media_id, media_type, permalink, caption, timestamp,
                 reach, views, likes, comments, saved, shares, total_interactions,
                 fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, media_id) DO UPDATE SET
                media_type         = excluded.media_type,
                permalink          = excluded.permalink,
                caption            = excluded.caption,
                timestamp          = excluded.timestamp,
                reach              = excluded.reach,
                views              = excluded.views,
                likes              = excluded.likes,
                comments           = excluded.comments,
                saved              = excluded.saved,
                shares             = excluded.shares,
                total_interactions = excluded.total_interactions,
                fetched_at         = CURRENT_TIMESTAMP,
                actualizado_en     = CURRENT_TIMESTAMP
            """,
            (
                user["id"],
                p.get("media_id"),
                p.get("media_type"),
                p.get("permalink"),
                p.get("caption"),
                p.get("timestamp"),
                p.get("reach"),
                p.get("views"),
                p.get("likes"),
                p.get("comments"),
                p.get("saved"),
                p.get("shares"),
                p.get("total_interactions"),
            ),
        )
    db.commit()
