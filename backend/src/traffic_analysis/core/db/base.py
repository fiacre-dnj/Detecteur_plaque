"""Base déclarative et mixins partagés.

Les dates sont **UTC et timezone-aware** partout. SQLite stocke des chaînes : un
mélange de datetimes naïfs et conscients produit des comparaisons silencieusement
fausses, donc une purge TTL qui ne purge rien ou qui purge trop.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from traffic_analysis.core.db.types import UtcDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base de tous les modèles ORM."""


class TimestampMixin:
    """Horodatage de création et de mise à jour.

    `UtcDateTime` et non `DateTime(timezone=True)` : sur SQLite, le second rend
    des datetimes **naïfs** à la relecture (voir `core/db/types.py`).
    """

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
