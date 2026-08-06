"""Routes des presets de géométrie.

**Les paramètres `width`/`height` de la lecture sont la raison d'être de ces
routes.** Sans eux, l'API rendrait des coordonnées tracées pour une autre résolution
et le client devrait deviner qu'il doit les convertir. Avec eux, le serveur convertit
et **le dit** par le drapeau `scaled` — la conversion silencieuse serait pire que pas
de conversion du tout, parce qu'une géométrie qui bouge sans prévenir se lit comme un
bug de l'application.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from traffic_analysis.core.logging import get_logger
from traffic_analysis.core.pagination import Page, PageParams, page_params
from traffic_analysis.core.schemas import ProblemDetails
from traffic_analysis.features.presets.api.deps import PresetServiceDep
from traffic_analysis.features.presets.api.schemas import PresetDraftSchema, PresetSchema
from traffic_analysis.features.presets.application.service import describe

logger = get_logger("traffic_analysis.presets.api")

router = APIRouter(prefix="/presets", tags=["presets"])

PageParamsDep = Annotated[PageParams, Depends(page_params)]

WidthQuery = Annotated[
    int | None,
    Query(
        gt=0,
        le=16384,
        description=(
            "Largeur de la vidéo courante. Fournie avec `height`, la géométrie rendue "
            "est mise à l'échelle et `scaled` vaut `true`."
        ),
    ),
]
HeightQuery = Annotated[
    int | None, Query(gt=0, le=16384, description="Hauteur de la vidéo courante.")
]

# Annotées : sans le type explicite, mypy infère `dict[int, dict[str, object]]` et
# refuse le dépaquetage dans le paramètre `responses` de FastAPI.
_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetails, "description": "Preset inconnu"}
}
_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"model": ProblemDetails, "description": "Persistance non configurée"}
}


@router.get(
    "",
    response_model=Page[PresetSchema],
    operation_id="listPresets",
    summary="Géométries enregistrées",
    description=(
        "Liste les presets, du plus récemment modifié au plus ancien.\n\n"
        "Les coordonnées rendues ici sont celles **d'origine** : la liste sert à "
        "choisir, pas à charger. La mise à l'échelle a lieu à la lecture d'un preset "
        "précis, où la résolution de la vidéo courante est connue."
    ),
    responses={**_UNAVAILABLE},
)
async def list_presets(service: PresetServiceDep, page: PageParamsDep) -> Page[PresetSchema]:
    result = await service.list(page)
    return Page.of(
        [PresetSchema.model_validate(describe(preset)) for preset in result.items],
        total=result.total,
        params=page,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PresetSchema,
    operation_id="createPreset",
    summary="Enregistre une géométrie réutilisable",
    description=(
        "Enregistre les lignes et les zones courantes sous un nom.\n\n"
        "**Les dimensions de la vidéo sont obligatoires** : une géométrie n'a de sens "
        "que pour une résolution donnée. Une ligne à `y = 400` traverse le milieu "
        "d'une image de 720 px de haut et sort du cadre d'une image de 360. Sans "
        "cette information, recharger le preset placerait les lignes au mauvais "
        "endroit sans qu'aucune erreur ne le signale — et les comptages seraient "
        "faux tout en restant plausibles.\n\n"
        "Le nom est unique. Un homonyme est refusé en **409** plutôt qu'écrasé : "
        "perdre une géométrie qu'on croyait garder ne se découvre qu'en la "
        "rechargeant, bien trop tard."
    ),
    responses={
        409: {"model": ProblemDetails, "description": "Nom déjà utilisé"},
        422: {"model": ProblemDetails, "description": "Géométrie invalide"},
        **_UNAVAILABLE,
    },
)
async def create_preset(
    draft: PresetDraftSchema, service: PresetServiceDep, response: Response
) -> PresetSchema:
    preset = await service.create(draft.to_domain())
    response.headers["Location"] = f"/api/v1/presets/{preset.id}"
    return PresetSchema.model_validate(describe(preset))


@router.get(
    "/{preset_id}",
    response_model=PresetSchema,
    operation_id="getPreset",
    summary="Une géométrie enregistrée, éventuellement mise à l'échelle",
    description=(
        "Rend un preset. Avec `width` et `height`, la géométrie est convertie vers "
        "cette résolution et **`scaled` vaut `true`**.\n\n"
        "Les deux axes sont mis à l'échelle **indépendamment**. Passer d'un 16/9 à un "
        "4/3 déforme donc la géométrie — c'est le comportement correct, puisque "
        "l'image subit exactement la même déformation. Une homothétie uniforme "
        "laisserait une bande morte ou déborderait du cadre.\n\n"
        "`originalWidth`/`originalHeight` restent toujours ceux de l'enregistrement, "
        "pour que l'interface puisse dire d'où vient le preset."
    ),
    responses={**_NOT_FOUND, **_UNAVAILABLE},
)
async def get_preset(
    preset_id: str,
    service: PresetServiceDep,
    width: WidthQuery = None,
    height: HeightQuery = None,
) -> PresetSchema:
    preset = await service.get(preset_id)
    return PresetSchema.model_validate(describe(preset, width=width, height=height))


@router.put(
    "/{preset_id}",
    response_model=PresetSchema,
    operation_id="updatePreset",
    summary="Remplace une géométrie enregistrée",
    description=(
        "Remplace intégralement le preset. Renommer un preset en son propre nom "
        "n'est pas un conflit — le refuser rendrait toute modification impossible "
        "sans changer de nom."
    ),
    responses={
        409: {"model": ProblemDetails, "description": "Nom déjà utilisé par un autre preset"},
        422: {"model": ProblemDetails, "description": "Géométrie invalide"},
        **_NOT_FOUND,
        **_UNAVAILABLE,
    },
)
async def update_preset(
    preset_id: str, draft: PresetDraftSchema, service: PresetServiceDep
) -> PresetSchema:
    preset = await service.replace(preset_id, draft.to_domain())
    return PresetSchema.model_validate(describe(preset))


@router.delete(
    "/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deletePreset",
    summary="Supprime une géométrie enregistrée",
    description=(
        "Supprime définitivement le preset. Les analyses déjà lancées avec cette "
        "géométrie ne sont **pas** affectées : elles portent leur propre copie de la "
        "configuration, et un résultat dont la géométrie disparaîtrait ne serait plus "
        "interprétable."
    ),
    responses={**_NOT_FOUND, **_UNAVAILABLE},
)
async def delete_preset(preset_id: str, service: PresetServiceDep) -> Response:
    await service.delete(preset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
