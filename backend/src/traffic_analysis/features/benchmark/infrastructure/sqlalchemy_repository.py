"""Dépôt de runs de benchmark sur SQLAlchemy async.

Deux décisions gouvernent ce module :

- **Les lignes sont écrites au fil du run, pas en bloc à la fin.** Vingt modèles
  mesurés sur CPU prennent plusieurs minutes ; un redémarrage à la quinzième ligne
  ne doit pas effacer les quatorze précédentes.
- **Rien n'est recalculé à la lecture.** `median_ms` est relu tel qu'il a été
  écrit, et le contexte matériel vient du run et non de la machine courante. Un run
  de mars relu en août doit dire « mesuré avec la version de mars » ; recalculer
  ferait mentir l'historique, ce qui est exactement ce que le hash de l'image
  existe pour empêcher.

Comme le dépôt de jobs, il ouvre **sa propre session par opération** : il est
appelé depuis une tâche de fond qui n'a pas de requête HTTP, donc pas de session
injectée par FastAPI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from traffic_analysis.core.pagination import Page
from traffic_analysis.features.benchmark.domain.records import BenchmarkEntry, BenchmarkRun
from traffic_analysis.features.benchmark.infrastructure.orm import (
    BenchmarkEntryModel,
    BenchmarkRunModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from traffic_analysis.core.pagination import PageParams


class SqlAlchemyBenchmarkRepository:
    """Persistance des runs de benchmark et de leurs lignes."""

    __slots__ = ("_session_factory",)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, run: BenchmarkRun) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(_to_model(run))

    async def get(self, run_id: str) -> BenchmarkRun | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                # `selectinload` explicite : sans lui, accéder à `model.entries`
                # après la fermeture de la session lèverait un `MissingGreenlet`,
                # dont le message ne dit rien de la cause réelle.
                select(BenchmarkRunModel)
                .where(BenchmarkRunModel.id == run_id)
                .options(selectinload(BenchmarkRunModel.entries))
            )
            return _to_record(model) if model else None

    async def latest(self) -> BenchmarkRun | None:
        """Le run le plus récent, terminé ou non.

        Trié sur `created_at` **puis sur l'id** : deux runs créés dans la même
        milliseconde donneraient sinon un ordre arbitraire, et « le dernier run »
        changerait d'une requête à l'autre.
        """
        async with self._session_factory() as session:
            model = await session.scalar(
                select(BenchmarkRunModel)
                .options(selectinload(BenchmarkRunModel.entries))
                .order_by(BenchmarkRunModel.created_at.desc(), BenchmarkRunModel.id.desc())
                .limit(1)
            )
            return _to_record(model) if model else None

    async def list(self, page: PageParams) -> Page[BenchmarkRun]:
        async with self._session_factory() as session:
            total = await session.scalar(select(func.count()).select_from(BenchmarkRunModel))
            rows = await session.scalars(
                select(BenchmarkRunModel)
                .options(selectinload(BenchmarkRunModel.entries))
                .order_by(BenchmarkRunModel.created_at.desc(), BenchmarkRunModel.id.desc())
                .limit(page.limit)
                .offset(page.offset)
            )
            return Page.of([_to_record(row) for row in rows], total=total or 0, params=page)

    async def append_entry(self, run_id: str, entry: BenchmarkEntry) -> None:
        """Ajoute une ligne, en lui donnant son rang dans le run.

        Le rang est compté en base et non passé par l'appelant : il doit rester
        juste même si le service est redémarré au milieu d'un run.
        """
        async with self._session_factory() as session, session.begin():
            position = await session.scalar(
                select(func.count())
                .select_from(BenchmarkEntryModel)
                .where(BenchmarkEntryModel.run_id == run_id)
            )
            session.add(_entry_to_model(run_id, entry, position or 0))

    async def set_status(self, run_id: str, status: str, *, error: str | None = None) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(BenchmarkRunModel)
                .where(BenchmarkRunModel.id == run_id)
                .values(status=status, error=error)
            )

    async def delete(self, run_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(delete(BenchmarkRunModel).where(BenchmarkRunModel.id == run_id))


# ── Traduction ORM ⇄ domaine ─────────────────────────────────────────────────

# Séparateur de la liste d'identifiants. Une virgule, parce qu'aucun identifiant
# du catalogue n'en contient — un test du catalogue vérifie déjà le format
# `^[a-z0-9._-]+$`.
_SEPARATOR = ","


def _to_model(run: BenchmarkRun) -> BenchmarkRunModel:
    return BenchmarkRunModel(
        id=run.id,
        status=run.status,
        model_ids=_SEPARATOR.join(run.model_ids),
        frames=run.frames,
        image_source=run.image_source,
        image_hash=run.image_hash,
        image_width=run.image_width,
        image_height=run.image_height,
        job_id=run.job_id,
        device=run.device,
        half=run.half,
        ultralytics_version=run.ultralytics_version,
        confidence_threshold=run.confidence_threshold,
        iou_threshold=run.iou_threshold,
        error=run.error,
    )


def _to_record(model: BenchmarkRunModel) -> BenchmarkRun:
    return BenchmarkRun(
        id=model.id,
        status=model.status,  # type: ignore[arg-type]
        model_ids=tuple(part for part in model.model_ids.split(_SEPARATOR) if part),
        frames=model.frames,
        image_source=model.image_source,  # type: ignore[arg-type]
        image_hash=model.image_hash,
        image_width=model.image_width,
        image_height=model.image_height,
        device=model.device,
        half=model.half,
        ultralytics_version=model.ultralytics_version,
        confidence_threshold=model.confidence_threshold,
        iou_threshold=model.iou_threshold,
        job_id=model.job_id,
        entries=[_entry_to_record(row) for row in model.entries],
        error=model.error,
    )


def _entry_to_model(run_id: str, entry: BenchmarkEntry, position: int) -> BenchmarkEntryModel:
    return BenchmarkEntryModel(
        run_id=run_id,
        position=position,
        model_id=entry.model_id,
        label=entry.label,
        tier=entry.tier,
        load_ms=entry.load_ms,
        median_ms=entry.median_ms,
        p95_ms=entry.p95_ms,
        min_ms=entry.min_ms,
        max_ms=entry.max_ms,
        preprocess_ms=entry.preprocess_ms,
        postprocess_ms=entry.postprocess_ms,
        detections=entry.detections,
        frames=entry.frames,
        was_loaded=entry.was_loaded,
        released=entry.released,
        error=entry.error,
    )


def _entry_to_record(model: BenchmarkEntryModel) -> BenchmarkEntry:
    return BenchmarkEntry(
        model_id=model.model_id,
        label=model.label,
        tier=model.tier,
        load_ms=model.load_ms,
        median_ms=model.median_ms,
        p95_ms=model.p95_ms,
        min_ms=model.min_ms,
        max_ms=model.max_ms,
        preprocess_ms=model.preprocess_ms,
        postprocess_ms=model.postprocess_ms,
        detections=model.detections,
        frames=model.frames,
        was_loaded=model.was_loaded,
        released=model.released,
        error=model.error,
    )
