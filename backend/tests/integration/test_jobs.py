"""Cycle de vie d'un job, du dépôt au résultat — avec un moteur factice.

Aucun de ces tests n'a besoin de GPU, de poids ni d'ultralytics : c'est la
propriété que l'architecture achète, et ces tests la démontrent.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from typing import TYPE_CHECKING, Any

import pytest

from tests.support.builders import CAR, TRUCK, compose, straight_line, track_path

if TYPE_CHECKING:
    from httpx import AsyncClient

    from traffic_analysis.core.settings import Settings

LINE = {"id": "l1", "name": "Voie nord", "a": {"x": 0, "y": 500}, "b": {"x": 1920, "y": 500}}


def _request(**overrides: Any) -> str:  # noqa: ANN401
    payload: dict[str, Any] = {"modelId": "yolov8n", "lines": [LINE]}
    payload.update(overrides)
    return json.dumps(payload)


def _video_bytes(size: int = 2048) -> bytes:
    """Un contenu quelconque : c'est le `FakeEngine` qui décide de sa validité.

    Le fichier n'est jamais décodé dans ces tests — ce serait tester OpenCV, pas
    le cycle de vie d'un job.
    """
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * size


async def _post_job(client: AsyncClient, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    response = await client.post(
        "/api/v1/jobs",
        files={"file": ("carrefour.mp4", _video_bytes(), "video/mp4")},
        data={"request": _request(**overrides)},
    )
    return {
        "status_code": response.status_code,
        "body": response.json(),
        "headers": response.headers,
    }


async def _wait_until_done(
    client: AsyncClient, job_id: str, *, timeout_s: float = 5.0
) -> dict[str, Any]:
    """Attend un statut terminal en sondant, comme le ferait le client réel."""
    async with asyncio.timeout(timeout_s):
        while True:
            response = await client.get(f"/api/v1/jobs/{job_id}")
            body = response.json()
            if body["status"] in {"done", "error", "cancelled"}:
                return body
            await asyncio.sleep(0.01)


@pytest.fixture
def traversing_frames() -> list[list[Any]]:
    """Deux véhicules qui traversent la ligne, en sens opposés."""
    return compose(
        track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=16)),
        track_path(2, TRUCK, straight_line((1200.0, 800.0), (1200.0, 250.0), steps=16)),
    )


class TestDepot:
    async def test_un_depot_valide_rend_202_et_un_identifiant(self, client: AsyncClient) -> None:
        result = await _post_job(client)

        assert result["status_code"] == 202
        assert result["body"]["status"] == "queued"
        assert result["body"]["jobId"]
        # L'en-tête `Location` permet à un client générique de suivre la ressource
        # sans reconstruire l'URL lui-même.
        assert result["headers"]["location"] == f"/api/v1/jobs/{result['body']['jobId']}"

    async def test_un_fichier_vide_est_refuse(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/jobs",
            files={"file": ("vide.mp4", b"", "video/mp4")},
            data={"request": _request()},
        )

        assert response.status_code == 422
        assert "vide" in response.json()["detail"].lower()

    async def test_une_extension_non_video_est_refusee(self, client: AsyncClient) -> None:
        """Le `content-type` annoncé est ignoré : il vient du client."""
        response = await client.post(
            "/api/v1/jobs",
            files={"file": ("archive.zip", _video_bytes(), "video/mp4")},
            data={"request": _request()},
        )

        assert response.status_code == 415
        assert response.json()["code"] == "unsupported_media_type"

    async def test_un_upload_trop_gros_est_refuse_et_ne_laisse_aucun_residu(
        self, client: AsyncClient, settings: Settings
    ) -> None:
        """413 **et** purge : un disque qui se remplit de vidéos rejetées est un
        incident silencieux."""
        oversized = b"\x00" * (settings.max_upload_bytes + 1)

        response = await client.post(
            "/api/v1/jobs",
            files={"file": ("enorme.mp4", oversized, "video/mp4")},
            data={"request": _request()},
        )

        assert response.status_code == 413
        jobs_dir = settings.data_dir / "jobs"
        assert not jobs_dir.exists() or not any(jobs_dir.iterdir())

    async def test_une_configuration_sans_geometrie_est_refusee(self, client: AsyncClient) -> None:
        """Une analyse sans ligne ni zone rendrait un écran de zéros, qui
        ressemble à une panne."""
        response = await client.post(
            "/api/v1/jobs",
            files={"file": ("clip.mp4", _video_bytes(), "video/mp4")},
            data={"request": json.dumps({"modelId": "yolov8n"})},
        )

        assert response.status_code == 422
        assert "ligne" in response.json()["detail"]

    async def test_une_ligne_referencant_une_zone_inconnue_est_refusee(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/jobs",
            files={"file": ("clip.mp4", _video_bytes(), "video/mp4")},
            data={"request": _request(lines=[{**LINE, "zoneId": "fantome"}])},
        )

        assert response.status_code == 422
        assert "fantome" in response.json()["detail"]

    async def test_une_ligne_de_longueur_nulle_est_refusee(self, client: AsyncClient) -> None:
        degenerate = {"id": "l1", "a": {"x": 100, "y": 100}, "b": {"x": 100, "y": 100}}
        response = await client.post(
            "/api/v1/jobs",
            files={"file": ("clip.mp4", _video_bytes(), "video/mp4")},
            data={"request": _request(lines=[degenerate])},
        )

        assert response.status_code == 422
        assert "longueur nulle" in response.json()["detail"]


class TestExecutionEtResultat:
    async def test_un_job_va_jusqu_au_bout_et_produit_un_resultat_conforme(
        self, client: AsyncClient
    ) -> None:
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        final = await _wait_until_done(client, job_id)
        assert final["status"] == "done"
        assert final["progress"] == 1.0

        response = await client.get(f"/api/v1/jobs/{job_id}/result")
        assert response.status_code == 200

        # Le client HTTP décompresse de lui-même : c'est précisément ce que
        # `Content-Encoding: gzip` promet, et le navigateur fera pareil.
        payload = response.json()
        assert payload["jobId"] == job_id
        assert payload["modelId"] == "yolov8n"
        # Les quatre invariants comptables tiennent aussi de l'autre côté du fil.
        stats = payload["stats"]
        assert stats["crossings"] == sum(line["total"] for line in stats["byLine"].values())
        for line in stats["byLine"].values():
            assert (
                line["total"] == line["byDirection"]["positive"] + line["byDirection"]["negative"]
            )
        assert sum(stats["uniqueByClass"].values()) == stats["uniqueVehicles"]

    async def test_le_resultat_est_refuse_tant_que_le_job_n_est_pas_termine(
        self, client: AsyncClient
    ) -> None:
        """409 et non 404 : la ressource existera, elle n'existe pas *encore*.

        Le message doit dire le statut courant, sinon l'utilisateur ne sait pas
        s'il doit attendre ou relancer.
        """
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        response = await client.get(f"/api/v1/jobs/{job_id}/result")

        if response.status_code == 409:
            assert response.json()["code"] == "job_not_finished"
        else:
            # L'analyse factice peut être terminée avant l'appel : c'est légitime.
            assert response.status_code == 200

    async def test_un_job_inconnu_rend_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/jobs/inexistant")

        assert response.status_code == 404
        assert response.json()["code"] == "job_not_found"

    async def test_le_resultat_est_servi_compresse_et_immuable(
        self, client: AsyncClient, settings: Settings
    ) -> None:
        """Un résultat ne change jamais : le cache peut être très long.

        Le fichier est vérifié **sur disque** : c'est là que la compression compte
        vraiment. Une timeline est extrêmement répétitive, et un résultat non
        compressé occuperait environ dix fois plus de place sur le volume.
        """
        created = await _post_job(client)
        job_id = created["body"]["jobId"]
        await _wait_until_done(client, job_id)

        response = await client.get(f"/api/v1/jobs/{job_id}/result")

        assert response.headers["content-encoding"] == "gzip"
        assert "immutable" in response.headers["cache-control"]

        stored = settings.data_dir / "jobs" / job_id / "result.json.gz"
        assert stored.read_bytes()[:2] == b"\x1f\x8b", "le résultat n'est pas gzippé sur disque"
        assert json.loads(gzip.decompress(stored.read_bytes()))["jobId"] == job_id


class TestSse:
    async def test_le_flux_envoie_l_etat_courant_en_premier(self, client: AsyncClient) -> None:
        """Un client qui se connecte ne doit pas attendre la prochaine image.

        Sur une analyse longue, l'attente se compte en secondes et l'interface
        paraît cassée.
        """
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        async with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # Sans cet en-tête, un proxy tamponne et la barre paraît figée.
            assert response.headers["x-accel-buffering"] == "no"

            first = ""
            async for chunk in response.aiter_text():
                first += chunk
                if "\n\n" in first:
                    break

        assert first.startswith("event: progress")
        assert job_id in first

    async def test_le_flux_se_termine_par_un_evenement_end(self, client: AsyncClient) -> None:
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        received = ""
        async with (
            asyncio.timeout(5.0),
            client.stream("GET", f"/api/v1/jobs/{job_id}/events") as response,
        ):
            async for chunk in response.aiter_text():
                received += chunk
                if "event: end" in received:
                    break

        assert "event: end" in received
        terminal = received.split("event: end\ndata: ")[-1].split("\n\n")[0]
        assert json.loads(terminal)["status"] in {"done", "cancelled", "error"}

    async def test_un_job_deja_termine_rend_progress_puis_end_et_ferme(
        self, client: AsyncClient
    ) -> None:
        """Pas de connexion laissée ouverte sur un job qui n'émettra plus rien."""
        created = await _post_job(client)
        job_id = created["body"]["jobId"]
        await _wait_until_done(client, job_id)

        async with asyncio.timeout(5.0):
            response = await client.get(f"/api/v1/jobs/{job_id}/events")

        body = response.text
        assert body.count("event: progress") == 1
        assert body.count("event: end") == 1

    async def test_le_flux_d_un_job_inconnu_rend_404_avant_d_ouvrir(
        self, client: AsyncClient
    ) -> None:
        """Un 404 dans un corps SSE déjà commencé serait invisible pour le client."""
        response = await client.get("/api/v1/jobs/inexistant/events")

        assert response.status_code == 404


class TestSuspensionHttp:
    """Suspendre et reprendre depuis l'API — y compris les refus.

    Le moteur est ralenti pour que « en cours » dure assez longtemps pour être
    observé : avec le moteur nominal, l'analyse se termine avant la requête.
    """

    @pytest.fixture
    def fake_engine(self, traversing_frames: list[list[Any]]) -> Any:  # noqa: ANN401
        import time

        from tests.support.engine import FakeEngine

        class SlowEngine(FakeEngine):
            def iter_video(self, video_path: Any, spec: Any) -> Any:  # noqa: ANN401
                for frame in super().iter_video(video_path, spec):
                    time.sleep(0.05)
                    yield frame

        return SlowEngine(traversing_frames)

    async def test_le_cycle_suspendre_reprendre_passe_par_l_api(self, client: AsyncClient) -> None:
        created = await _post_job(client)
        job_id = created["body"]["jobId"]
        async with asyncio.timeout(5.0):
            while (await client.get(f"/api/v1/jobs/{job_id}")).json()["status"] != "running":
                await asyncio.sleep(0.01)

        paused = await client.post(f"/api/v1/jobs/{job_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"

        # Suspendre deux fois de suite est refusé, avec la cause dans le code :
        # le client peut distinguer « déjà suspendu » de « déjà terminé ».
        again = await client.post(f"/api/v1/jobs/{job_id}/pause")
        assert again.status_code == 409
        assert again.json()["code"] == "job_not_running"

        resumed = await client.post(f"/api/v1/jobs/{job_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "running"

        assert (await _wait_until_done(client, job_id))["status"] == "done"

    async def test_reprendre_une_analyse_qui_tourne_est_refuse(self, client: AsyncClient) -> None:
        created = await _post_job(client)
        job_id = created["body"]["jobId"]
        async with asyncio.timeout(5.0):
            while (await client.get(f"/api/v1/jobs/{job_id}")).json()["status"] != "running":
                await asyncio.sleep(0.01)

        response = await client.post(f"/api/v1/jobs/{job_id}/resume")

        assert response.status_code == 409
        assert response.json()["code"] == "job_not_paused"
        await client.delete(f"/api/v1/jobs/{job_id}")
        await _wait_until_done(client, job_id)

    async def test_suspendre_un_job_inconnu_rend_404(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/jobs/inexistant/pause")

        assert response.status_code == 404


class TestApercuSse:
    """L'aperçu tel qu'il arrive réellement au navigateur.

    Le moteur est ralenti à dessein : avec le moteur factice nominal, l'analyse
    se termine avant même que le client ait ouvert le flux, et le test ne
    vérifierait plus que le chemin « job déjà terminé ».
    """

    @pytest.fixture
    def fake_engine(self, traversing_frames: list[list[Any]]) -> Any:  # noqa: ANN401
        import time

        from tests.support.engine import FakeEngine

        class SlowEngine(FakeEngine):
            def iter_video(self, video_path: Any, spec: Any) -> Any:  # noqa: ANN401
                for frame in super().iter_video(video_path, spec):
                    time.sleep(0.02)
                    yield frame

        return SlowEngine(traversing_frames)

    async def test_le_flux_porte_des_apercus_dessinables(self, client: AsyncClient) -> None:
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        received = ""
        async with (
            asyncio.timeout(10.0),
            client.stream("GET", f"/api/v1/jobs/{job_id}/events") as response,
        ):
            async for chunk in response.aiter_text():
                received += chunk
                if "event: end" in received:
                    break

        assert "event: preview" in received
        apercu = json.loads(received.split("event: preview\ndata: ")[1].split("\n\n")[0])
        assert apercu["jobId"] == job_id
        # Les dimensions sondées voyagent avec l'aperçu : c'est ce qui permet au
        # client de refuser de dessiner une géométrie mal ancrée plutôt que
        # d'afficher des boîtes décalées que rien n'expliquerait.
        assert (apercu["frameWidth"], apercu["frameHeight"]) == (1920, 1080)
        # La forme d'une piste est **exactement** celle du temps réel et de la
        # timeline : un seul chemin de rendu côté navigateur.
        assert {"trackId", "globalId", "box", "counted", "identityLabel"} <= set(
            apercu["tracks"][0]
        )
        assert "uniqueVehicles" in apercu["stats"]


class TestAnnulationEtHistorique:
    async def test_supprimer_un_job_termine_purge_ses_artefacts(
        self, client: AsyncClient, settings: Settings
    ) -> None:
        created = await _post_job(client)
        job_id = created["body"]["jobId"]
        await _wait_until_done(client, job_id)
        assert (settings.data_dir / "jobs" / job_id).exists()

        response = await client.delete(f"/api/v1/jobs/{job_id}")

        assert response.status_code == 200
        assert not (settings.data_dir / "jobs" / job_id).exists()
        assert (await client.get(f"/api/v1/jobs/{job_id}")).status_code == 404

    async def test_l_historique_est_pagine_et_trie_du_plus_recent(
        self, client: AsyncClient
    ) -> None:
        ids = [(await _post_job(client))["body"]["jobId"] for _ in range(3)]
        for job_id in ids:
            await _wait_until_done(client, job_id)

        response = await client.get("/api/v1/jobs", params={"limit": 2})

        body = response.json()
        assert body["total"] == 3
        assert body["limit"] == 2
        assert len(body["items"]) == 2

    async def test_l_historique_se_filtre_par_statut(self, client: AsyncClient) -> None:
        job_id = (await _post_job(client))["body"]["jobId"]
        await _wait_until_done(client, job_id)

        done = await client.get("/api/v1/jobs", params={"status": "done"})
        cancelled = await client.get("/api/v1/jobs", params={"status": "cancelled"})

        assert done.json()["total"] == 1
        assert cancelled.json()["total"] == 0

    async def test_un_statut_de_filtre_invalide_est_refuse(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/jobs", params={"status": "en-cours-peut-etre"})

        assert response.status_code == 422


class TestConfigurationDUnJob:
    """`GET /jobs/{id}/config` — ce qui rend « ouvrir » et « relancer » possibles.

    Sans cette route, l'historique ne pourrait ni recharger la géométrie d'une
    analyse dans le studio, ni préremplir une relance : l'utilisateur devrait
    retracer ses lignes de mémoire, et les chiffres du résultat ne correspondraient
    à aucun tracé visible.
    """

    async def test_la_configuration_est_rendue_telle_qu_elle_a_ete_recue(
        self, client: AsyncClient
    ) -> None:
        created = await _post_job(client, confidenceThreshold=0.6, minHits=4)
        job_id = created["body"]["jobId"]

        response = await client.get(f"/api/v1/jobs/{job_id}/config")
        config = response.json()["configJson"]

        assert response.status_code == 200
        assert config["modelId"] == "yolov8n"
        assert config["confidenceThreshold"] == 0.6
        assert config["minHits"] == 4

    async def test_la_geometrie_est_relisible_pour_recharger_le_studio(
        self, client: AsyncClient
    ) -> None:
        """La géométrie **exacte**, sinon les chiffres relus décriraient un autre tracé."""
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        lines = (await client.get(f"/api/v1/jobs/{job_id}/config")).json()["configJson"]["lines"]

        assert len(lines) == 1
        assert lines[0]["id"] == "l1"
        assert lines[0]["a"] == {"x": 0.0, "y": 500.0}
        assert lines[0]["b"] == {"x": 1920.0, "y": 500.0}

    async def test_la_route_porte_aussi_l_etat_du_job(self, client: AsyncClient) -> None:
        """Elle étend `JobSchema` : un seul appel suffit à l'historique."""
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        body = (await client.get(f"/api/v1/jobs/{job_id}/config")).json()

        assert body["jobId"] == job_id
        assert body["modelId"] == "yolov8n"
        assert body["fileName"] == "carrefour.mp4"

    async def test_la_route_de_sondage_ne_porte_PAS_la_configuration(
        self, client: AsyncClient
    ) -> None:
        """`GET /jobs/{id}` est sondée toutes les 3 s pendant l'analyse.

        Y joindre la géométrie complète la ferait voyager des centaines de fois
        pour une valeur qui ne change jamais. C'est la raison d'être de la route
        séparée, et ce test empêche de « simplifier » en fusionnant les deux.
        """
        created = await _post_job(client)
        job_id = created["body"]["jobId"]

        body = (await client.get(f"/api/v1/jobs/{job_id}")).json()

        assert "configJson" not in body

    async def test_un_job_inconnu_rend_un_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/jobs/inexistant/config")

        assert response.status_code == 404
        assert response.json()["code"] == "job_not_found"
