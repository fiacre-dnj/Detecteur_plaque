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

    async def test_rouvrir_un_job_ne_consomme_pas_le_quota_global(
        self, limited_client: AsyncClient
    ) -> None:
        """ADR 0027, sur l'application réelle : trois requêtes de quota, dix lectures.

        Le job n'existe pas — chaque lecture répond 404, pas 200 — mais ce n'est
        pas ce qui est vérifié ici : un 404 prouve que le middleware a laissé
        passer la requête jusqu'à la route, ce qu'un 429 aurait empêché. Le quota
        de trois posé par `limited_client` reste ensuite intact pour `/health`.
        """
        for _ in range(10):
            response = await limited_client.get("/api/v1/jobs/inconnu/config")
            assert response.status_code != 429

        for _ in range(3):
            assert (await limited_client.get(HEALTH)).status_code == 200
        assert (await limited_client.get(HEALTH)).status_code == 429


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

    def test_les_lectures_d_un_job_sont_exemptees_de_la_regle_globale(self) -> None:
        """ADR 0027 : rouvrir une analyse archivée ne doit pas épuiser le quota global.

        Mesuré sur l'application réelle : une vingtaine de requêtes en quelques
        secondes pour un seul clic sur « Ouvrir », dont une quinzaine pour la seule
        vidéo — que le navigateur charge par plages. Sans cette exemption, la
        fonctionnalité même que l'historique promet épuisait le quota prévu pour
        l'ingestion.
        """

        async def _noop(scope: object, receive: object, send: object) -> None: ...

        limiter = RateLimitMiddleware(
            _noop,  # type: ignore[arg-type]
            rules=[Rule(1, 60.0, exempt_get_prefixes=("/api/v1/jobs/",))],
        )

        # Quinze plages vidéo, un statut, une config, un résultat : aucun n'entame
        # le quota d'une seule place.
        for path in (
            "/api/v1/jobs/abc/input",
            "/api/v1/jobs/abc/input",
            "/api/v1/jobs/abc",
            "/api/v1/jobs/abc/config",
            "/api/v1/jobs/abc/result",
            "/api/v1/jobs/abc/events",
        ):
            assert limiter._register("ip", path, "GET", 0.0) is None

        # La règle reste bien vivante : une autre route en consomme le seul crédit.
        assert limiter._register("ip", "/api/v1/health/live", "GET", 0.0) is None
        assert limiter._register("ip", "/api/v1/health/live", "GET", 0.5) is not None

    def test_la_liste_des_jobs_reste_comptee(self) -> None:
        """`GET /jobs` (sans identifiant) n'est **pas** exempté.

        Seules les lectures d'un job précis le sont : la liste paginée de
        l'historique n'a jamais fait partie de la rafale mesurée, et l'exempter
        aussi élargirait la portée du correctif sans raison mesurée.
        """

        async def _noop(scope: object, receive: object, send: object) -> None: ...

        limiter = RateLimitMiddleware(
            _noop,  # type: ignore[arg-type]
            rules=[Rule(1, 60.0, exempt_get_prefixes=("/api/v1/jobs/",))],
        )

        assert limiter._register("ip", "/api/v1/jobs", "GET", 0.0) is None
        assert limiter._register("ip", "/api/v1/jobs", "GET", 0.5) is not None

    def test_seules_les_lectures_sont_exemptees(self) -> None:
        """Déposer, annuler, suspendre ou reprendre un job restent comptés.

        L'exemption vise la relecture d'un résultat, pas les écritures : une
        exemption qui porterait aussi sur `POST`/`DELETE` retirerait la protection
        que `POST /jobs` a précisément sa propre règle pour assurer.
        """

        async def _noop(scope: object, receive: object, send: object) -> None: ...

        limiter = RateLimitMiddleware(
            _noop,  # type: ignore[arg-type]
            rules=[Rule(1, 60.0, exempt_get_prefixes=("/api/v1/jobs/",))],
        )

        assert limiter._register("ip", "/api/v1/jobs/abc", "DELETE", 0.0) is None
        assert limiter._register("ip", "/api/v1/jobs/abc/pause", "POST", 0.5) is not None
