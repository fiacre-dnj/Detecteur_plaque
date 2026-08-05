"""Dépendances FastAPI de la feature `jobs`.

Les types annotés sont importés **à l'exécution** et non sous `TYPE_CHECKING` :
sous `from __future__ import annotations`, un type que FastAPI ne peut pas
résoudre est pris pour un champ de requête, et la route rend un 422 déroutant sur
un paramètre qui n'existe pas.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from traffic_analysis.core.deps import ContainerDep
from traffic_analysis.features.jobs.application.job_manager import JobManager
from traffic_analysis.features.jobs.application.progress_hub import ProgressHub
from traffic_analysis.features.jobs.infrastructure.result_store import FileResultStore
from traffic_analysis.features.jobs.infrastructure.sqlalchemy_repository import (
    SqlAlchemyJobRepository,
)


def get_job_manager(container: ContainerDep) -> JobManager:
    return container.job_manager


def get_progress_hub(container: ContainerDep) -> ProgressHub:
    return container.progress_hub


def get_result_store(container: ContainerDep) -> FileResultStore:
    return container.result_store


def get_job_queries(container: ContainerDep) -> SqlAlchemyJobRepository:
    """Dépôt SQL, pour les lectures d'agrégats.

    Ces routes exigent la persistance : le registre paginé et l'export CSV n'ont
    pas d'équivalent en mémoire, et prétendre le contraire rendrait une page vide
    au lieu d'une erreur claire.
    """
    repository = container.job_repository
    if not isinstance(repository, SqlAlchemyJobRepository):
        from traffic_analysis.core.errors import UnavailableError

        raise UnavailableError(
            "Le registre et les exports exigent la persistance en base, "
            "qui n'est pas configurée sur ce serveur.",
            code="persistence_unavailable",
        )
    return repository


JobManagerDep = Annotated[JobManager, Depends(get_job_manager)]
ProgressHubDep = Annotated[ProgressHub, Depends(get_progress_hub)]
ResultStoreDep = Annotated[FileResultStore, Depends(get_result_store)]
JobQueriesDep = Annotated[SqlAlchemyJobRepository, Depends(get_job_queries)]
