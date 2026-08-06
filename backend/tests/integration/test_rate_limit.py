"""La limitation de débit, par adresse IP et en fenêtre glissante.

Les tests construisent leur propre application avec des limites **très basses** :
attendre soixante requêtes pour prouver qu'une limite de soixante fonctionne rendrait
la suite lente pour rien, et une limite basse teste exactement le même code.

Aucun test ne dort. La fenêtre glissante est vérifiée sur le régulateur lui-même, en
lui passant le temps en paramètre — un test qui attendrait vraiment soixante secondes
serait insupportable, et un test qui attendrait « un peu » serait à la merci de la
charge de la machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from traffic_analysis.app_factory import create_app
from traffic_analysis.core.middleware.rate_limit import RateLimitMiddleware, Rule
from traffic_analysis.core.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

HEALTH = "/api/v1/health/live"


@pytest.fixture
async def limited_client(tmp_path: object, settings: Settings) -> AsyncIterator[AsyncClient]:
    """Une application dont la limite globale est de **trois** requêtes par minute."""
    tight = settings.model_copy(update={"rate_limit_per_minute": 3})
    app = create_app(tight)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


class TestLimiteGlobale:
    async def test_les_requetes_sous_la_limite_passent(self, limited_client: AsyncClient) -> None:
        for _ in range(3):
            assert (await limited_client.get(HEALTH)).status_code == 200

    async def test_la_requete_de_trop_est_refusee_en_429(self, limited_client: AsyncClient) -> None:
        for _ in range(3):
            await limited_client.get(HEALTH)

        response = await limited_client.get(HEALTH)

        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"

    async def test_le_refus_porte_un_retry_after_exploitable(
        self, limited_client: AsyncClient
    ) -> None:
        """Sans lui, le client ne peut que réessayer au hasard.

        `Retry-After` est aussi dans `expose_headers` du CORS : sans cela le
        JavaScript ne le verrait pas, même envoyé.
        """
        for _ in range(4):
            response = await limited_client.get(HEALTH)

        assert int(response.headers["Retry-After"]) >= 1

    async def test_le_refus_est_un_problem_details(self, limited_client: AsyncClient) -> None:
        # Le même contrat d'erreur que partout ailleurs : le frontend branche sur
        # `code`, pas sur le texte.
        for _ in range(4):
            response = await limited_client.get(HEALTH)

        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["status"] == 429
        assert "Réessayez" in body["detail"]

    async def test_le_refus_porte_les_en_tetes_de_securite(
        self, limited_client: AsyncClient
    ) -> None:
        """Le middleware de débit est **sous** celui des en-têtes de sécurité.

        Une réponse 429 nue, sans `X-Content-Type-Options` ni `X-Frame-Options`,
        serait un trou dans la politique — d'autant plus facile à atteindre qu'il
        suffit d'une rafale pour la provoquer.
        """
        for _ in range(4):
            response = await limited_client.get(HEALTH)

        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"


class TestDesactivation:
    async def test_une_limite_a_zero_desactive_le_garde_fou(self, settings: Settings) -> None:
        """`0` signifie « désactivée », jamais « tout refuser ».

        L'inverse serait catastrophique et silencieux : un déploiement derrière une
        passerelle qui limite déjà poserait `0` en croyant relâcher, et le service
        refuserait toutes les requêtes.
        """
        app = create_app(settings.model_copy(update={"rate_limit_per_minute": 0}))
        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            for _ in range(20):
                assert (await client.get(HEALTH)).status_code == 200


class TestFenetreGlissante:
    """Le régulateur seul, avec le temps en paramètre.

    Une fenêtre glissante plutôt qu'un compteur remis à zéro à intervalle fixe : ce
    dernier autorise deux fois la limite à cheval sur la remise à zéro — dix
    requêtes à 59 s puis dix à 61 s passent, alors que vingt en deux secondes est
    exactement ce qu'on refuse.
    """

    def _limiter(self, count: int = 2, per: float = 60.0) -> RateLimitMiddleware:
        async def _noop(scope: object, receive: object, send: object) -> None: ...

        return RateLimitMiddleware(_noop, rules=[Rule(count, per)])  # type: ignore[arg-type]

    def test_la_fenetre_libere_les_creneaux_les_plus_anciens(self) -> None:
        limiter = self._limiter(count=2, per=60.0)

        assert limiter._register("ip", "/x", "GET", 0.0) is None
        assert limiter._register("ip", "/x", "GET", 1.0) is None
        assert limiter._register("ip", "/x", "GET", 2.0) is not None
        # À 61 s, la requête de l'instant 0 est sortie de la fenêtre.
        assert limiter._register("ip", "/x", "GET", 61.0) is None

    def test_le_delai_annonce_correspond_a_la_sortie_du_plus_ancien(self) -> None:
        # Ce qui rend `Retry-After` honnête : réessayer après ce délai réussit.
        limiter = self._limiter(count=1, per=60.0)
        limiter._register("ip", "/x", "GET", 0.0)

        retry_after = limiter._register("ip", "/x", "GET", 10.0)

        assert retry_after == 51  # 60 - 10, arrondi au-dessus

    def test_un_refus_ne_prolonge_pas_le_bannissement(self) -> None:
        """Une requête refusée n'est **pas** comptée.

        Sinon un client qui martèle repousserait indéfiniment sa propre
        réouverture, alors même qu'il respecte déjà le refus qu'on vient de lui
        envoyer — un bannissement qui s'auto-entretient.
        """
        limiter = self._limiter(count=1, per=60.0)
        limiter._register("ip", "/x", "GET", 0.0)
        for instant in (10.0, 20.0, 30.0, 40.0, 50.0):
            limiter._register("ip", "/x", "GET", instant)

        assert limiter._register("ip", "/x", "GET", 61.0) is None

    def test_deux_adresses_ont_des_compteurs_separes(self) -> None:
        limiter = self._limiter(count=1, per=60.0)

        assert limiter._register("a", "/x", "GET", 0.0) is None
        assert limiter._register("b", "/x", "GET", 0.0) is None

    def test_une_regle_de_chemin_ne_bride_pas_les_autres_routes(self) -> None:
        """Chaque règle a sa propre file.

        Une file partagée ferait étrangler tout le service par la règle la plus
        stricte : dix dépôts épuiseraient le quota des lectures de santé.
        """

        async def _noop(scope: object, receive: object, send: object) -> None: ...

        limiter = RateLimitMiddleware(
            _noop,  # type: ignore[arg-type]
            rules=[Rule(100, 60.0), Rule(1, 60.0, prefixes=("/api/v1/jobs",), methods=("POST",))],
        )

        assert limiter._register("ip", "/api/v1/jobs", "POST", 0.0) is None
        assert limiter._register("ip", "/api/v1/jobs", "POST", 1.0) is not None
        # La lecture reste possible : c'est la règle `POST /jobs` qui est épuisée,
        # pas la globale.
        assert limiter._register("ip", "/api/v1/jobs", "GET", 2.0) is None
        assert limiter._register("ip", "/api/v1/health/live", "GET", 3.0) is None

    def test_la_methode_est_prise_en_compte(self) -> None:
        # Sonder la progression toutes les 3 s est une lecture bon marché : la
        # brider à dix par minute casserait l'interface.
        async def _noop(scope: object, receive: object, send: object) -> None: ...

        limiter = RateLimitMiddleware(
            _noop,  # type: ignore[arg-type]
            rules=[Rule(1, 60.0, prefixes=("/api/v1/jobs",), methods=("POST",))],
        )

        for instant in range(30):
            assert limiter._register("ip", "/api/v1/jobs/abc", "GET", float(instant)) is None
