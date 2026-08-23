"""Registre, franchissements et exports — les agrégats interrogeables d'un job.

Ces routes existent parce que le fichier de résultat n'est pas interrogeable :
filtrer 10 000 véhicules côté client obligerait à télécharger et décompresser la
timeline entière. Les agrégats sont en base précisément pour ça.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from traffic_analysis.core.errors import UnavailableError
from traffic_analysis.core.pagination import Page, PageParams, page_params
from traffic_analysis.core.schemas import ProblemDetails
from traffic_analysis.features.jobs.api.deps import JobManagerDep, JobQueriesDep
from traffic_analysis.features.jobs.application.csv_export import crossings_csv, vehicles_csv

router = APIRouter(prefix="/jobs", tags=["jobs"])

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


@router.get(
    "/{job_id}/vehicles",
    response_model=Page[dict[str, Any]],
    operation_id="listJobVehicles",
    summary="Registre des véhicules, paginé et filtrable",
    description=(
        "Une ligne par identité : vu de/à, lignes franchies avec leur sens, "
        "ré-identifications, meilleure plaque **détectée** et plaque "
        "**lue** (`plateText`, vote sur toute la vie du véhicule).\n\n"
        "Les cartes de synthèse disent *combien*, ce registre dit **lesquels** — "
        "c'est lui qui rend un total vérifiable plutôt que croyable."
    ),
    responses={404: {"model": ProblemDetails, "description": "Job inconnu"}},
)
async def list_vehicles(
    manager: JobManagerDep,
    queries: JobQueriesDep,
    job_id: str,
    page: Annotated[PageParams, Depends(page_params)],
    label: Annotated[str | None, Query(description="Filtre par classe votée.")] = None,
    crossed: Annotated[
        bool | None,
        Query(
            description=(
                "Véhicules ayant franchi au moins une ligne (`true`) ou aucune "
                "(`false`). Remplace `minReid`, disparu avec la ré-identification : "
                "la question utile est désormais « lesquels ne sont jamais passés »."
            )
        ),
    ] = None,
    has_plate: Annotated[
        bool | None, Query(description="Avec ou sans plaque **détectée**.")
    ] = None,
    plate_text: Annotated[
        str | None,
        Query(
            max_length=16,
            description=(
                "Recherche dans le texte **lu** — sous-chaîne, insensible à la casse. "
                "Indépendant de `has_plate`, qui porte sur la détection : une plaque "
                "peut être vue sans qu'aucune lecture ne fasse consensus."
            ),
        ),
    ] = None,
) -> Page[dict[str, Any]]:
    await manager.get(job_id)  # 404 explicite plutôt qu'une page vide trompeuse
    return await queries.list_vehicles(
        job_id, page, label=label, crossed=crossed, has_plate=has_plate, plate_text=plate_text
    )


@router.get(
    "/{job_id}/crossings",
    response_model=Page[dict[str, Any]],
    operation_id="listJobCrossings",
    summary="Franchissements, paginés et filtrables",
    description=(
        "Ordre chronologique. `direction` vaut `+1` (A→B) ou `-1` (B→A), selon "
        "l'orientation de la ligne telle qu'elle a été tracée."
    ),
    responses={404: {"model": ProblemDetails, "description": "Job inconnu"}},
)
async def list_crossings(
    manager: JobManagerDep,
    queries: JobQueriesDep,
    job_id: str,
    page: Annotated[PageParams, Depends(page_params)],
    line_id: Annotated[str | None, Query()] = None,
    direction: Annotated[int | None, Query(ge=-1, le=1)] = None,
    from_ms: Annotated[float | None, Query(ge=0)] = None,
    to_ms: Annotated[float | None, Query(ge=0)] = None,
) -> Page[dict[str, Any]]:
    await manager.get(job_id)
    return await queries.list_crossings(
        job_id, page, line_id=line_id, direction=direction, from_ms=from_ms, to_ms=to_ms
    )


@router.get(
    "/{job_id}/export.csv",
    operation_id="exportJobCsv",
    summary="Export CSV du registre ou des franchissements",
    description=(
        "`text/csv; charset=utf-8` avec **BOM UTF-8** et séparateur `;`.\n\n"
        "Les trois ensemble sont ce qui rend le fichier directement ouvrable dans "
        "un Excel français : sans le BOM les accents sont massacrés, sans le "
        "point-virgule tout atterrit dans une seule colonne, et les décimales "
        "sont écrites à la virgule pour qu'Excel les reconnaisse comme des nombres."
    ),
    responses={
        200: {"content": {"text/csv": {}}, "description": "Fichier CSV"},
        404: {"model": ProblemDetails, "description": "Job inconnu"},
        503: {"model": ProblemDetails, "description": "Agrégats indisponibles"},
    },
)
async def export_csv(
    manager: JobManagerDep,
    queries: JobQueriesDep,
    job_id: str,
    dataset: Annotated[str, Query(pattern="^(vehicles|crossings)$")] = "vehicles",
) -> Response:
    record = await manager.get(job_id)
    if queries is None:  # pragma: no cover — garde-fou de configuration
        raise UnavailableError("L'export CSV exige la persistance en base.")

    if dataset == "vehicles":
        content = vehicles_csv(await queries.all_vehicles(job_id))
        suffix = "vehicules"
    else:
        content = crossings_csv(await queries.all_crossings(job_id))
        suffix = "franchissements"

    # Le nom de fichier est construit à partir du nom d'origine assaini, ce qui
    # évite qu'un utilisateur retrouve douze fichiers « export.csv » dans son
    # dossier de téléchargements.
    stem = record.file_name.rsplit(".", 1)[0][:60] or "analyse"
    filename = f"{stem}-{suffix}.csv"
    return Response(
        content=content,
        media_type=CSV_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # `expose_headers` de CORS doit lister Content-Disposition, sinon le
            # JavaScript ne voit pas le nom de fichier.
            "Cache-Control": "no-store",
        },
    )
