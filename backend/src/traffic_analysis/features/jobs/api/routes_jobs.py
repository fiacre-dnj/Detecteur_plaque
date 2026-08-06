"""Routes de dépôt, de suivi et de récupération d'une analyse différée."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError

from traffic_analysis.core.deps import SettingsDep
from traffic_analysis.core.errors import (
    PayloadTooLargeError,
    UnsupportedMediaError,
    ValidationAppError,
)
from traffic_analysis.core.logging import get_logger
from traffic_analysis.core.pagination import Page, PageParams, page_params
from traffic_analysis.core.schemas import ProblemDetails
from traffic_analysis.features.counting.application.dto import VideoInfo
from traffic_analysis.features.jobs.api.deps import JobManagerDep, ResultStoreDep
from traffic_analysis.features.jobs.api.schemas import (
    AnalysisRequestSchema,
    JobCreatedSchema,
    JobDetailSchema,
    JobSchema,
)
from traffic_analysis.features.jobs.application.job_manager import JobManager
from traffic_analysis.features.jobs.application.ports import JobFilters
from traffic_analysis.features.jobs.domain.status import JobStatus

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("traffic_analysis.jobs.api")

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Extensions acceptées. Le `content-type` annoncé par le client n'est **pas** un
# critère : il est trivial à falsifier. La validation réelle est le `probe()`,
# qui échoue si le fichier n'est pas une vidéo décodable.
ALLOWED_SUFFIXES = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"})

# Écriture par morceaux : jamais l'upload entier en mémoire. Une vidéo de 800 Mo
# chargée en RAM ferait tomber le service bien avant d'être analysée.
CHUNK_SIZE = 1024 * 1024


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobCreatedSchema,
    operation_id="createAnalysisJob",
    summary="Dépose une vidéo et lance une analyse",
    description=(
        "Corps `multipart/form-data` : `file` porte la vidéo, `request` la "
        "configuration JSON (`AnalysisRequestSchema`).\n\n"
        "L'analyse est **asynchrone**. Suivre la progression sur "
        "`/jobs/{id}/events` (SSE), puis récupérer `/jobs/{id}/result`.\n\n"
        "Une analyse déjà en cours ne provoque pas de refus : le job est accepté "
        "avec le statut `queued` et démarre quand le précédent se termine."
    ),
    responses={
        202: {
            "description": "Job accepté",
            "content": {"application/json": {"example": {"jobId": "9f2c4a1b", "status": "queued"}}},
        },
        413: {"model": ProblemDetails, "description": "Vidéo trop volumineuse"},
        415: {"model": ProblemDetails, "description": "Format de média non supporté"},
        422: {"model": ProblemDetails, "description": "Configuration ou vidéo invalide"},
    },
)
async def create_job(
    manager: JobManagerDep,
    store: ResultStoreDep,
    settings: SettingsDep,
    response: Response,
    file: Annotated[UploadFile, File(description="La vidéo à analyser.")],
    request: Annotated[str, Form(description="`AnalysisRequestSchema` sérialisée en JSON.")],
) -> JobCreatedSchema:
    config_schema = _parse_request(request)
    job_id = uuid4().hex
    suffix = _validated_suffix(file.filename)

    destination = store.input_path(job_id, suffix)
    try:
        size = await _write_upload(file, destination, settings.max_upload_bytes)
        info = manager_probe(manager, destination)
    except Exception:
        # Tout échec avant l'acceptation ne doit laisser **aucun résidu** : ni
        # répertoire, ni fichier partiel. Un disque qui se remplit de vidéos
        # rejetées est un incident silencieux.
        store.delete(job_id)
        raise

    logger.info(
        "job accepté",
        job_id=job_id,
        model_id=config_schema.model_id,
        size_bytes=size,
        frames=info.frame_count,
    )
    await manager.submit(
        job_id,
        destination,
        config_schema.to_config(),
        file_name=_sanitised_name(file.filename),
        file_size_bytes=size,
        config_json=config_schema.model_dump(by_alias=True, mode="json"),
    )
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return JobCreatedSchema(job_id=job_id)


@router.get(
    "",
    response_model=Page[JobSchema],
    operation_id="listAnalysisJobs",
    summary="Historique paginé des analyses",
    description="Trié par date de création décroissante. Filtrable par statut et par modèle.",
)
async def list_jobs(
    manager: JobManagerDep,
    page: Annotated[PageParams, Depends(page_params)],
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    model_id: Annotated[str | None, Query()] = None,
) -> Page[JobSchema]:
    result = await manager.list(JobFilters(status=job_status, model_id=model_id), page)
    return Page.of(
        [JobSchema.model_validate(manager.describe(job)) for job in result.items],
        total=result.total,
        params=page,
    )


@router.get(
    "/{job_id}",
    response_model=JobSchema,
    operation_id="getAnalysisJob",
    summary="Statut et progression d'un job",
    description=(
        "Le client interroge cette route toutes les 3 s **en complément** du SSE : "
        "un flux peut tomber (proxy, onglet mis en veille), et la barre de "
        "progression ne doit pas rester figée pour autant."
    ),
    responses={404: {"model": ProblemDetails, "description": "Job inconnu"}},
)
async def get_job(manager: JobManagerDep, job_id: str) -> JobSchema:
    return JobSchema.model_validate(manager.describe(await manager.get(job_id)))


@router.get(
    "/{job_id}/config",
    response_model=JobDetailSchema,
    operation_id="getAnalysisJobConfig",
    summary="Job et configuration qui l'a produit",
    description=(
        "Rend le job **avec** `configJson`, la requête telle qu'elle a été reçue.\n\n"
        "Route distincte de `GET /jobs/{id}` **volontairement** : cette dernière est "
        "sondée toutes les 3 secondes pendant l'analyse, et y joindre la géométrie "
        "complète la ferait voyager des centaines de fois pour une valeur qui ne "
        "change jamais.\n\n"
        "Sert deux gestes de l'interface : **ouvrir** une analyse de l'historique en "
        "rechargeant son tracé dans le studio, et **relancer** avec les mêmes "
        "réglages — ce qui crée un nouveau job et ne mute jamais l'ancien."
    ),
    responses={404: {"model": ProblemDetails, "description": "Job inconnu"}},
)
async def get_job_config(manager: JobManagerDep, job_id: str) -> JobDetailSchema:
    record = await manager.get(job_id)
    return JobDetailSchema.model_validate(
        {**manager.describe(record), "configJson": record.config_json}
    )


@router.get(
    "/{job_id}/result",
    operation_id="getAnalysisResult",
    summary="Résultat complet d'une analyse",
    description=(
        "Servi tel quel depuis le fichier `result.json.gz`. C'est la seule route "
        "qui ne rend pas un modèle validé : revalider une timeline de 54 000 "
        "lignes doublerait la mémoire pour rien.\n\n"
        "Un résultat est **immuable**, d'où le cache très long."
    ),
    responses={
        200: {"content": {"application/json": {}}, "description": "Résultat (gzip)"},
        404: {"model": ProblemDetails, "description": "Job inconnu"},
        409: {"model": ProblemDetails, "description": "Job non terminé, ou résultat purgé"},
    },
)
async def get_result(manager: JobManagerDep, job_id: str) -> FileResponse:
    path = await manager.result_path(job_id)
    return FileResponse(
        path,
        media_type="application/json",
        headers={
            # Le fichier est déjà gzippé sur disque : on l'annonce, et le
            # navigateur le décompresse nativement.
            "Content-Encoding": "gzip",
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )


@router.delete(
    "/{job_id}",
    response_model=JobSchema,
    operation_id="cancelOrPurgeAnalysisJob",
    summary="Annule un job en cours, purge un job terminé",
    description=(
        "Un seul geste côté utilisateur — « je ne veux plus de ce job » — donc une "
        "seule route. Sur un job actif, l'annulation est **coopérative** : "
        "l'analyse s'arrête entre deux images, ce qui laisse le modèle se libérer "
        "proprement."
    ),
    responses={404: {"model": ProblemDetails, "description": "Job inconnu"}},
)
async def delete_job(manager: JobManagerDep, job_id: str) -> JobSchema:
    return JobSchema.model_validate(manager.describe(await manager.cancel_or_purge(job_id)))


@router.post(
    "/{job_id}/pause",
    response_model=JobSchema,
    operation_id="pauseAnalysisJob",
    summary="Suspend une analyse en cours",
    description=(
        "L'analyse s'arrête **entre deux images**, comme l'annulation : le "
        "décodeur garde sa position, le suivi garde ses identités, les compteurs "
        "gardent leurs totaux. Reprendre continue la même analyse ; relancer en "
        "commencerait une autre, avec d'autres identités.\n\n"
        "**Un job suspendu occupe toujours le serveur** : sa place de calcul et "
        "le bail de son modèle restent pris, donc un job en file d'attente "
        "continue d'attendre. C'est le prix d'une reprise exacte.\n\n"
        "409 si le job n'est pas en cours — `job_not_running`."
    ),
    responses={
        404: {"model": ProblemDetails, "description": "Job inconnu"},
        409: {"model": ProblemDetails, "description": "Le job n'est pas en cours"},
    },
)
async def pause_job(manager: JobManagerDep, job_id: str) -> JobSchema:
    return JobSchema.model_validate(manager.describe(await manager.pause(job_id)))


@router.post(
    "/{job_id}/resume",
    response_model=JobSchema,
    operation_id="resumeAnalysisJob",
    summary="Reprend une analyse suspendue",
    description=(
        "Reprend là où la suspension a eu lieu. Le temps passé en pause est "
        "**retranché de la cadence** rapportée : une analyse suspendue une heure "
        "n'a pas ralenti, elle a attendu.\n\n"
        "409 si le job n'est pas suspendu — `job_not_paused`."
    ),
    responses={
        404: {"model": ProblemDetails, "description": "Job inconnu"},
        409: {"model": ProblemDetails, "description": "Le job n'est pas suspendu"},
    },
)
async def resume_job(manager: JobManagerDep, job_id: str) -> JobSchema:
    return JobSchema.model_validate(manager.describe(await manager.resume(job_id)))


# ── Fonctions internes ───────────────────────────────────────────────────────


def _parse_request(raw: str) -> AnalysisRequestSchema:
    """Valide le champ `request` du multipart.

    Le traduire ici plutôt que de laisser FastAPI le faire : le champ est une
    chaîne du point de vue du multipart, donc une `ValidationError` brute
    n'indiquerait pas quel champ *de la configuration* est fautif.
    """
    try:
        return AnalysisRequestSchema.model_validate_json(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])} : {error['msg']}"
            for error in exc.errors()
        )
        raise ValidationAppError(f"Configuration d'analyse invalide — {details}.") from exc


def _validated_suffix(filename: str | None) -> str:
    from pathlib import PurePosixPath

    suffix = PurePosixPath(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise UnsupportedMediaError(
            f"Format non supporté. Extensions acceptées : {allowed}.",
        )
    return suffix


def _sanitised_name(filename: str | None) -> str:
    """Nom d'origine, conservé pour l'affichage seulement.

    Il n'est **jamais** utilisé comme chemin — le fichier s'appelle `input<ext>`
    dans un répertoire nommé d'après l'uuid du job. On le nettoie tout de même :
    il finira dans une page HTML et dans des journaux.
    """
    from pathlib import PurePosixPath

    name = PurePosixPath(filename or "video").name
    cleaned = "".join(char for char in name if char.isprintable() and char not in {"\\", "/"})
    return cleaned[:255] or "video"


async def _write_upload(file: UploadFile, destination: Path, max_bytes: int) -> int:
    """Écrit l'upload par morceaux, en refusant dès le dépassement.

    Le compteur est indispensable : `Content-Length` peut mentir (encodage
    `chunked`), donc la seule limite fiable est celle qu'on applique en écrivant.
    """
    written = 0
    with destination.open("wb") as output:
        while chunk := await file.read(CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                raise PayloadTooLargeError(
                    f"Vidéo trop volumineuse : la limite est de {max_bytes // (1024 * 1024)} Mo."
                )
            output.write(chunk)

    if written == 0:
        raise ValidationAppError("Fichier vidéo vide.")
    return written


def manager_probe(manager: JobManager, path: Path) -> VideoInfo:
    """Sonde la vidéo, et **c'est la vraie validation de format**.

    Se fier à l'extension ou au `content-type` annoncé serait une faille : les
    deux viennent du client. Un fichier qui ne s'ouvre pas, ou qui annonce zéro
    image, n'est pas une vidéo analysable.
    """
    try:
        info = manager.probe_video(path)
    except Exception as exc:
        raise UnsupportedMediaError("Ce fichier n'a pas pu être ouvert comme une vidéo.") from exc
    if info.frame_count <= 0:
        raise ValidationAppError("La vidéo ne contient aucune image exploitable.")
    return info
