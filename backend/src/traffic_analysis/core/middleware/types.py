"""Alias de types partagés par les middlewares.

`BaseHTTPMiddleware.dispatch` reçoit un `RequestResponseEndpoint`, dont le nom
est plus long que ce qu'il décrit et qui vit dans un module privé de Starlette.
Un alias unique évite d'importer le même détail dans cinq fichiers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

type CallNext = Callable[[Request], Awaitable[Response]]
