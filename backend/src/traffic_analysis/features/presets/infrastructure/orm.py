"""Modèle ORM des presets.

**La géométrie est stockée en JSON, et non dans des tables filles.** C'est le seul
endroit du projet où ce choix est fait, alors que les franchissements d'un job ont
bien leur table — la différence tient à l'usage. On requête les franchissements (par
ligne, par instant, pour agréger) ; on ne requête **jamais** les sommets d'un preset :
ils sont écrits en bloc et relus en bloc. Deux tables filles et leurs `selectinload`
n'apporteraient ici qu'un coût de jointure et deux migrations de plus.

Les dimensions d'origine sont des colonnes à part entière et non des clés du JSON :
elles font partie de l'identité du preset — un même tracé pour deux résolutions sont
deux presets — et rien n'interdit d'avoir un jour à les filtrer.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from traffic_analysis.core.db.base import Base, TimestampMixin


class PresetModel(TimestampMixin, Base):
    """Une géométrie enregistrée."""

    __tablename__ = "geometry_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Unique : c'est le nom que l'utilisateur lit dans la liste, et deux presets
    # homonymes seraient impossibles à distinguer au moment de charger.
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Le réglage de masque voyage avec la géométrie : il n'a de sens qu'avec les
    # zones qui l'accompagnent, et le séparer ferait recharger un masque sans zones.
    mask_outside_zones: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    lines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    zones_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    __table_args__ = (
        # Tri de la liste : le plus récemment modifié d'abord, ce qui est l'ordre
        # dans lequel on cherche un preset qu'on vient d'enregistrer.
        Index("ix_geometry_presets_updated", "updated_at"),
    )
