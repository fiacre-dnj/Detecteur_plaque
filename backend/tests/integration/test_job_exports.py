"""Registre, franchissements et export CSV, à travers HTTP.

Ces routes existent pour que l'utilisateur puisse **vérifier** un total plutôt que
le croire. Le CSV en est l'aboutissement : il doit s'ouvrir directement dans un
Excel français, sans réencodage ni assistant d'importation.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient

    from traffic_analysis.core.clock import FrozenClock
    from traffic_analysis.core.settings import Settings

LINE = {"id": "l1", "name": "Voie nord", "a": {"x": 0, "y": 500}, "b": {"x": 1920, "y": 500}}


async def _finished_job(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/jobs",
        files={"file": ("carrefour.mp4", b"\x00" * 2048, "video/mp4")},
        data={"request": json.dumps({"modelId": "yolov8n", "lines": [LINE]})},
    )
    job_id: str = response.json()["jobId"]
    async with asyncio.timeout(5.0):
        while True:
            status = (await client.get(f"/api/v1/jobs/{job_id}")).json()["status"]
            if status in {"done", "error", "cancelled"}:
                assert status == "done", f"le job s'est terminé en « {status} »"
                return job_id
            await asyncio.sleep(0.01)


class TestRegistre:
    async def test_le_registre_liste_les_identites(self, client: AsyncClient) -> None:
        job_id = await _finished_job(client)

        body = (await client.get(f"/api/v1/jobs/{job_id}/vehicles")).json()

        assert body["total"] == 2
        vehicle = body["items"][0]
        assert vehicle["globalId"] == 1
        assert vehicle["label"] in {"car", "truck"}
        assert vehicle["crossedLines"][0]["lineId"] == "l1"
        # Sans échelle px/m fournie, la vitesse reste en px/s : `null` et non `0`.
        assert vehicle["avgSpeedKmh"] is None

    async def test_le_registre_se_filtre_par_classe(self, client: AsyncClient) -> None:
        job_id = await _finished_job(client)

        cars = (await client.get(f"/api/v1/jobs/{job_id}/vehicles?label=car")).json()

        assert cars["total"] == 1
        assert all(item["label"] == "car" for item in cars["items"])

    async def test_le_registre_d_un_job_inconnu_rend_404(self, client: AsyncClient) -> None:
        """Un 404 explicite plutôt qu'une page vide, qui serait trompeuse."""
        response = await client.get("/api/v1/jobs/inexistant/vehicles")

        assert response.status_code == 404

    async def test_une_taille_de_page_hors_bornes_est_refusee(self, client: AsyncClient) -> None:
        job_id = await _finished_job(client)

        response = await client.get(f"/api/v1/jobs/{job_id}/vehicles?limit=5000")

        assert response.status_code == 422


class TestFranchissements:
    async def test_les_franchissements_sont_chronologiques(self, client: AsyncClient) -> None:
        job_id = await _finished_job(client)

        body = (await client.get(f"/api/v1/jobs/{job_id}/crossings")).json()

        assert body["total"] == 2
        timestamps = [item["timestampMs"] for item in body["items"]]
        assert timestamps == sorted(timestamps)

    async def test_le_filtre_par_sens_fonctionne(self, client: AsyncClient) -> None:
        """Les deux véhicules du scénario traversent en sens opposés."""
        job_id = await _finished_job(client)

        montants = (await client.get(f"/api/v1/jobs/{job_id}/crossings?direction=-1")).json()

        assert montants["total"] == 1
        assert montants["items"][0]["direction"] == -1


class TestExportCsv:
    async def test_le_csv_du_registre_est_ouvrable_dans_excel_francais(
        self, client: AsyncClient
    ) -> None:
        """Les trois détails qui font la différence entre lisible et illisible."""
        job_id = await _finished_job(client)

        response = await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=vehicles")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        assert "carrefour-vehicules.csv" in response.headers["content-disposition"]

        content = response.content.decode("utf-8")
        # 1. BOM UTF-8 : sans lui, Excel massacre les accents.
        assert content.startswith("﻿")
        # 2. Point-virgule : sans lui, tout atterrit dans une seule colonne.
        header = content.lstrip("﻿").splitlines()[0]
        assert header.split(";")[0] == "Identifiant"
        assert "Type" in header
        # 3. Les en-têtes sont en français, comme tout ce qui est destiné à un
        #    lecteur humain.
        assert "Ré-identifications" in header

    async def test_les_nombres_utilisent_la_virgule_decimale(self, client: AsyncClient) -> None:
        """Sinon Excel lit du texte et refuse de faire la moindre somme."""
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=vehicles")
        ).content.decode("utf-8")

        rows = content.lstrip("﻿").splitlines()[1:]
        assert rows
        speeds = [row.split(";")[7] for row in rows]
        assert any("," in speed for speed in speeds), f"aucune virgule décimale : {speeds}"
        assert not any("." in speed for speed in speeds)

    async def test_une_vitesse_inconnue_est_une_case_vide_et_non_un_zero(
        self, client: AsyncClient
    ) -> None:
        """`0` voudrait dire « à l'arrêt ». Sans échelle, la valeur est inconnue."""
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=vehicles")
        ).content.decode("utf-8")

        rows = content.lstrip("﻿").splitlines()[1:]
        kmh_column = [row.split(";")[8] for row in rows]
        assert all(value == "" for value in kmh_column)

    async def test_le_csv_des_franchissements_traduit_le_sens(self, client: AsyncClient) -> None:
        """`+1`/`-1` est le contrat machine ; « A→B » est ce que lit un humain."""
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=crossings")
        ).content.decode("utf-8")

        assert "A→B" in content
        assert "B→A" in content
        # Les classes aussi sont traduites : un CSV français ne dit pas « truck ».
        assert "Camion" in content or "Voiture" in content

    async def test_un_dataset_inconnu_est_refuse(self, client: AsyncClient) -> None:
        job_id = await _finished_job(client)

        response = await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=tout")

        assert response.status_code == 422


class TestSurvieAuRedemarrage:
    async def test_un_job_survit_au_redemarrage_du_service(
        self, client: AsyncClient, settings: Settings, clock: FrozenClock
    ) -> None:
        """LE test qui justifie tout le lot.

        Une **seconde application** est construite sur la même base, comme après
        un redémarrage. Le job doit y être, avec ses agrégats.
        """
        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport
        from httpx import AsyncClient as Client

        from tests.support.engine import FakeEngine
        from traffic_analysis.app_factory import create_app

        job_id = await _finished_job(client)

        restarted = create_app(settings, clock=clock, engine=FakeEngine([]))
        transport = ASGITransport(app=restarted)
        async with (
            LifespanManager(restarted),
            Client(transport=transport, base_url="http://test") as second,
        ):
            response = await second.get(f"/api/v1/jobs/{job_id}")
            vehicles = await second.get(f"/api/v1/jobs/{job_id}/vehicles")

        assert response.status_code == 200
        assert response.json()["status"] == "done"
        assert vehicles.json()["total"] == 2
