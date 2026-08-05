"""Les trois sondes de santé, et ce qu'elles promettent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from traffic_analysis import __version__
from traffic_analysis.core.middleware.request_id import HEADER_NAME

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

    from traffic_analysis.core.settings import Settings


async def test_liveness_repond_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_verifie_le_repertoire_de_donnees(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"dataDir": True}


async def test_readiness_degrade_si_le_repertoire_est_inutilisable(
    app: FastAPI, client: AsyncClient, settings: Settings
) -> None:
    """Un volume monté en lecture seule doit se voir dans `ready`, pas au premier job.

    Le répertoire est remplacé par un *fichier* : `mkdir` échoue alors avec une
    `OSError`, exactement comme sur un montage non inscriptible, sans dépendre des
    permissions POSIX (que Windows n'applique pas de la même façon).
    """
    settings.data_dir.parent.mkdir(parents=True, exist_ok=True)
    settings.data_dir.write_bytes(b"ceci n'est pas un repertoire")

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["dataDir"] is False


async def test_health_expose_la_version_et_l_environnement(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "environment": "test",
    }


@pytest.mark.parametrize(
    "path",
    ["/api/v1/health/live", "/api/v1/health/ready", "/api/v1/health"],
)
async def test_chaque_reponse_porte_un_request_id(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.headers[HEADER_NAME]


async def test_un_request_id_fourni_par_le_client_est_conserve(client: AsyncClient) -> None:
    """Une passerelle en amont pose souvent l'identifiant : le corréler des deux
    côtés est tout l'intérêt du mécanisme."""
    response = await client.get(
        "/api/v1/health/live", headers={HEADER_NAME: "correlation-amont-42"}
    )

    assert response.headers[HEADER_NAME] == "correlation-amont-42"


async def test_un_request_id_demesure_est_borne(client: AsyncClient) -> None:
    """Sans borne, un en-tête de plusieurs kilooctets finirait recopié dans
    chaque ligne de journal."""
    response = await client.get("/api/v1/health/live", headers={HEADER_NAME: "x" * 5000})

    assert len(response.headers[HEADER_NAME]) == 128
