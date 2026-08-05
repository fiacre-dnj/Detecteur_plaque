"""Dépôt de jobs sur SQLAlchemy async.

Deux décisions gouvernent ce module, et les deux se mesurent :

- **Les agrégats sont écrits en une seule transaction, en lot.** Cinq mille
  franchissements insérés un par un prennent des minutes sur SQLite ; en lot,
  moins d'une seconde.
- **Rien ne se recalcule en SQL.** `crossings_total` est écrit depuis la valeur
  que le domaine a calculée. Réimplémenter le comptage en SQL créerait une
  seconde implémentation, qui divergerait — et on ne saurait pas laquelle croire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, insert, select, update

from traffic_analysis.core.db.base import utcnow
from traffic_analysis.core.pagination import Page
from traffic_analysis.features.counting.application.dto import AnalysisResultData
from traffic_analysis.features.counting.application.serializers import (
    serialise_crossing,
    serialise_stats,
    serialise_vehicle,
    serialise_zone_event,
)
from traffic_analysis.features.jobs.domain.records import JobRecord, VideoMetadata
from traffic_analysis.features.jobs.domain.status import TERMINAL_STATUSES, JobStatus, is_terminal
from traffic_analysis.features.jobs.infrastructure.orm import (
    JobCrossingModel,
    JobModel,
    JobVehicleModel,
    JobZoneEventModel,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from traffic_analysis.core.pagination import PageParams
    from traffic_analysis.features.counting.application.dto import Progress
    from traffic_analysis.features.jobs.application.ports import JobFilters


class SqlAlchemyJobRepository:
    """Persistance des jobs et de leurs agrégats.

    Le dépôt ouvre **sa propre session par opération** plutôt que d'en recevoir
    une : il est appelé depuis des tâches de fond qui n'ont pas de requête HTTP,
    donc pas de session injectée par FastAPI. Chaque opération est atomique par
    construction.
    """

    __slots__ = ("_session_factory",)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, job: JobRecord) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(_to_model(job))

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._session_factory() as session:
            model = await session.get(JobModel, job_id)
            return _to_record(model) if model else None

    async def list(self, filters: JobFilters, page: PageParams) -> Page[JobRecord]:
        async with self._session_factory() as session:
            criteria = []
            if filters.status is not None:
                criteria.append(JobModel.status == filters.status)
            if filters.model_id is not None:
                criteria.append(JobModel.model_id == filters.model_id)

            total = await session.scalar(
                select(func.count()).select_from(JobModel).where(*criteria)
            )
            rows = await session.scalars(
                select(JobModel)
                .where(*criteria)
                # Du plus récent au plus ancien : l'historique montre d'abord ce
                # qui vient d'être analysé.
                .order_by(JobModel.created_at.desc(), JobModel.id.desc())
                .limit(page.limit)
                .offset(page.offset)
            )
            return Page.of([_to_record(row) for row in rows], total=total or 0, params=page)

    async def update_progress(self, job_id: str, progress: Progress) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(JobModel)
                .where(JobModel.id == job_id)
                .values(
                    progress=progress.ratio,
                    processed_frames=progress.processed_frames,
                    total_frames=progress.total_frames,
                    processing_fps=progress.processing_fps,
                )
            )

    async def set_status(self, job_id: str, status: JobStatus, *, error: str | None = None) -> None:
        values: dict[str, Any] = {"status": status, "error": error}
        now = utcnow()
        if status == "running":
            values["started_at"] = now
        if is_terminal(status):
            values["finished_at"] = now
            # Un job terminé sans erreur affiche 100 % : la barre doit atteindre
            # sa fin, sinon l'utilisateur croit l'analyse interrompue.
            if status == "done":
                values["progress"] = 1.0

        async with self._session_factory() as session, session.begin():
            if status == "running":
                # Ne pas écraser `started_at` si le job redémarre : la durée
                # affichée deviendrait fausse.
                existing = await session.get(JobModel, job_id)
                if existing is not None and existing.started_at is not None:
                    del values["started_at"]
            await session.execute(update(JobModel).where(JobModel.id == job_id).values(**values))

    async def set_video_metadata(self, job_id: str, video: VideoMetadata) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(JobModel)
                .where(JobModel.id == job_id)
                .values(
                    video_width=video.width,
                    video_height=video.height,
                    video_fps=video.fps,
                    video_frame_count=video.frame_count,
                    video_duration_ms=video.duration_ms,
                )
            )

    async def save_result_aggregates(self, job_id: str, data: AnalysisResultData) -> None:
        """Écrit registre, franchissements et entrées de zone — **en une transaction**.

        Un seul `begin()` englobe tout : soit le job a ses agrégats complets, soit
        il n'en a aucun. Un job à moitié écrit serait pire qu'un job sans agrégats,
        parce que rien à l'écran ne le signalerait.
        """
        if data.stats is None:
            return

        vehicles = [
            {
                "job_id": job_id,
                "global_id": record.global_id,
                "label": record.label,
                "first_seen_ms": record.first_seen_ms,
                "last_seen_ms": record.last_seen_ms,
                "reid_count": record.reid_count,
                "avg_speed_px_s": record.avg_speed_px_s,
                "avg_speed_kmh": record.avg_speed_kmh,
                "best_plate_score": record.best_plate_score,
                "zones_visited_json": list(record.zones_visited),
                "crossed_lines_json": serialise_vehicle(record)["crossedLines"],
            }
            for record in data.vehicles
        ]
        crossings = [
            {"job_id": job_id, **_snake(serialise_crossing(event))} for event in data.crossings
        ]
        zone_events = [
            {"job_id": job_id, **_snake(serialise_zone_event(event))} for event in data.zone_events
        ]

        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(JobModel)
                .where(JobModel.id == job_id)
                .values(
                    stats_json=serialise_stats(data.stats),
                    unique_vehicles=data.stats.unique_vehicles,
                    crossings_total=data.stats.crossings,
                    reid_hits=data.stats.reid_hits,
                    processing_fps=data.processing_fps,
                    result_path=f"jobs/{job_id}/result.json.gz",
                )
            )
            # `insert(Model), [dict, …]` est l'insertion en lot de SQLAlchemy :
            # une seule instruction, un seul aller-retour.
            if vehicles:
                await session.execute(insert(JobVehicleModel), vehicles)
            if crossings:
                await session.execute(insert(JobCrossingModel), crossings)
            if zone_events:
                await session.execute(insert(JobZoneEventModel), zone_events)

    async def delete(self, job_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(delete(JobModel).where(JobModel.id == job_id))

    async def list_expired(self, older_than_minutes: int) -> Sequence[JobRecord]:
        """Jobs **terminaux** plus vieux que le TTL.

        Terminaux uniquement : purger un job en cours détruirait une analyse que
        quelqu'un attend.
        """
        from datetime import timedelta as _timedelta

        cutoff = utcnow() - _timedelta(minutes=older_than_minutes)
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(JobModel).where(
                    JobModel.status.in_(tuple(TERMINAL_STATUSES)),
                    JobModel.finished_at.is_not(None),
                    JobModel.finished_at < cutoff,
                )
            )
            return [_to_record(row) for row in rows]

    # ── Lectures paginées des agrégats ───────────────────────────────────────

    async def list_vehicles(
        self,
        job_id: str,
        page: PageParams,
        *,
        label: str | None = None,
        min_reid: int | None = None,
        has_plate: bool | None = None,
    ) -> Page[dict[str, Any]]:
        """Registre paginé et filtrable, **sans ouvrir le fichier de résultat**.

        C'est tout l'intérêt d'avoir dénormalisé : filtrer 10 000 véhicules côté
        client obligerait à télécharger le résultat complet.
        """
        criteria = [JobVehicleModel.job_id == job_id]
        if label is not None:
            criteria.append(JobVehicleModel.label == label)
        if min_reid is not None:
            criteria.append(JobVehicleModel.reid_count >= min_reid)
        if has_plate is True:
            criteria.append(JobVehicleModel.best_plate_score.is_not(None))
        elif has_plate is False:
            criteria.append(JobVehicleModel.best_plate_score.is_(None))

        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(JobVehicleModel).where(*criteria)
            )
            rows = await session.scalars(
                select(JobVehicleModel)
                .where(*criteria)
                .order_by(JobVehicleModel.global_id)
                .limit(page.limit)
                .offset(page.offset)
            )
            return Page.of([_vehicle_payload(row) for row in rows], total=total or 0, params=page)

    async def list_crossings(
        self,
        job_id: str,
        page: PageParams,
        *,
        line_id: str | None = None,
        direction: int | None = None,
        from_ms: float | None = None,
        to_ms: float | None = None,
    ) -> Page[dict[str, Any]]:
        criteria = [JobCrossingModel.job_id == job_id]
        if line_id is not None:
            criteria.append(JobCrossingModel.line_id == line_id)
        if direction is not None:
            criteria.append(JobCrossingModel.direction == direction)
        if from_ms is not None:
            criteria.append(JobCrossingModel.timestamp_ms >= from_ms)
        if to_ms is not None:
            criteria.append(JobCrossingModel.timestamp_ms <= to_ms)

        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(JobCrossingModel).where(*criteria)
            )
            rows = await session.scalars(
                select(JobCrossingModel)
                # Ordre chronologique : la relecture côté client parcourt les
                # événements par balayage croissant et suppose cet ordre.
                .where(*criteria)
                .order_by(JobCrossingModel.timestamp_ms, JobCrossingModel.id)
                .limit(page.limit)
                .offset(page.offset)
            )
            return Page.of([_crossing_payload(row) for row in rows], total=total or 0, params=page)

    async def all_vehicles(self, job_id: str) -> Sequence[dict[str, Any]]:
        """Registre complet, pour l'export CSV."""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(JobVehicleModel)
                .where(JobVehicleModel.job_id == job_id)
                .order_by(JobVehicleModel.global_id)
            )
            return [_vehicle_payload(row) for row in rows]

    async def all_crossings(self, job_id: str) -> Sequence[dict[str, Any]]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(JobCrossingModel)
                .where(JobCrossingModel.job_id == job_id)
                .order_by(JobCrossingModel.timestamp_ms, JobCrossingModel.id)
            )
            return [_crossing_payload(row) for row in rows]


# ── Traduction ORM ⇄ domaine ─────────────────────────────────────────────────


def _to_model(record: JobRecord) -> JobModel:
    return JobModel(
        id=record.id,
        status=record.status,
        model_id=record.model_id,
        file_name=record.file_name,
        file_size_bytes=record.file_size_bytes,
        config_json=record.config_json,
        progress=record.progress,
        processed_frames=record.processed_frames,
        total_frames=record.total_frames,
        processing_fps=record.processing_fps,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _to_record(model: JobModel) -> JobRecord:
    return JobRecord(
        id=model.id,
        status=model.status,  # type: ignore[arg-type]
        model_id=model.model_id,
        file_name=model.file_name,
        file_size_bytes=model.file_size_bytes,
        created_at=model.created_at,
        config_json=model.config_json,
        progress=model.progress,
        processed_frames=model.processed_frames,
        total_frames=model.total_frames,
        processing_fps=model.processing_fps,
        error=model.error,
        video=VideoMetadata(
            width=model.video_width,
            height=model.video_height,
            fps=model.video_fps,
            frame_count=model.video_frame_count,
            duration_ms=model.video_duration_ms,
        ),
        stats_json=model.stats_json,
        unique_vehicles=model.unique_vehicles,
        crossings_total=model.crossings_total,
        reid_hits=model.reid_hits,
        result_path=model.result_path,
        started_at=model.started_at,
        finished_at=model.finished_at,
    )


_CAMEL_TO_SNAKE = {
    "lineId": "line_id",
    "zoneId": "zone_id",
    "globalId": "global_id",
    "trackId": "track_id",
    "timestampMs": "timestamp_ms",
    "frameIndex": "frame_index",
}


def _snake(payload: dict[str, Any]) -> dict[str, Any]:
    """Traduit les clés du fil vers les colonnes.

    Les sérialiseurs produisent du camelCase — c'est le contrat HTTP. Les
    colonnes sont en snake_case. Réutiliser les sérialiseurs plutôt que de
    dupliquer la construction du dictionnaire garantit qu'un champ ajouté au
    contrat n'est pas oublié en base.
    """
    return {_CAMEL_TO_SNAKE.get(key, key): value for key, value in payload.items()}


def _vehicle_payload(model: JobVehicleModel) -> dict[str, Any]:
    return {
        "globalId": model.global_id,
        "label": model.label,
        "firstSeenMs": model.first_seen_ms,
        "lastSeenMs": model.last_seen_ms,
        "crossedLines": model.crossed_lines_json,
        "zonesVisited": model.zones_visited_json,
        "reidCount": model.reid_count,
        "avgSpeedPxS": model.avg_speed_px_s,
        "avgSpeedKmh": model.avg_speed_kmh,
        "bestPlateScore": model.best_plate_score,
    }


def _crossing_payload(model: JobCrossingModel) -> dict[str, Any]:
    return {
        "lineId": model.line_id,
        "globalId": model.global_id,
        "trackId": model.track_id,
        "label": model.label,
        "direction": model.direction,
        "timestampMs": model.timestamp_ms,
        "frameIndex": model.frame_index,
    }
