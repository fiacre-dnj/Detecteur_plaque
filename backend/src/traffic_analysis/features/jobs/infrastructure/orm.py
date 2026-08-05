"""Modèles ORM de la feature `jobs`.

Ces classes ne sortent **jamais** du repository : il traduit dans les deux sens
vers `JobRecord`. Un modèle ORM qui remonte jusqu'à une route emporte une session
et des chargements paresseux, qui explosent en contexte async avec un
`MissingGreenlet` dont le message ne dit rien de la cause.

Une décision de schéma mérite d'être lue avant d'être modifiée : **aucune
contrainte d'unicité sur `job_crossings`**. Deux franchissements légitimes de la
même identité sur la même ligne dans **deux sens** doivent coexister. La
déduplication est une règle de domaine, déjà appliquée en amont ; la reproduire en
contrainte SQL casserait le cas de l'aller-retour.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from traffic_analysis.core.db.base import Base, TimestampMixin
from traffic_analysis.core.db.types import UtcDateTime


class JobModel(TimestampMixin, Base):
    """Un job d'analyse et ses agrégats dénormalisés."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # La requête telle qu'elle a été reçue : rejouer une analyse à l'identique doit
    # être possible, et c'est aussi ce qui permet à l'historique de recharger la
    # géométrie dans le studio.
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    processed_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_fps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Message destiné à l'utilisateur, jamais une trace de pile.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    video_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_fps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    video_frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Dénormalisés : trier l'historique par nombre de véhicules ne doit pas
    # obliger à ouvrir et décompresser chaque fichier de résultat.
    unique_vehicles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crossings_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reid_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    result_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    vehicles: Mapped[list[JobVehicleModel]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    crossings: Mapped[list[JobCrossingModel]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    zone_events: Mapped[list[JobZoneEventModel]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # L'historique se lit du plus récent au plus ancien, filtré par statut :
        # c'est exactement cet index qui évite un balayage complet.
        Index("ix_jobs_status_created", "status", "created_at"),
    )


class JobVehicleModel(Base):
    """Une ligne du registre des véhicules."""

    __tablename__ = "job_vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    global_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    first_seen_ms: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen_ms: Mapped[float] = mapped_column(Float, nullable=False)
    reid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_speed_px_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_plate_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    zones_visited_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    crossed_lines_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )

    job: Mapped[JobModel] = relationship(back_populates="vehicles")

    __table_args__ = (
        # Une identité est unique **dans un job** : deux jobs ont chacun leur
        # numérotation, qui n'a aucune raison de coïncider.
        Index("uq_job_vehicles_identity", "job_id", "global_id", unique=True),
        Index("ix_job_vehicles_label", "job_id", "label"),
    )


class JobCrossingModel(Base):
    """Un franchissement comptabilisé."""

    __tablename__ = "job_crossings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    line_id: Mapped[str] = mapped_column(String(64), nullable=False)
    global_id: Mapped[int] = mapped_column(Integer, nullable=False)
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_ms: Mapped[float] = mapped_column(Float, nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)

    job: Mapped[JobModel] = relationship(back_populates="crossings")

    __table_args__ = (
        Index("ix_job_crossings_line", "job_id", "line_id"),
        # La relecture parcourt les événements par horodatage croissant : cet
        # index est ce qui rend le filtrage par fenêtre temporelle instantané.
        Index("ix_job_crossings_time", "job_id", "timestamp_ms"),
    )


class JobZoneEventModel(Base):
    """Une entrée de zone."""

    __tablename__ = "job_zone_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    zone_id: Mapped[str] = mapped_column(String(64), nullable=False)
    global_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp_ms: Mapped[float] = mapped_column(Float, nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)

    job: Mapped[JobModel] = relationship(back_populates="zone_events")

    __table_args__ = (Index("ix_job_zone_events_zone", "job_id", "zone_id"),)
