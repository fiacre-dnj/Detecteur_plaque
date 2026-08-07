"""Sondes de santé.

Trois routes distinctes parce qu'elles répondent à trois questions différentes,
et qu'un orchestrateur qui les confond redémarre des processus sains :

- `/health/live`  : « le processus répond-il ? » — aucune dépendance vérifiée ;
- `/health/ready` : « peut-il travailler ? » — dépendances vérifiées ;
- `/health`       : « dans quel état est-il ? » — diagnostic pour l'interface.

`/health` complet (device, version d'Ultralytics, modèles résidents,
disponibilité de l'ANPR) arrive avec le registre de modèles ; ici il n'existe que
ce qui peut être dit honnêtement.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from traffic_analysis import __version__
from traffic_analysis.core.deps import ContainerDep, SettingsDep
from traffic_analysis.core.logging import get_logger
from traffic_analysis.core.schemas import LivenessSchema, ReadinessSchema
from traffic_analysis.features.health.api.schemas import HealthSchema

logger = get_logger("traffic_analysis.health")

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=LivenessSchema,
    status_code=status.HTTP_200_OK,
    operation_id="getLiveness",
    summary="Vivacité du processus",
    description=(
        'Répond `{"status":"ok"}` dès que le processus sert des requêtes. '
        "**Ne vérifie aucune dépendance** : une base lente ne doit pas faire "
        "redémarrer un service parfaitement sain."
    ),
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def liveness() -> LivenessSchema:
    return LivenessSchema()


@router.get(
    "/ready",
    response_model=ReadinessSchema,
    status_code=status.HTTP_200_OK,
    operation_id="getReadiness",
    summary="Préparation du service",
    description=(
        "Vérifie les dépendances nécessaires au travail réel. Le statut vaut "
        "`degraded` — et non une erreur — quand une vérification échoue : le "
        "service reste interrogeable, et l'interface peut dire *ce qui* manque."
    ),
    responses={
        200: {
            "content": {
                "application/json": {"example": {"status": "ready", "checks": {"dataDir": True}}}
            }
        }
    },
)
async def readiness(settings: SettingsDep) -> ReadinessSchema:
    checks = {"dataDir": _data_dir_is_writable(settings.data_dir)}
    return ReadinessSchema(
        status="ready" if all(checks.values()) else "degraded",
        checks=checks,
    )


@router.get(
    "",
    response_model=HealthSchema,
    status_code=status.HTTP_200_OK,
    operation_id="getHealth",
    summary="Diagnostic du service",
    description=(
        "Ce que l'interface affiche en permanence dans son badge d'état. "
        "Le device, la version d'Ultralytics et les modèles résidents "
        "apparaîtront ici avec le registre de modèles."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "version": "0.1.0",
                        "environment": "development",
                        "device": "cpu",
                        "half": False,
                        "ultralyticsVersion": "8.4.115",
                        "loadedModels": ["yolov8n"],
                        "maxLoadedModels": 2,
                        "plateAvailable": False,
                        "plateOcrAvailable": False,
                        "defaultModelId": "yolov8n",
                        "weightsDir": "/app/.weights",
                    }
                }
            }
        }
    },
)
async def health(settings: SettingsDep, container: ContainerDep) -> HealthSchema:
    service = container.model_service
    return HealthSchema(
        status="ok",
        version=__version__,
        environment=settings.env,
        device=service.device() if service else "inconnu",
        half=service.half() if service else False,
        ultralytics_version=service.ultralytics_version() if service else "indisponible",
        loaded_models=service.loaded_ids() if service else [],
        max_loaded_models=settings.max_loaded_models,
        plate_available=service.plate_available() if service else False,
        plate_ocr_available=service.plate_ocr_available() if service else False,
        default_model_id=settings.default_model_id,
        # Le chemin **résolu**, jamais celui de la configuration : c'est
        # exactement l'écart entre les deux qui rendait l'ANPR silencieusement
        # indisponible quand on lançait uvicorn depuis un autre répertoire.
        weights_dir=str(settings.weights_dir),
    )


def _data_dir_is_writable(data_dir: object) -> bool:
    """Le répertoire de données est-il utilisable en écriture ?

    C'est une dépendance réelle et fréquemment cassée : les résultats `json.gz`
    et les vidéos déposées y sont écrits, et un volume monté en lecture seule
    produit sinon un premier job qui échoue sans raison lisible.

    On écrit vraiment un fichier plutôt que de consulter les permissions :
    `os.access` ment sur un partage réseau et sur un volume Docker.
    """
    from pathlib import Path

    path = data_dir if isinstance(data_dir, Path) else Path(str(data_dir))
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        logger.warning("répertoire de données non inscriptible", path=str(path), error=str(exc))
        return False
    return True
