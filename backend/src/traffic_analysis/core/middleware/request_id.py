"""Identifiant de corrélation par requête.

Le middleware le plus externe de la pile : tout ce qui se journalise ensuite, y
compris la traduction d'une exception en Problem Details, doit pouvoir le citer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware

from traffic_analysis.core.logging import bind_request_id

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from traffic_analysis.core.middleware.types import CallNext

HEADER_NAME = "X-Request-ID"

# Un identifiant fourni par le client est accepté (une passerelle en amont en
# pose souvent un, et le corréler des deux côtés est tout l'intérêt), mais borné :
# sans limite, un en-tête de 8 Ko finirait recopié dans chaque ligne de journal.
MAX_INBOUND_LENGTH = 128


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attache un identifiant à la requête, au journal et à la réponse."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        inbound = request.headers.get(HEADER_NAME, "").strip()
        request_id = inbound[:MAX_INBOUND_LENGTH] if inbound else uuid4().hex

        bind_request_id(request_id)
        # Posé sur l'état de la requête pour que les gestionnaires d'exceptions le
        # lisent : ils s'exécutent hors de la pile de middlewares, donc le
        # `ContextVar` n'y est pas garanti.
        request.state.request_id = request_id

        response = await call_next(request)
        # `expose_headers` de CORS doit lister cet en-tête, sinon le JavaScript ne
        # le voit pas même s'il est envoyé (piège 45 de prompt/13).
        response.headers[HEADER_NAME] = request_id
        return response
