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


def get_job_manager(container: ContainerDep) -> JobManager:
    return container.job_manager


def get_progress_hub(container: ContainerDep) -> ProgressHub:
    return container.progress_hub


def get_result_store(container: ContainerDep) -> FileResultStore:
    return container.result_store


JobManagerDep = Annotated[JobManager, Depends(get_job_manager)]
ProgressHubDep = Annotated[ProgressHub, Depends(get_progress_hub)]
ResultStoreDep = Annotated[FileResultStore, Depends(get_result_store)]
