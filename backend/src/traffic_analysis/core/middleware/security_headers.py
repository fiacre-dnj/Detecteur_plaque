"""En-têtes de sécurité, posés sur **toutes** les réponses.

Tous en `setdefault` : une route qui a délibérément posé un `Cache-Control` — le
résultat immuable d'un job, par exemple — ne doit pas se le faire écraser par une
politique générique.

**COEP `require-corp` n'est pas ici, et c'est délibéré.** Ce besoin venait
d'ONNX Runtime Web, qui exigeait `SharedArrayBuffer`. Avec l'analyse
exclusivement backend il disparaît, et COEP casse le chargement de ressources
sans rien apporter (voir docs/adr/0003).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from traffic_analysis.core.middleware.types import CallNext

# `blob:` est **indispensable** dans `img-src` et `media-src` : la vidéo locale et
# les frames capturées par la webcam sont des blobs, et sans lui la scène reste
# noire sans le moindre message.
#
# `style-src 'unsafe-inline'` : Tailwind injecte des styles au runtime pour les
# valeurs arbitraires. Le retirer casserait la mise en page ; le risque XSS reste
# borné puisque `script-src` n'accepte que 'self'.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self'",
        "connect-src 'self' ws: wss:",
        "object-src 'none'",
        # Remplace `X-Frame-Options` sur les navigateurs modernes ; l'en-tête
        # historique reste posé pour les anciens.
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    )
)

BASE_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # La webcam est nécessaire au mode temps réel ; tout le reste ne l'est pas.
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=()",
    "X-Frame-Options": "DENY",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# HSTS **en production seulement** : sur un poste de développement en HTTP, il
# épinglerait `localhost` en HTTPS dans le navigateur, et le développeur ne
# pourrait plus atteindre son propre service — pour six mois.
HSTS_HEADER = ("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Pose les en-têtes de sécurité et retire la signature du serveur."""

    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        super().__init__(app)
        self._production = production

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        response = await call_next(request)

        for name, value in BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        if self._production:
            response.headers.setdefault(*HSTS_HEADER)

        # Une réponse d'API dynamique mise en cache est une réponse fausse : un
        # statut de job figé ferait croire à une analyse bloquée.
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"

        # Ne pas annoncer uvicorn et sa version : c'est une information gratuite
        # offerte à qui cherche une vulnérabilité connue.
        if "server" in response.headers:
            del response.headers["server"]
        return response
