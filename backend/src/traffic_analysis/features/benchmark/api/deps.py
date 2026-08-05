"""Dépendances FastAPI de la feature `benchmark`.

Les types annotés sont importés **à l'exécution** et non sous `TYPE_CHECKING` :
sous `from __future__ import annotations`, un type que FastAPI ne peut pas résoudre
est pris pour un champ de requête, et la route rend un 422 déroutant sur un
paramètre qui n'existe pas.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from traffic_analysis.core.deps import ContainerDep
from traffic_analysis.core.errors import UnavailableError
from traffic_analysis.features.benchmark.application.service import BenchmarkService
from traffic_analysis.features.jobs.application.progress_hub import ProgressHub


def get_benchmark_service(container: ContainerDep) -> BenchmarkService:
    """Service de benchmark, ou une erreur qui dit **pourquoi** il manque.

    Il exige la persistance : un run est écrit ligne par ligne et rechargé à
    l'ouverture de la page. Sans base, prétendre le contraire rendrait un tableau
    vide au lieu d'une explication.
    """
    service = container.benchmark_service
    if service is None:
        raise UnavailableError(
            "Le benchmark exige la persistance en base, qui n'est pas configurée sur ce serveur.",
            code="persistence_unavailable",
        )
    return service


def get_benchmark_hub(container: ContainerDep) -> ProgressHub:
    """Le **même** hub que celui des jobs.

    Le même, délibérément : un second mécanisme de diffusion serait un second
    endroit où corriger le tamponnage des proxys et le ping de maintien.
    """
    return container.progress_hub


BenchmarkServiceDep = Annotated[BenchmarkService, Depends(get_benchmark_service)]
BenchmarkHubDep = Annotated[ProgressHub, Depends(get_benchmark_hub)]
