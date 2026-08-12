"""Catalogue de modèles, préchargement, déchargement."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from traffic_analysis.core.deps import ContainerDep
from traffic_analysis.core.errors import UnavailableError
from traffic_analysis.core.schemas import CamelModel, ProblemDetails
from traffic_analysis.features.counting.application.dto import (
    DETECTABLE_CLASSES,
    VEHICLE_CLASS_IDS,
)
from traffic_analysis.features.models_registry.application.model_service import ModelService

router = APIRouter(prefix="/models", tags=["models"])


def get_model_service(container: ContainerDep) -> ModelService:
    service = container.model_service
    if service is None:  # pragma: no cover — garde-fou de configuration
        raise UnavailableError("Le registre de modèles n'est pas configuré.")
    return service


ModelServiceDep = Annotated[ModelService, Depends(get_model_service)]


class ModelSchema(CamelModel):
    """Un modèle du catalogue, avec son état sur cette machine."""

    id: str
    label: str
    family: str
    tier: str
    tier_label: str
    note: str
    size_mb: int
    size_bytes: int | None
    downloaded: bool
    loaded: bool
    is_default: bool


class TierSchema(CamelModel):
    id: str
    label: str


class ModelCatalogueSchema(CamelModel):
    """Le catalogue complet et le contexte matériel qui donne sens aux mesures."""

    models: list[ModelSchema]
    tiers: list[TierSchema]
    device: str
    half: bool
    ultralytics_version: str
    plate_available: bool
    #: Deux drapeaux et non un : le détecteur et le lecteur sont deux artefacts
    #: distincts, et « détection sans lecture » est l'état de tout déploiement neuf.
    plate_ocr_available: bool
    loaded_ids: list[str]
    max_loaded_models: int


@router.get(
    "",
    response_model=ModelCatalogueSchema,
    operation_id="listModels",
    summary="Catalogue des détecteurs et état de chacun",
    description=(
        "Trois états **distincts** par modèle :\n\n"
        "- `available` (présence au catalogue) — implicite, tout modèle listé l'est ;\n"
        "- `downloaded` — ses poids sont sur le disque de ce serveur ;\n"
        "- `loaded` — une instance est résidente en mémoire.\n\n"
        "Les distinguer permet à l'interface d'annoncer « premier usage : "
        "téléchargement ~N Mo » **avant** que l'utilisateur lance une analyse, au "
        "lieu de le laisser devant une barre immobile pendant 90 secondes."
    ),
)
async def list_models(service: ModelServiceDep, container: ContainerDep) -> ModelCatalogueSchema:
    return ModelCatalogueSchema(
        models=[ModelSchema.model_validate(model) for model in service.catalogue_with_state()],
        tiers=[TierSchema.model_validate(tier) for tier in service.tiers()],
        device=service.device(),
        half=service.half(),
        ultralytics_version=service.ultralytics_version(),
        plate_available=service.plate_available(),
        plate_ocr_available=service.plate_ocr_available(),
        loaded_ids=service.loaded_ids(),
        max_loaded_models=container.settings.max_loaded_models,
    )


class DetectableClassSchema(CamelModel):
    """Une classe cochable, telle que l'interface doit l'afficher."""

    id: int
    coco_name: str
    label: str
    category: str
    default_selected: bool


@router.get(
    "/classes",
    response_model=list[DetectableClassSchema],
    operation_id="listDetectableClasses",
    summary="Classes que les détecteurs savent reconnaître",
    description=(
        "La liste des cases à cocher, **servie par le serveur et non recopiée dans "
        "l'interface**. Les modèles du catalogue sont tous entraînés sur COCO : une "
        "classe absente de cette réponse ne demande pas un autre réglage mais un "
        "autre modèle.\n\n"
        "`category` sépare les véhicules des personnes, et les totaux ne mélangent "
        "jamais les deux. `defaultSelected` marque les quatre véhicules, "
        "c'est-à-dire le comportement historique de l'application."
    ),
)
async def list_detectable_classes() -> list[DetectableClassSchema]:
    """Servie sans toucher au registre : c'est une donnée, pas un état machine.

    Publier cette liste plutôt que la recopier côté interface évite la panne la
    plus bête de ce genre de fonctionnalité : une case cochable dans le navigateur
    que le serveur refuse à l'envoi, ou l'inverse — une classe détectable que
    personne ne peut cocher.
    """
    return [
        DetectableClassSchema(
            id=entry.id,
            coco_name=entry.coco_name,
            label=entry.label,
            category=entry.category,
            default_selected=entry.id in VEHICLE_CLASS_IDS,
        )
        for entry in DETECTABLE_CLASSES
    ]


@router.post(
    "/{model_id}/preload",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="preloadModel",
    summary="Charge et préchauffe un modèle par avance",
    description=(
        "Le premier appel d'un modèle inclut son téléchargement **et** la fusion "
        "de ses couches. Précharger déplace cette attente à un moment choisi par "
        "l'utilisateur, au lieu de la faire subir à sa première analyse."
    ),
    responses={
        202: {"description": "Modèle chargé et préchauffé"},
        404: {"model": ProblemDetails, "description": "Modèle inconnu"},
        503: {"model": ProblemDetails, "description": "Chargement impossible"},
    },
)
async def preload_model(service: ModelServiceDep, model_id: str) -> dict[str, str]:
    await service.preload(model_id)
    return {"modelId": model_id, "status": "loaded"}


@router.delete(
    "/{model_id}/loaded",
    operation_id="unloadModel",
    summary="Décharge une instance résidente",
    description=(
        "Libère la mémoire d'un modèle. **Refuse** si l'instance est occupée par "
        "une analyse en cours : l'arracher laisserait l'analyse sans modèle."
    ),
    responses={404: {"model": ProblemDetails, "description": "Modèle inconnu"}},
)
async def unload_model(service: ModelServiceDep, model_id: str) -> dict[str, object]:
    return {"modelId": model_id, "unloaded": service.unload(model_id)}
