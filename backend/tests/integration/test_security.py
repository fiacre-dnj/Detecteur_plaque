"""En-têtes de sécurité, CORS, limite de corps et qualité du schéma OpenAPI.

Ces tests protègent des régressions qu'aucune fonctionnalité ne révélerait :
retirer un en-tête ne casse rien de visible, jusqu'au jour où ça compte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from traffic_analysis.core.middleware.security_headers import BASE_HEADERS

if TYPE_CHECKING:
    from httpx import AsyncClient

    from traffic_analysis.core.clock import FrozenClock
    from traffic_analysis.core.settings import Settings

ALLOWED_ORIGIN = "http://localhost:5173"


class TestEnTetesDeSecurite:
    @pytest.mark.parametrize("header", sorted(BASE_HEADERS))
    async def test_chaque_en_tete_du_tableau_est_pose(
        self, client: AsyncClient, header: str
    ) -> None:
        """Test paramétré sur le tableau de prompt/06 §3.

        Paramétré et non une seule assertion : l'échec nomme l'en-tête manquant.
        """
        response = await client.get("/api/v1/health/live")

        assert response.headers.get(header) == BASE_HEADERS[header]

    async def test_la_csp_autorise_les_blobs_pour_la_video_et_la_webcam(
        self, client: AsyncClient
    ) -> None:
        """`blob:` est **indispensable** : la vidéo locale et les frames capturées
        en sont. Sans lui, la scène reste noire sans le moindre message."""
        policy = (await client.get("/api/v1/health/live")).headers["content-security-policy"]

        assert "img-src 'self' data: blob:" in policy
        assert "media-src 'self' blob:" in policy

    async def test_la_csp_ne_reintroduit_pas_coep(self, client: AsyncClient) -> None:
        """COEP venait d'ONNX Runtime Web et de son besoin de SharedArrayBuffer.

        Avec l'analyse exclusivement backend il n'a plus d'objet, et il casse le
        chargement de ressources sans rien apporter (ADR 0003).
        """
        headers = (await client.get("/api/v1/health/live")).headers

        assert "cross-origin-embedder-policy" not in headers

    async def test_la_signature_du_serveur_est_retiree(self, client: AsyncClient) -> None:
        """Annoncer « uvicorn 0.30 » est une information offerte gratuitement."""
        assert "server" not in (await client.get("/api/v1/health/live")).headers

    async def test_hsts_est_absent_hors_production(self, client: AsyncClient) -> None:
        """En développement sur HTTP, HSTS épinglerait localhost en HTTPS dans le
        navigateur du développeur — pour six mois."""
        assert "strict-transport-security" not in (await client.get("/api/v1/health/live")).headers

    async def test_une_reponse_d_api_dynamique_n_est_pas_mise_en_cache(
        self, client: AsyncClient
    ) -> None:
        """Un statut de job en cache est un statut faux."""
        assert (await client.get("/api/v1/health")).headers["cache-control"] == "no-store"

    async def test_un_cache_pose_par_une_route_n_est_pas_ecrase(self, client: AsyncClient) -> None:
        """Le résultat d'un job est immuable : sa politique de cache doit survivre
        au middleware générique."""
        import json

        created = await client.post(
            "/api/v1/jobs",
            files={"file": ("clip.mp4", b"\x00" * 512, "video/mp4")},
            data={
                "request": json.dumps(
                    {
                        "modelId": "yolov8n",
                        "lines": [
                            {"id": "l1", "a": {"x": 0, "y": 500}, "b": {"x": 1920, "y": 500}}
                        ],
                    }
                )
            },
        )
        job_id = created.json()["jobId"]

        import asyncio

        async with asyncio.timeout(5.0):
            while (await client.get(f"/api/v1/jobs/{job_id}")).json()["status"] != "done":
                await asyncio.sleep(0.01)

        cache = (await client.get(f"/api/v1/jobs/{job_id}/result")).headers["cache-control"]
        assert "immutable" in cache


class TestCors:
    async def test_un_preflight_d_origine_autorisee_recoit_ses_en_tetes(
        self, client: AsyncClient
    ) -> None:
        response = await client.options(
            "/api/v1/jobs",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
        # 600 s : un préflight par requête serait coûteux, mais 86 400 laisserait
        # un changement de politique en cache une journée entière.
        assert response.headers["access-control-max-age"] == "600"

    async def test_une_origine_inconnue_ne_recoit_aucun_en_tete_cors(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/v1/health/live", headers={"Origin": "https://evil.test"})

        assert "access-control-allow-origin" not in response.headers

    async def test_les_en_tetes_utiles_au_client_sont_exposes(self, client: AsyncClient) -> None:
        """Sans `expose_headers`, le JavaScript ne voit pas ces en-têtes même
        quand le serveur les envoie : le nom du CSV téléchargé et l'identifiant
        de corrélation d'une erreur seraient perdus."""
        response = await client.get("/api/v1/health/live", headers={"Origin": ALLOWED_ORIGIN})

        exposed = response.headers["access-control-expose-headers"].lower()
        assert "content-disposition" in exposed
        assert "x-request-id" in exposed

    async def test_les_deux_formes_de_l_hote_local_sont_autorisees(
        self, settings: Settings
    ) -> None:
        """`localhost` et `127.0.0.1` sont **deux origines** pour le navigateur.

        N'en autoriser qu'une produit le classique « ça marche sur l'une et pas
        sur l'autre » (piège 46 de prompt/13).
        """
        assert "http://localhost:5173" in settings.cors_origins
        assert "http://127.0.0.1:5173" in settings.cors_origins


class TestLimiteDeCorps:
    async def test_un_content_length_trop_grand_est_refuse_avant_lecture(
        self, client: AsyncClient, settings: Settings
    ) -> None:
        """Refuser sur l'annonce évite de lire 800 Mo pour les jeter ensuite."""
        response = await client.post(
            "/api/v1/jobs",
            content=b"x" * 32,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(settings.max_upload_bytes + 1),
            },
        )

        assert response.status_code == 413
        assert response.json()["code"] == "payload_too_large"


class TestOpenApi:
    async def test_le_schema_est_valide_et_documente(self, client: AsyncClient) -> None:
        schema = (await client.get("/api/openapi.json")).json()

        assert schema["openapi"].startswith("3.")
        assert schema["info"]["license"]["name"] == "AGPL-3.0"

    async def test_chaque_route_a_un_operation_id_explicite_et_unique(
        self, client: AsyncClient
    ) -> None:
        """Sans `operation_id`, FastAPI génère `create_job_api_v1_jobs_post` et
        tout client généré devient illisible."""
        schema = (await client.get("/api/openapi.json")).json()

        ids = [
            operation["operationId"]
            for methods in schema["paths"].values()
            for operation in methods.values()
            if isinstance(operation, dict) and "operationId" in operation
        ]

        assert ids, "aucune opération documentée"
        assert len(set(ids)) == len(ids), "des operationId sont dupliqués"
        # Un identifiant généré automatiquement contient le chemin et la méthode.
        assert not [name for name in ids if "_api_v1_" in name]

    async def test_chaque_route_a_un_resume(self, client: AsyncClient) -> None:
        schema = (await client.get("/api/openapi.json")).json()

        missing = [
            f"{method.upper()} {path}"
            for path, methods in schema["paths"].items()
            for method, operation in methods.items()
            if isinstance(operation, dict) and not operation.get("summary")
        ]

        assert not missing, f"routes sans résumé : {missing}"

    async def test_les_schemas_de_securite_sont_declares_pour_plus_tard(
        self, client: AsyncClient
    ) -> None:
        """Point d'extension documenté : le contrat ne changera pas le jour où
        l'authentification arrivera, seule son application changera."""
        schema = (await client.get("/api/openapi.json")).json()

        assert set(schema["components"]["securitySchemes"]) == {"ApiKeyAuth", "BearerAuth"}

    async def test_le_resultat_d_analyse_a_un_schema_malgre_le_fichier(
        self, client: AsyncClient
    ) -> None:
        """La route la plus importante du service est servie en fichier : sans
        schéma manuel, sa réponse ne serait documentée nulle part."""
        schema = (await client.get("/api/openapi.json")).json()

        assert "AnalysisResult" in schema["components"]["schemas"]
        result_route = schema["paths"]["/api/v1/jobs/{job_id}/result"]["get"]
        content = result_route["responses"]["200"]["content"]["application/json"]
        assert content["schema"]["$ref"].endswith("AnalysisResult")

    async def test_les_routes_principales_portent_un_exemple_curl(
        self, client: AsyncClient
    ) -> None:
        schema = (await client.get("/api/openapi.json")).json()

        samples = {
            operation["operationId"]
            for methods in schema["paths"].values()
            for operation in methods.values()
            if isinstance(operation, dict) and operation.get("x-codeSamples")
        }
        assert "createAnalysisJob" in samples

    async def test_les_docs_sont_servies_en_developpement(self, client: AsyncClient) -> None:
        for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
            assert (await client.get(path)).status_code == 200, path


class TestDocumentationDesactivable:
    async def test_docs_desactivees_rendent_404_sur_les_trois_url(
        self, settings: Settings, clock: FrozenClock
    ) -> None:
        """Un `openapi.json` public expose la surface d'attaque complète.

        Le laisser ouvert est un choix légitime ; qu'il soit *le défaut* en
        production ne le serait pas.
        """
        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport
        from httpx import AsyncClient as Client

        from tests.support.engine import FakeEngine
        from traffic_analysis.app_factory import create_app

        closed = settings.model_copy(update={"docs_enabled": False})
        app = create_app(closed, clock=clock, engine=FakeEngine([]))
        transport = ASGITransport(app=app)

        async with (
            LifespanManager(app),
            Client(transport=transport, base_url="http://test") as private,
        ):
            for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
                assert (await private.get(path)).status_code == 404, path
            # …mais le service reste parfaitement utilisable.
            assert (await private.get("/api/v1/health/live")).status_code == 200
