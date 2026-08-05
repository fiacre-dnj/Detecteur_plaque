"""Ports de la feature `jobs`.

La persistance est remplaçable (mémoire → SQLite → Postgres) sans toucher aux
routes. Le `JobManager` ne connaît que ces protocoles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from typing import Any

    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.counting.application.dto import (
        AnalysisResultData,
        Progress,
    )
    from traffic_analysis.features.jobs.domain.records import JobRecord, VideoMetadata
    from traffic_analysis.features.jobs.domain.status import JobStatus


@dataclass(frozen=True, slots=True)
class JobFilters:
    """Filtres de l'historique. Tous optionnels, combinables."""

    status: JobStatus | None = None
    model_id: str | None = None


class JobRepository(Protocol):
    """Persistance de l'état des jobs."""

    async def add(self, job: JobRecord) -> None: ...

    async def get(self, job_id: str) -> JobRecord | None: ...

    async def list(self, filters: JobFilters, page: PageParams) -> Page[JobRecord]: ...

    async def update_progress(self, job_id: str, progress: Progress) -> None:
        """Enregistre l'avancement.

        **N'est pas appelée à chaque frame.** La progression vit en mémoire dans
        le `ProgressHub` et n'est persistée qu'à intervalle et aux transitions
        d'état : SQLite n'a qu'un écrivain, et une analyse à 25 images par seconde
        déclencherait 25 écritures par seconde.
        """
        ...

    async def set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> None: ...

    async def set_video_metadata(self, job_id: str, video: VideoMetadata) -> None: ...

    async def save_result_aggregates(self, job_id: str, data: AnalysisResultData) -> None:
        """Écrit les agrégats en **une seule transaction**, en lot.

        Cinq mille franchissements insérés un par un prennent des minutes sur
        SQLite ; en lot, moins d'une seconde.
        """
        ...

    async def delete(self, job_id: str) -> None: ...

    async def list_expired(self, older_than_minutes: int) -> Sequence[JobRecord]:
        """Jobs **terminaux** plus vieux que le TTL, candidats à la purge."""
        ...


class ResultStore(Protocol):
    """Stockage du résultat détaillé — le blob de relecture.

    Sur disque et non en base : une timeline de 30 minutes compte 54 000 lignes,
    ce n'est pas une donnée relationnelle et l'interroger n'a aucun sens.
    """

    def write(self, job_id: str, payload: dict[str, Any]) -> Path:
        """Écrit le résultat compressé et rend son chemin."""
        ...

    def path_for(self, job_id: str) -> Path | None:
        """Chemin du résultat s'il existe encore sur disque, `None` sinon.

        `None` plutôt qu'une exception : un fichier disparu (purge, volume
        démonté) doit produire un message clair, pas un 500.
        """
        ...

    def delete(self, job_id: str) -> None:
        """Supprime les artefacts d'un job. **Idempotent** : un fichier déjà
        absent n'est pas une erreur."""
        ...
