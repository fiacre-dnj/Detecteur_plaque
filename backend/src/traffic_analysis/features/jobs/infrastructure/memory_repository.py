"""Dépôt de jobs en mémoire.

Ce n'est **pas** une doublure de test : c'est l'implémentation qui permet au
service de démarrer et de fonctionner sans base, et c'est la seconde
implémentation réelle qui justifie l'existence du port `JobRepository`. Le dépôt
SQLite la remplacera en production sans qu'aucune route ne change.

Sa limite est assumée et documentée dans `/health` : les jobs ne survivent pas au
redémarrage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from traffic_analysis.core.pagination import Page
from traffic_analysis.features.jobs.domain.status import is_terminal

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from traffic_analysis.core.clock import Clock
    from traffic_analysis.core.pagination import PageParams
    from traffic_analysis.features.counting.application.dto import AnalysisResultData, Progress
    from traffic_analysis.features.jobs.application.ports import JobFilters
    from traffic_analysis.features.jobs.domain.records import JobRecord, VideoMetadata
    from traffic_analysis.features.jobs.domain.status import JobStatus

_MINUTE_S = 60.0


class InMemoryJobRepository:
    """Jobs conservés dans un dictionnaire, du plus récent au plus ancien."""

    __slots__ = ("_clock", "_jobs")

    def __init__(self, clock: Clock) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._clock = clock

    async def add(self, job: JobRecord) -> None:
        self._jobs[job.id] = job

    async def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def list(self, filters: JobFilters, page: PageParams) -> Page[JobRecord]:
        matching = [
            job
            for job in self._jobs.values()
            if (filters.status is None or job.status == filters.status)
            and (filters.model_id is None or job.model_id == filters.model_id)
        ]
        # Tri décroissant par date de création : l'historique montre d'abord ce
        # qui vient d'être analysé, c'est ce que l'utilisateur cherche.
        matching.sort(key=lambda job: job.created_at, reverse=True)
        window = matching[page.offset : page.offset + page.limit]
        return Page.of(window, total=len(matching), params=page)

    async def update_progress(self, job_id: str, progress: Progress) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        self._jobs[job_id] = job.with_changes(
            progress=progress.ratio,
            processed_frames=progress.processed_frames,
            total_frames=progress.total_frames,
            processing_fps=progress.processing_fps,
        )

    async def set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        now: datetime = self._clock.now()
        # Les deux écrits ensemble, y compris à `None` : une transition vers un
        # statut sain efface le code d'un échec précédent, comme l'adaptateur SQL.
        changes: dict[str, object] = {"status": status, "error": error, "error_code": error_code}
        if status == "running" and job.started_at is None:
            changes["started_at"] = now
        if is_terminal(status):
            changes["finished_at"] = now
            # Un job terminé sans erreur affiche 100 % : la barre doit atteindre
            # sa fin, sinon l'utilisateur croit l'analyse interrompue.
            if status == "done":
                changes["progress"] = 1.0
        self._jobs[job_id] = job.with_changes(**changes)

    async def set_video_metadata(self, job_id: str, video: VideoMetadata) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            self._jobs[job_id] = job.with_changes(video=video)

    async def save_result_aggregates(self, job_id: str, data: AnalysisResultData) -> None:
        job = self._jobs.get(job_id)
        if job is None or data.stats is None:
            return
        from traffic_analysis.features.counting.application.serializers import serialise_stats

        self._jobs[job_id] = job.with_changes(
            stats_json=serialise_stats(data.stats),
            tracked_vehicles=data.stats.tracked_vehicles,
            crossings_total=data.stats.crossings,
            processing_fps=data.processing_fps,
            result_path=f"jobs/{job_id}/result.json.gz",
        )

    async def delete(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)

    async def list_expired(self, older_than_minutes: int) -> Sequence[JobRecord]:
        """Jobs **terminaux** plus vieux que le TTL.

        Terminaux uniquement : purger un job en cours détruirait une analyse que
        quelqu'un attend.
        """
        now = self._clock.now()
        cutoff_s = older_than_minutes * _MINUTE_S
        return [
            job
            for job in self._jobs.values()
            if is_terminal(job.status)
            and job.finished_at is not None
            and (now - job.finished_at).total_seconds() > cutoff_s
        ]
