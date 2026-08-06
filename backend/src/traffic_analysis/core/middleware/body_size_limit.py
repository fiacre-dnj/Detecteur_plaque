"""Limite de taille du corps de requête.

Deux vérifications, parce qu'une seule ne suffit pas :

1. **Avant lecture**, sur `Content-Length` : refuser tout de suite évite de lire
   800 Mo pour les jeter ensuite.
2. **Pendant la lecture**, en comptant les octets : `Content-Length` peut mentir
   ou être absent (`Transfer-Encoding: chunked`), et c'est alors la seule limite
   réellement applicable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from traffic_analysis.core.errors import PayloadTooLargeError, title_for
from traffic_analysis.core.middleware.security_headers import headers_for_short_circuit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

STATUS = 413
PROBLEM_JSON = "application/problem+json"


class BodySizeLimitMiddleware:
    """Refuse un corps trop volumineux, annoncé ou constaté.

    Middleware ASGI brut et non `BaseHTTPMiddleware` : ce dernier matérialise le
    corps pour le passer à la suite, ce qui reviendrait à charger en mémoire
    exactement ce qu'on cherche à refuser.

    **Il produit sa réponse lui-même.** Les gestionnaires d'exceptions de
    l'application sont enregistrés *à l'intérieur* de la pile de middlewares :
    une exception levée ici passerait au-dessus d'eux et remonterait en 500 nu,
    sans en-tête CORS ni identifiant de corrélation.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            await self._refuse(scope, receive, send)
            return

        try:
            await self._app(scope, self._counting(receive), send)
        except PayloadTooLargeError:
            # Le dépassement a été constaté en cours de lecture : la réponse n'a
            # pas encore commencé, on peut encore refuser proprement.
            await self._refuse(scope, receive, send)

    def _counting(self, receive: Receive) -> Callable[[], Awaitable[Message]]:
        """Enveloppe `receive` d'un compteur d'octets réellement transmis.

        Indispensable en plus de `Content-Length` : l'en-tête peut mentir ou être
        absent (`Transfer-Encoding: chunked`), et c'est alors la seule limite
        réellement applicable.
        """
        received = 0

        async def wrapped() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise PayloadTooLargeError(self._message())
            return message

        return wrapped

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Rend un Problem Details, de la même forme que toutes les erreurs.

        **Les en-têtes de sécurité sont posés ici**, comme pour le 429 de la limite
        de débit et pour la même raison : `SecurityHeadersMiddleware` hérite de
        `BaseHTTPMiddleware`, qui ne décore que ce qui passe par son `call_next`.
        Une réponse envoyée directement à `send` depuis un middleware ASGI brut
        sortirait nue — et un 413 est trivial à provoquer de l'extérieur.
        """
        response = JSONResponse(
            status_code=STATUS,
            headers=headers_for_short_circuit(),
            content={
                "type": "about:blank",
                "title": title_for(STATUS),
                "status": STATUS,
                "detail": self._message(),
                "code": "payload_too_large",
                "instance": scope.get("path"),
                "requestId": Headers(scope=scope).get("x-request-id"),
            },
            media_type=PROBLEM_JSON,
        )
        await response(scope, receive, send)

    def _message(self) -> str:
        return (
            "Le contenu envoyé dépasse la taille maximale acceptée "
            f"({self._max_bytes // (1024 * 1024)} Mo)."
        )
