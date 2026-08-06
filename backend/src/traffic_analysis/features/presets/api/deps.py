"""Dépendances FastAPI de la feature `presets`.

Les types annotés sont importés **à l'exécution** et non sous `TYPE_CHECKING` : sous
`from __future__ import annotations`, un type que FastAPI ne peut pas résoudre est
pris pour un champ de requête, et la route rend un 422 sur un paramètre qui n'existe
pas.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from traffic_analysis.core.deps import ContainerDep
from traffic_analysis.core.errors import UnavailableError
from traffic_analysis.features.presets.application.service import PresetService


def get_preset_service(container: ContainerDep) -> PresetService:
    """Service des presets, ou une erreur qui dit **pourquoi** il manque.

    Un preset n'a aucun sens sans persistance : le stocker en mémoire le ferait
    disparaître au redémarrage, ce qui est exactement le contraire de ce qu'un
    enregistrement promet. Mieux vaut un 503 explicite qu'une liste qui se vide
    toute seule.
    """
    service = container.preset_service
    if service is None:
        raise UnavailableError(
            "Les presets exigent la persistance en base, qui n'est pas configurée sur ce serveur.",
            code="persistence_unavailable",
        )
    return service


PresetServiceDep = Annotated[PresetService, Depends(get_preset_service)]
