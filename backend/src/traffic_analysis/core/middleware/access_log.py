"""Journal d'accès structuré.

Remplace `uvicorn.access`, désactivé dans `configure_logging` : son format texte
ne porte pas le `request_id` et ne se corrèle donc à rien.

La durée est mesurée avec `perf_counter`, pas avec l'heure murale : une durée
calculée depuis `datetime.now()` devient négative quand l'horloge du système est
ajustée pendant la requête.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from traffic_analysis.core.logging import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from traffic_analysis.core.middleware.types import CallNext

logger = get_logger("traffic_analysis.access")

# Un flux SSE ou un WebSocket dure des minutes : journaliser sa « durée » à la
# fermeture n'apprend rien sur la latence du service et fausse toute moyenne.
_STREAMING_CONTENT_TYPES = frozenset({"text/event-stream"})


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Une ligne structurée par requête HTTP terminée."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # L'exception est journalisée ici avec le contexte de la requête,
            # puis relancée : le gestionnaire d'exceptions de l'application
            # produit la réponse, ce middleware ne fait que raconter.
            logger.exception(
                "requête en échec",
                method=request.method,
                path=request.url.path,
                duration_ms=round((perf_counter() - started) * 1000, 1),
            )
            raise

        duration_ms = round((perf_counter() - started) * 1000, 1)
        is_stream = response.headers.get("content-type", "").split(";")[0] in (
            _STREAMING_CONTENT_TYPES
        )

        # Une requête lente ou en erreur mérite d'être visible sans passer le
        # service en DEBUG ; le reste reste en debug pour ne pas noyer le journal.
        level = "warning" if response.status_code >= 500 else "debug"
        getattr(logger, level)(
            "requête",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=None if is_stream else duration_ms,
        )
        return response
