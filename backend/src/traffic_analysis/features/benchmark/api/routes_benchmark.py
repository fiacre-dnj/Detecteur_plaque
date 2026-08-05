"""Routes du benchmark : dépôt, lecture, dernier run, annulation.

Une décision d'ordre de déclaration mérite d'être signalée : **`/benchmark/latest`
est déclarée avant `/benchmark/{run_id}`**. FastAPI résout dans l'ordre, donc
l'inverse ferait interpréter « latest » comme un identifiant de run et rendrait un
404 sur la route la plus utilisée de la page.
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Response, status

from traffic_analysis.core.logging import get_logger
from traffic_analysis.core.pagination import Page, PageParams, page_params
from traffic_analysis.core.schemas import ProblemDetails
from traffic_analysis.features.benchmark.api.deps import BenchmarkServiceDep
from traffic_analysis.features.benchmark.api.schemas import (
    BenchmarkCreatedSchema,
    BenchmarkRequestSchema,
    BenchmarkRunSchema,
)
from traffic_analysis.features.benchmark.application.ports import ProbeSpec
from traffic_analysis.features.benchmark.application.service import describe
from traffic_analysis.features.counting.application.dto import VEHICLE_CLASS_IDS
from traffic_analysis.features.models_registry.application.catalogue_access import known_model_ids

logger = get_logger("traffic_analysis.benchmark.api")

router = APIRouter(prefix="/benchmark", tags=["benchmark"])

PageParamsDep = Annotated[PageParams, Depends(page_params)]


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BenchmarkCreatedSchema,
    operation_id="createBenchmarkRun",
    summary="Mesure des modèles sur cette machine",
    description=(
        "Mesure la latence d'inférence des modèles demandés — ou de **tout le "
        "catalogue** si `modelIds` est absent — sur une **image de référence "
        "unique**.\n\n"
        "Le protocole, parce qu'il détermine ce que les chiffres veulent dire :\n\n"
        "1. une seule image pour tous les modèles (comparer sur des images "
        "différentes ne compare rien) ;\n"
        "2. `loadMs` vaut **0** si le modèle était déjà résident ;\n"
        "3. **un run de chauffe est exécuté puis écarté**, puis `frames` mesures "
        "sont retenues ;\n"
        "4. les seuils utilisés sont ceux de **cette requête**, pas ceux du "
        "catalogue ;\n"
        "5. chaque modèle est **libéré après sa mesure** (sauf s'il sert une "
        "analyse en cours), et la ligne le dit via `released` ;\n"
        "6. un modèle en échec porte son `error` et **le run continue**.\n\n"
        "**Un seul benchmark à la fois** : deux runs simultanés se mesureraient "
        "l'un l'autre. Le second attend en `queued`.\n\n"
        "La mesure est asynchrone : suivre `/benchmark/{runId}/events` (SSE), puis "
        "lire `/benchmark/{runId}`."
    ),
    responses={
        202: {
            "description": "Run accepté",
            "content": {
                "application/json": {"example": {"runId": "7d1e0c4a9b2f", "status": "queued"}}
            },
        },
        404: {"model": ProblemDetails, "description": "Modèle ou job inconnu"},
        409: {"model": ProblemDetails, "description": "Vidéo du job purgée ou illisible"},
        422: {"model": ProblemDetails, "description": "Requête invalide"},
        503: {"model": ProblemDetails, "description": "Persistance non configurée"},
    },
)
async def create_run(
    service: BenchmarkServiceDep,
    response: Response,
    request: BenchmarkRequestSchema | None = None,
) -> BenchmarkCreatedSchema:
    # Corps absent = tout le catalogue avec les valeurs par défaut. C'est le geste
    # le plus courant, et il ne doit pas exiger de remplir un formulaire.
    payload = request or BenchmarkRequestSchema()
    # Vide comme absent : une liste vide veut dire « tout », pas « rien » — un run
    # sans aucun modèle ne mesurerait quoi que ce soit et n'a pas de sens.
    model_ids = tuple(payload.model_ids) if payload.model_ids else known_model_ids()

    run_id = uuid4().hex
    logger.info(
        "benchmark accepté",
        run_id=run_id,
        models=len(model_ids),
        frames=payload.frames,
        image_source=payload.image_source,
    )
    await service.submit(
        run_id,
        model_ids=model_ids,
        frames=payload.frames,
        spec=ProbeSpec(
            confidence=payload.confidence_threshold,
            iou=payload.iou_threshold,
            # Les mêmes classes que l'analyse : mesurer sur les 80 classes de COCO
            # gonflerait le post-traitement et la colonne « détections » ne
            # correspondrait plus à ce que compte une analyse réelle.
            class_ids=VEHICLE_CLASS_IDS,
        ),
        image_source=payload.image_source,
        job_id=payload.job_id,
    )
    response.headers["Location"] = f"/api/v1/benchmark/{run_id}"
    return BenchmarkCreatedSchema(run_id=run_id)


@router.get(
    "",
    response_model=Page[BenchmarkRunSchema],
    operation_id="listBenchmarkRuns",
    summary="Historique paginé des runs de benchmark",
    description="Trié par date de création décroissante.",
)
async def list_runs(service: BenchmarkServiceDep, page: PageParamsDep) -> Page[BenchmarkRunSchema]:
    result = await service.list(page)
    return Page.of(
        [BenchmarkRunSchema.model_validate(describe(run)) for run in result.items],
        total=result.total,
        params=page,
    )


# **Déclarée avant `/{run_id}`** : FastAPI résout dans l'ordre, et l'inverse ferait
# prendre « latest » pour un identifiant de run.
@router.get(
    "/latest",
    response_model=BenchmarkRunSchema | None,
    operation_id="getLatestBenchmarkRun",
    summary="Le run le plus récent, terminé ou non",
    description=(
        "Rend `null` quand aucun run n'existe encore. Cette route existe pour que "
        "la page de benchmark n'ouvre pas sur un tableau vide alors qu'une mesure "
        "est en base : un écran vide se lit comme une panne."
    ),
)
async def get_latest(service: BenchmarkServiceDep) -> BenchmarkRunSchema | None:
    run = await service.latest()
    return BenchmarkRunSchema.model_validate(describe(run)) if run else None


@router.get(
    "/{run_id}",
    response_model=BenchmarkRunSchema,
    operation_id="getBenchmarkRun",
    summary="État et résultat d'un run",
    description=(
        "Les lignes apparaissent **au fil de la mesure** : un run `running` porte "
        "déjà les modèles achevés. Le contexte matériel (`device`, `half`, "
        "`ultralyticsVersion`, `imageHash`) est celui du moment de la mesure, pas "
        "celui de la machine à la lecture."
    ),
    responses={404: {"model": ProblemDetails, "description": "Run inconnu"}},
)
async def get_run(service: BenchmarkServiceDep, run_id: str) -> BenchmarkRunSchema:
    return BenchmarkRunSchema.model_validate(describe(await service.get(run_id)))


@router.delete(
    "/{run_id}",
    response_model=BenchmarkRunSchema,
    operation_id="cancelBenchmarkRun",
    summary="Annule un run en cours, ou supprime un run terminé",
    description=(
        "Un seul geste pour les deux cas : du point de vue de l'utilisateur, c'est "
        "« je ne veux plus de ce run ».\n\n"
        "L'annulation s'arrête **entre deux modèles**, jamais au milieu d'une "
        "inférence : interrompre de force laisserait le bail du modèle non rendu, "
        "donc une instance immobilisée jusqu'au redémarrage."
    ),
    responses={404: {"model": ProblemDetails, "description": "Run inconnu"}},
)
async def cancel_run(service: BenchmarkServiceDep, run_id: str) -> BenchmarkRunSchema:
    return BenchmarkRunSchema.model_validate(describe(await service.cancel_or_purge(run_id)))
