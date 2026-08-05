"""Modèles ORM du benchmark.

Comme pour les jobs, ces classes ne sortent **jamais** du repository : il traduit
dans les deux sens vers `BenchmarkRun` / `BenchmarkEntry`. Un modèle ORM qui
remonte jusqu'à une route emporte une session et des chargements paresseux, qui
explosent en contexte async avec un `MissingGreenlet` dont le message ne dit rien.

Le contexte matériel est stocké **sur le run**, pas déduit à la lecture :
`device`, `half`, `ultralytics_version` et le hash de l'image sont des propriétés
du moment de la mesure. Les relire depuis la machine courante ferait qu'un run de
mars, relu en août sur une machine mise à jour, prétendrait avoir été mesuré avec
la version d'août.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from traffic_analysis.core.db.base import Base, TimestampMixin


class BenchmarkRunModel(TimestampMixin, Base):
    """Un run de benchmark et son contexte matériel."""

    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    # Les identifiants demandés, joints par des virgules. Une table de liaison
    # serait plus normalisée et n'apporterait rien : cette liste n'est jamais
    # requêtée, seulement relue en bloc pour rétablir le run.
    model_ids: Mapped[str] = mapped_column(Text, nullable=False, default="")
    frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    image_source: Mapped[str] = mapped_column(String(16), nullable=False, default="sample")
    # Le hash est ce qui permet, six mois plus tard, de savoir si deux runs sont
    # comparables — ou pourquoi ils ne le sont pas.
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    image_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    device: Mapped[str] = mapped_column(String(32), nullable=False, default="cpu")
    half: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ultralytics_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    # Les seuils **de la requête**, persistés : sans eux, la colonne « détections »
    # d'un run relu ne serait rattachable à aucun réglage.
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    iou_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.45)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    entries: Mapped[list[BenchmarkEntryModel]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # Ordre d'insertion = ordre du catalogue = ordre d'affichage. Sans ce tri
        # explicite, SQLite rend les lignes dans l'ordre du rowid, qui coïncide
        # aujourd'hui et n'a aucune raison de coïncider demain.
        order_by="BenchmarkEntryModel.position",
    )

    __table_args__ = (
        # `GET /benchmark/latest` trie par date décroissante : cet index est
        # exactement ce qui évite un balayage complet de la table.
        Index("ix_benchmark_runs_created", "created_at"),
    )


class BenchmarkEntryModel(Base):
    """Une ligne de mesure — un modèle dans un run."""

    __tablename__ = "benchmark_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False
    )
    # Rang dans le run, pour restituer l'ordre du catalogue.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    # Durées brutes, **non arrondies** : l'arrondi est une affaire d'affichage, et
    # agréger des valeurs déjà arrondies accumule l'erreur.
    load_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    median_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p95_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    min_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Nullables : un moteur qui n'expose pas `result.speed` doit rendre `None` et
    # non `0.0`, qui se lirait comme « instantané ».
    preprocess_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    postprocess_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    detections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    was_loaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[BenchmarkRunModel] = relationship(back_populates="entries")

    __table_args__ = (
        # Un modèle n'est mesuré qu'une fois par run. La contrainte est ici — et
        # pas seulement dans le service — parce qu'une double insertion après un
        # redémarrage produirait deux lignes contradictoires pour le même modèle,
        # ce que rien à l'écran ne signalerait.
        Index("uq_benchmark_entries_model", "run_id", "model_id", unique=True),
    )
