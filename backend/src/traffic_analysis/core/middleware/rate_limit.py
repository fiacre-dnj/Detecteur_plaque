"""Limitation de débit par adresse IP, en fenêtre glissante.

**Écrit à la main plutôt qu'avec `slowapi`**, et pour une raison concrète : slowapi
fonctionne par décorateur sur chaque route et exige un paramètre `request: Request`
dans leur signature, ce qui polluerait vingt-huit routes pour une politique qui se
décrit en trois lignes. Il ne protégeait pas non plus le handshake WebSocket, que
`prompt/06` §4 demande explicitement de limiter. Un middleware ASGI voit tout ce qui
entre, y compris le `websocket` scope.

**Fenêtre glissante et non compteur par intervalle fixe.** Un compteur remis à zéro
toutes les minutes autorise deux fois la limite à cheval sur la remise à zéro — dix
requêtes à 59 s puis dix à 61 s passent, alors que vingt en deux secondes est
exactement ce qu'on refuse. La fenêtre glissante n'a pas ce trou.

**L'état est en mémoire du processus.** Le service tourne avec un seul worker (voir
`backend/Dockerfile`), donc une mémoire partagée n'apporterait rien ; y mettre Redis
ajouterait une dépendance opérationnelle pour une garantie que personne n'utilise
ici. Si le service passait un jour à plusieurs répliques, cette limite deviendrait
« par réplique » — et c'est écrit ici pour que la découverte ne se fasse pas en
production.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from traffic_analysis.core.errors import title_for
from traffic_analysis.core.middleware.security_headers import headers_for_short_circuit

if TYPE_CHECKING:
    from collections.abc import Iterable

STATUS = 429
PROBLEM_JSON = "application/problem+json"

#: Au-delà, le dictionnaire des compteurs est purgé des adresses inactives. Sans
#: cette purge, une IP par visiteur s'accumulerait indéfiniment — une fuite mémoire
#: lente, du genre qui ne se voit qu'après trois semaines de production.
_SWEEP_EVERY = 512


class Rule:
    """Une limite : `count` requêtes par `per_seconds`, sur les chemins donnés.

    `prefixes` vide signifie « toutes les requêtes » — c'est la limite globale.
    """

    __slots__ = ("count", "methods", "per_seconds", "prefixes")

    def __init__(
        self,
        count: int,
        per_seconds: float,
        *,
        prefixes: tuple[str, ...] = (),
        methods: tuple[str, ...] = (),
    ) -> None:
        self.count = count
        self.per_seconds = per_seconds
        self.prefixes = prefixes
        self.methods = methods

    def matches(self, path: str, method: str) -> bool:
        if self.methods and method not in self.methods:
            return False
        if not self.prefixes:
            return True
        return any(path.startswith(prefix) for prefix in self.prefixes)

    @property
    def key(self) -> str:
        """Identifiant de la règle, pour séparer les compteurs.

        Une seule file par (IP, règle) : mélanger les règles ferait décompter une
        requête de dépôt sur le quota global **et** sur le sien, ce qui est correct,
        mais dans la *même* file — et la limite la plus stricte étranglerait alors
        toutes les autres routes.
        """
        return f"{self.count}/{self.per_seconds}/{','.join(self.prefixes)}"


class RateLimitMiddleware:
    """Refuse les requêtes au-delà du débit autorisé, avec `Retry-After`.

    Produit sa réponse lui-même, comme `BodySizeLimitMiddleware` et pour la même
    raison : les gestionnaires d'exceptions sont enregistrés *à l'intérieur* de la
    pile, donc une exception levée ici remonterait en 500 nu, sans en-tête CORS ni
    identifiant de corrélation.

    Un WebSocket refusé est **fermé** plutôt que répondu : on ne peut pas renvoyer
    de JSON sur un handshake. Le code 1013 « try again later » est celui que le
    client sait interpréter (voir `realtime/api/protocol.py`).
    """

    def __init__(self, app: ASGIApp, *, rules: Iterable[Rule], enabled: bool = True) -> None:
        self._app = app
        self._rules = tuple(rules)
        self._enabled = enabled
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._since_sweep = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._enabled or scope["type"] not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return

        client = _client_of(scope)
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET"))
        now = time.monotonic()

        retry_after = self._register(client, path, method, now)
        if retry_after is None:
            await self._app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await _reject_websocket(send)
            return
        await _reject_http(retry_after, scope, receive, send)

    def _register(self, client: str, path: str, method: str, now: float) -> int | None:
        """Enregistre la requête, ou rend le délai d'attente si elle dépasse.

        **Aucun compteur n'est incrémenté quand une règle refuse.** Sinon une rafale
        continue de remplir les files et prolonge indéfiniment le bannissement,
        alors que le client respecte déjà le refus qu'on vient de lui envoyer.
        """
        self._maybe_sweep(now)

        matching = [rule for rule in self._rules if rule.matches(path, method)]
        # Vérifier **toutes** les règles avant d'enregistrer quoi que ce soit :
        # enregistrer au fil de l'eau laisserait un compteur incrémenté sur une
        # requête finalement refusée par une règle suivante.
        for rule in matching:
            window = self._hits[(client, rule.key)]
            _drop_expired(window, now - rule.per_seconds)
            if len(window) >= rule.count:
                oldest = window[0]
                return max(1, int(rule.per_seconds - (now - oldest)) + 1)

        for rule in matching:
            self._hits[(client, rule.key)].append(now)
        return None

    def _maybe_sweep(self, now: float) -> None:
        """Oublie les adresses dont plus aucune requête n'est dans sa fenêtre."""
        self._since_sweep += 1
        if self._since_sweep < _SWEEP_EVERY:
            return
        self._since_sweep = 0
        # La fenêtre la plus longue borne ce qu'on doit garder : au-delà, aucune
        # règle ne peut plus s'appuyer sur ces horodatages.
        longest = max((rule.per_seconds for rule in self._rules), default=0.0)
        cutoff = now - longest
        stale = [key for key, window in self._hits.items() if not window or window[-1] < cutoff]
        for key in stale:
            del self._hits[key]


def _drop_expired(window: deque[float], cutoff: float) -> None:
    while window and window[0] < cutoff:
        window.popleft()


def _client_of(scope: Scope) -> str:
    """L'adresse du client, ou `"?"`.

    **`X-Forwarded-For` n'est pas lu**, délibérément. Cet en-tête est trivial à
    forger : le lire sans savoir qu'un proxy de confiance le pose transformerait la
    limite en simple formalité — un attaquant enverrait une adresse différente à
    chaque requête. Derrière un proxy, c'est à lui de limiter, ou au service de
    tourner avec `--forwarded-allow-ips` correctement réglé.

    L'adresse **n'est pas journalisée** : elle sert de clé de dictionnaire et rien
    d'autre.
    """
    client = scope.get("client")
    if not client:
        return "?"
    return str(client[0])


async def _reject_http(retry_after: int, scope: Scope, receive: Receive, send: Send) -> None:
    """Émet le 429, **en-têtes de sécurité compris**.

    Ils sont posés ici, et c'est nécessaire : `SecurityHeadersMiddleware` hérite de
    `BaseHTTPMiddleware`, qui ne décore que les réponses passées par son
    `call_next`. Un middleware ASGI brut placé en dessous — comme celui-ci, ou comme
    `BodySizeLimitMiddleware` — court-circuite vers `send` et sort donc **sans
    aucun en-tête de sécurité**. Un 429 nu, d'autant plus fâcheux qu'une simple
    rafale suffit à le provoquer.

    Les valeurs viennent de `headers_for_short_circuit()`, jamais recopiées : un
    en-tête ajouté à la politique arrive ici automatiquement. Trouvé par le test
    `test_le_refus_porte_les_en_tetes_de_securite`.
    """
    response = JSONResponse(
        status_code=STATUS,
        media_type=PROBLEM_JSON,
        headers={"Retry-After": str(retry_after), **headers_for_short_circuit()},
        content={
            "type": "about:blank",
            "title": title_for(STATUS),
            "status": STATUS,
            "detail": (
                "Trop de requêtes en peu de temps. "
                f"Réessayez dans {retry_after} seconde{'s' if retry_after > 1 else ''}."
            ),
            "code": "rate_limited",
        },
    )
    await response(scope, receive, send)


async def _reject_websocket(send: Send) -> None:
    # Refus **avant** l'acceptation : le handshake échoue au niveau HTTP et la
    # connexion WebSocket n'existe jamais.
    await send({"type": "websocket.close", "code": 1013})
