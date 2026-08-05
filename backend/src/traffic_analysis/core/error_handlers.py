"""Traduction des exceptions en réponses Problem Details (RFC 9457).

Un seul endroit du service transforme une exception en réponse HTTP. C'est ce qui
permet au domaine de ne rien connaître d'HTTP, et c'est aussi ce qui garantit
qu'aucune trace interne ne fuit dans un corps de réponse.

`Content-Type: application/problem+json` plutôt que `application/json` : c'est ce
que la RFC demande, et c'est ce qui permet au client de distinguer un corps
d'erreur d'un corps métier sans deviner d'après sa forme.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from traffic_analysis.core.errors import AppError, detail_for_framework_error, title_for
from traffic_analysis.core.logging import get_logger
from traffic_analysis.core.schemas import FieldError, ProblemDetails, ValidationProblemDetails

if TYPE_CHECKING:
    from starlette.responses import Response

logger = get_logger("traffic_analysis.errors")

PROBLEM_JSON = "application/problem+json"


def _request_id(request: Request) -> str | None:
    """Identifiant posé par `RequestIdMiddleware`.

    Lu depuis `request.state` et non depuis le `ContextVar` : les gestionnaires
    d'exceptions s'exécutent hors de la pile de middlewares, où le contexte de la
    tâche n'est pas garanti.
    """
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _problem_response(problem: ProblemDetails) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        # `by_alias` est ce qui produit `requestId` et non `request_id` : le
        # contrat est en camelCase, y compris pour les erreurs.
        content=problem.model_dump(by_alias=True, exclude_none=False),
        media_type=PROBLEM_JSON,
    )


async def handle_app_error(request: Request, exc: Exception) -> Response:
    """`AppError` → Problem Details, avec son code machine stable."""
    assert isinstance(exc, AppError)  # noqa: S101 — garanti par l'enregistrement du handler
    problem = ProblemDetails(
        title=title_for(exc.status_code),
        status=exc.status_code,
        detail=exc.detail,
        code=exc.code,
        instance=request.url.path,
        request_id=_request_id(request),
    )
    # Une erreur 5xx applicative est un incident : elle est journalisée avec sa
    # trace. Une 4xx est un usage incorrect de l'API, pas un problème du service.
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("erreur applicative", code=exc.code, path=request.url.path, exc_info=exc)
    else:
        logger.info("requête refusée", code=exc.code, status=exc.status_code)
    return _problem_response(problem)


async def handle_validation_error(request: Request, exc: Exception) -> Response:
    """`RequestValidationError` → 422 Problem Details enrichi de `errors[]`.

    Le détail par champ est conservé parce qu'un « corps invalide » sans dire
    *quel* champ est inutilisable côté client ; il est en revanche traduit en
    français et débarrassé de la valeur reçue, qui pourrait être sensible.
    """
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        FieldError(
            field=_field_path(error.get("loc", ())),
            message=str(error.get("msg", "")),
            type=str(error.get("type", "")),
        )
        for error in exc.errors()
    ]
    problem = ValidationProblemDetails(
        title=title_for(status.HTTP_422_UNPROCESSABLE_CONTENT),
        status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="La requête est syntaxiquement correcte mais son contenu est refusé.",
        code="validation_error",
        instance=request.url.path,
        request_id=_request_id(request),
        errors=errors,
    )
    logger.info("validation refusée", path=request.url.path, fields=[e.field for e in errors])
    return _problem_response(problem)


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    """`HTTPException` → Problem Details.

    FastAPI en lève lui-même (404 de route inconnue, 405, 429 de slowapi) : sans
    ce gestionnaire, le service répondrait tantôt `{"detail": …}` tantôt un
    Problem Details, et le client aurait deux formes d'erreur à gérer.

    Le `detail` anglais du framework (« Not Found ») est traduit ; un `detail`
    posé volontairement par une route est conservé tel quel.
    """
    assert isinstance(exc, HTTPException)  # noqa: S101
    problem = ProblemDetails(
        title=title_for(exc.status_code),
        status=exc.status_code,
        detail=detail_for_framework_error(exc.status_code, str(exc.detail)),
        code=_code_for_status(exc.status_code),
        instance=request.url.path,
        request_id=_request_id(request),
    )
    response = _problem_response(problem)
    # `Retry-After` sur un 429, `Allow` sur un 405 : les en-têtes portés par
    # l'exception sont le contrat, ils ne doivent pas disparaître à la traduction.
    for key, value in (exc.headers or {}).items():
        response.headers[key] = value
    return response


async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
    """Filet de sécurité : trace complète au journal, **rien** dans la réponse.

    Le message d'une exception interne peut contenir un chemin de fichier, une
    requête SQL ou un fragment de configuration. Le client reçoit un code de
    corrélation et rien d'autre ; l'information vit dans le journal.
    """
    logger.exception("exception non gérée", path=request.url.path, exc_info=exc)
    problem = ProblemDetails(
        title=title_for(status.HTTP_500_INTERNAL_SERVER_ERROR),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=(
            "Une erreur interne est survenue. Citez l'identifiant de requête "
            "ci-dessous si vous signalez l'incident."
        ),
        code="internal_error",
        instance=request.url.path,
        request_id=_request_id(request),
    )
    return _problem_response(problem)


def register_error_handlers(app: FastAPI) -> None:
    """Branche les quatre gestionnaires. Appelé par `create_app()`."""
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    # `Exception` doit être enregistré en dernier : c'est le filet, il ne doit
    # jamais intercepter ce qu'un gestionnaire plus précis sait traduire.
    app.add_exception_handler(Exception, handle_unexpected_error)


def _field_path(loc: tuple[Any, ...] | list[Any]) -> str:
    """`("body", "lines", 0, "a")` → `"lines.0.a"`.

    Le premier segment (`body`, `query`, `path`) est retiré : il dit *où* dans la
    requête, ce que le client sait déjà, et il rend le chemin moins lisible.
    """
    parts = [str(part) for part in loc]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    return ".".join(parts) or "(corps)"


_STATUS_CODES: dict[int, str] = {
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_413_CONTENT_TOO_LARGE: "payload_too_large",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_503_SERVICE_UNAVAILABLE: "unavailable",
}


def _code_for_status(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "http_error")
