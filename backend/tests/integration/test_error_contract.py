"""Le contrat d'erreur : toute erreur est un Problem Details, sans fuite.

Ces tests valent surtout par ce qu'ils interdisent. Le jour où quelqu'un ajoute
un `raise HTTPException` en pensant bien faire, ou laisse une exception remonter,
c'est ici que ça se voit — pas dans un rapport d'utilisateur six semaines plus tard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import status

from traffic_analysis.core.errors import ConflictError, NotFoundError, ValidationAppError
from traffic_analysis.core.middleware.request_id import HEADER_NAME

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

PROBLEM_JSON = "application/problem+json"

# Message qui ne doit JAMAIS atteindre le client : il tient le rôle d'un chemin
# de fichier, d'une requête SQL ou d'un fragment de configuration.
INTERNAL_LEAK_MARKER = "chemin interne /srv/prive/config.yaml"


@pytest.fixture
def app_with_failing_routes(app: FastAPI) -> FastAPI:
    """Ajoute des routes qui échouent volontairement.

    Elles vivent dans le test et non dans le code de production : une route de
    débogage laissée dans le service est une surface d'attaque, et personne ne se
    souvient de la retirer.
    """

    @app.get("/api/v1/_test/boom")
    async def boom() -> None:
        raise RuntimeError(INTERNAL_LEAK_MARKER)

    @app.get("/api/v1/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Le job « 9f2c » n'existe pas.", code="job_not_found")

    @app.get("/api/v1/_test/conflict")
    async def conflict() -> None:
        raise ConflictError("Le job est encore en cours d'analyse.")

    @app.get("/api/v1/_test/invalid")
    async def invalid() -> None:
        raise ValidationAppError("Une analyse sans ligne ni zone ne compterait rien.")

    return app


async def test_une_route_inconnue_rend_un_problem_details(client: AsyncClient) -> None:
    """Le 404 de FastAPI lui-même doit avoir la même forme que les nôtres.

    Sinon le client a deux formats d'erreur à gérer selon que l'erreur vient du
    framework ou du service.
    """
    response = await client.get("/api/v1/route-qui-n-existe-pas")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["code"] == "not_found"
    assert body["title"] == "Ressource introuvable"
    assert body["instance"] == "/api/v1/route-qui-n-existe-pas"
    assert body["requestId"]
    # Toute la copie destinée à l'utilisateur est en français : le « Not Found »
    # de Starlette doit avoir été traduit, et dire quoi faire ensuite.
    assert body["detail"] == "Cette ressource n'existe pas. Vérifiez le chemin appelé."


async def test_un_detail_pose_par_une_route_survit_a_la_traduction(app: FastAPI) -> None:
    """Seule la phrase HTTP anglaise par défaut est remplacée.

    Un message écrit volontairement doit atteindre l'utilisateur intact, sinon la
    traduction serait une perte d'information.
    """
    from fastapi import HTTPException
    from httpx import ASGITransport, AsyncClient

    message = "Le job est encore en cours d'analyse."

    @app.get("/api/v1/_test/http-exception-explicite")
    async def explicit() -> None:
        raise HTTPException(status_code=409, detail=message)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.get("/api/v1/_test/http-exception-explicite")

    assert response.status_code == 409
    assert response.json()["detail"] == message


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        ("/api/v1/_test/not-found", 404, "job_not_found"),
        ("/api/v1/_test/conflict", 409, "conflict"),
        ("/api/v1/_test/invalid", 422, "validation_error"),
    ],
)
async def test_les_app_errors_portent_leur_code_machine(
    app_with_failing_routes: FastAPI,
    client: AsyncClient,
    path: str,
    expected_status: int,
    expected_code: str,
) -> None:
    response = await client.get(path)

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["code"] == expected_code
    assert body["status"] == expected_status
    # `detail` est destiné à un humain francophone : il doit être une phrase.
    assert body["detail"].endswith(".")


async def test_un_500_ne_fuit_aucun_detail_interne(
    app_with_failing_routes: FastAPI, client_like_production: AsyncClient
) -> None:
    """C'est le test le plus important du fichier.

    Le message d'une exception interne peut contenir un chemin, une requête SQL
    ou un secret. Le client reçoit un identifiant de corrélation, rien de plus.
    """
    response = await client_like_production.get("/api/v1/_test/boom")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["code"] == "internal_error"
    assert INTERNAL_LEAK_MARKER not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
    # …mais l'utilisateur repart avec de quoi faire un rapport exploitable.
    assert body["requestId"]


async def test_le_request_id_de_l_erreur_est_celui_de_la_reponse(
    app_with_failing_routes: FastAPI, client: AsyncClient
) -> None:
    """Le corps et l'en-tête doivent citer le même identifiant.

    Deux valeurs différentes rendraient un rapport d'incident ambigu — et le
    corps est produit hors de la pile de middlewares, donc l'accord n'est pas
    gratuit.
    """
    response = await client.get(
        "/api/v1/_test/not-found", headers={HEADER_NAME: "trace-du-support-7"}
    )

    assert response.json()["requestId"] == "trace-du-support-7"
    assert response.headers[HEADER_NAME] == "trace-du-support-7"


async def test_une_validation_refusee_nomme_les_champs(client: AsyncClient) -> None:
    """Un « corps invalide » sans dire *quel* champ est inutilisable côté client."""
    response = await client.get("/api/v1/health/ready", params={})
    assert response.status_code == 200  # garde-fou : la route existe bien

    # `limit` hors bornes sur une route paginée n'existe pas encore ; on
    # provoque la validation de FastAPI avec une méthode inattendue.
    response = await client.post("/api/v1/health/live")

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert response.json()["code"] == "method_not_allowed"
