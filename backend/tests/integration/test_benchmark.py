"""Le benchmark à travers HTTP : dépôt, lecture, SSE, dernier run, annulation.

Les tests unitaires prouvent que le **protocole** est juste ; ceux-ci prouvent que
le contrat exposé l'est aussi — que la persistance restitue ce que la mesure a
produit, et que les routes rendent les statuts que le frontend attend.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

# Importée à l'exécution et non sous `TYPE_CHECKING` : une fixture la **construit**.
from tests.support.probe import FakeProbe

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

BENCHMARK_URL = "/api/v1/benchmark"


def _messages(payload: dict[str, Any]) -> str:
    """Concatène les messages de `errors[]` d'un Problem Details de validation.

    Le détail par champ y vit, et non dans `detail` : c'est lui qui dit *lequel*
    des réglages est refusé, ce qu'un message global ne peut pas faire.
    """
    return " | ".join(error["message"] for error in payload.get("errors", ()))


async def _wait_for_done(app: FastAPI, client: AsyncClient, run_id: str) -> dict[str, Any]:
    """Attend **la tâche de fond**, puis relit le run par HTTP.

    Le service est atteint par le conteneur plutôt que sondé par la route : une
    boucle de sondage bornée en nombre d'itérations échoue dès que la machine
    ralentit — sous `--cov`, par exemple — et un test dont le verdict dépend de la
    vitesse de la machine ne prouve rien. La **lecture**, elle, reste HTTP : c'est
    le contrat qu'on vérifie.
    """
    await app.state.container.benchmark_service.wait_for_idle()
    response = await client.get(f"{BENCHMARK_URL}/{run_id}")
    payload: dict[str, Any] = response.json()
    assert payload["status"] in {"done", "error", "cancelled"}
    return payload


class TestDepot:
    async def test_un_depot_est_accepte_en_202_avec_son_identifiant(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n"], "frames": 3})

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["runId"]
        # `Location` pointe vers la ressource créée : c'est ce qui permet au client
        # de suivre le run sans reconstruire l'URL à la main.
        assert response.headers["Location"].endswith(payload["runId"])

    async def test_un_corps_vide_mesure_tout_le_catalogue(self, client: AsyncClient) -> None:
        """Le geste le plus courant ne doit pas exiger de remplir un formulaire."""
        response = await client.post(BENCHMARK_URL)

        assert response.status_code == 202
        run_id = response.json()["runId"]
        detail = await client.get(f"{BENCHMARK_URL}/{run_id}")

        # Les 20 modèles du catalogue.
        assert detail.json()["total"] == 20

    async def test_un_modele_inconnu_est_refuse_en_422_avec_la_liste_des_valides(
        self, client: AsyncClient
    ) -> None:
        """Refuser tôt plutôt qu'au chargement.

        Un identifiant inconnu accepté produirait un run qui échoue au milieu, sans
        que l'utilisateur sache lequel de ses choix est en cause.
        """
        response = await client.post(BENCHMARK_URL, json={"modelIds": ["yolo42x"]})

        assert response.status_code == 422
        # Le détail par champ vit dans `errors[]` : c'est lui qui dit *lequel* des
        # réglages est en cause, ce qu'un `detail` global ne peut pas faire.
        messages = _messages(response.json())
        assert "yolo42x" in messages
        assert "yolov8n" in messages

    async def test_un_doublon_est_refuse_plutot_que_corrige_en_silence(
        self, client: AsyncClient
    ) -> None:
        """Mesurer deux fois le même modèle est presque toujours une faute de frappe.

        La corriger en douce cacherait l'erreur — et produirait deux lignes que la
        contrainte d'unicité en base refuserait de toute façon.
        """
        response = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n", "yolov8n"]})

        assert response.status_code == 422
        assert "doublon" in _messages(response.json())

    async def test_image_source_job_sans_job_id_est_refusee(self, client: AsyncClient) -> None:
        """Refusé au lieu d'un repli sur l'échantillon.

        L'utilisateur croirait mesurer sur sa propre scène et comparerait des
        chiffres qui ne portent pas sur ce qu'il pense.
        """
        response = await client.post(
            BENCHMARK_URL, json={"modelIds": ["yolov8n"], "imageSource": "job"}
        )

        assert response.status_code == 422
        assert "jobId" in _messages(response.json())

    async def test_un_job_inexistant_est_refuse_en_404(self, client: AsyncClient) -> None:
        response = await client.post(
            BENCHMARK_URL,
            json={"modelIds": ["yolov8n"], "imageSource": "job", "jobId": "inexistant"},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "benchmark_job_not_found"

    async def test_un_nombre_de_mesures_hors_bornes_est_refuse(self, client: AsyncClient) -> None:
        response = await client.post(BENCHMARK_URL, json={"frames": 500})

        assert response.status_code == 422


class TestResultat:
    async def test_le_run_complet_porte_ses_lignes_et_son_contexte_materiel(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Un résultat sans son contexte matériel est trompeur.

        40 ms sur GPU et 40 ms sur CPU ne racontent pas la même histoire.
        """
        created = await client.post(
            BENCHMARK_URL, json={"modelIds": ["yolov8n", "yolo11m"], "frames": 5}
        )
        payload = await _wait_for_done(app, client, created.json()["runId"])

        assert payload["status"] == "done"
        assert payload["progress"] == 1.0
        assert payload["device"] == "cpu"
        assert payload["half"] is False
        assert payload["ultralyticsVersion"] == "8.3.0-factice"
        assert len(payload["imageHash"]) == 64
        assert payload["imageSource"] == "sample"
        assert len(payload["entries"]) == 2

    async def test_chaque_ligne_porte_mediane_p95_cadence_et_liberation(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        created = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n"], "frames": 5})
        payload = await _wait_for_done(app, client, created.json()["runId"])
        entry = payload["entries"][0]

        assert entry["modelId"] == "yolov8n"
        # Le palier vient du **catalogue**, jamais du nom de fichier de poids.
        assert entry["tier"] == "nano"
        assert entry["medianMs"] > 0.0
        # Le p95 est au moins la médiane : la série de la sonde porte une valeur
        # haute, et c'est justement ce que le p95 sert à rendre visible.
        assert entry["p95Ms"] >= entry["medianMs"]
        assert entry["fps"] == pytest.approx(1000.0 / entry["medianMs"], rel=0.01)
        assert entry["frames"] == 5
        assert entry["released"] is True
        assert entry["error"] is None

    async def test_les_seuils_de_la_requete_sont_restitues(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        created = await client.post(
            BENCHMARK_URL,
            json={"modelIds": ["yolov8n"], "confidenceThreshold": 0.6, "iouThreshold": 0.3},
        )
        payload = await _wait_for_done(app, client, created.json()["runId"])

        assert payload["confidenceThreshold"] == 0.6
        assert payload["iouThreshold"] == 0.3

    async def test_le_run_survit_a_la_relecture_depuis_la_base(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Les lignes sont écrites au fil du run, pas en bloc à la fin.

        Un redémarrage à la quinzième ligne d'un run de vingt ne doit pas effacer
        les quatorze précédentes.
        """
        created = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n", "yolo11n"]})
        run_id = created.json()["runId"]
        await _wait_for_done(app, client, run_id)

        # Seconde lecture : elle repart de la base, pas d'un cache mémoire.
        again = await client.get(f"{BENCHMARK_URL}/{run_id}")

        assert [entry["modelId"] for entry in again.json()["entries"]] == [
            "yolov8n",
            "yolo11n",
        ]

    async def test_un_run_inconnu_rend_un_404_en_problem_details(self, client: AsyncClient) -> None:
        response = await client.get(f"{BENCHMARK_URL}/inexistant")

        assert response.status_code == 404
        assert response.json()["code"] == "benchmark_not_found"


class TestEchecParModele:
    async def test_un_modele_en_echec_n_interrompt_pas_le_run(
        self, app: FastAPI, client: AsyncClient, benchmark_probe: FakeProbe
    ) -> None:
        """La ligne porte son `error`, le run continue et se termine en `done`."""
        benchmark_probe.make_unloadable("yolov8n")

        created = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n", "yolo11n"]})
        payload = await _wait_for_done(app, client, created.json()["runId"])
        by_id = {entry["modelId"]: entry for entry in payload["entries"]}

        assert payload["status"] == "done"
        assert by_id["yolov8n"]["error"] is not None
        assert by_id["yolo11n"]["error"] is None
        # Le plus rapide ignore la ligne en échec : son `medianMs` vaut 0, et un
        # zéro gagnerait tous les classements.
        assert payload["fastestModelId"] == "yolo11n"


class TestDernierRun:
    async def test_latest_rend_null_quand_aucun_run_n_existe(self, client: AsyncClient) -> None:
        response = await client.get(f"{BENCHMARK_URL}/latest")

        assert response.status_code == 200
        assert response.json() is None

    async def test_latest_rend_le_run_le_plus_recent(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """La route qui évite d'ouvrir la page sur un tableau vide."""
        created = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n"]})
        run_id = created.json()["runId"]
        await _wait_for_done(app, client, run_id)

        response = await client.get(f"{BENCHMARK_URL}/latest")

        assert response.json()["runId"] == run_id

    async def test_latest_n_est_pas_pris_pour_un_identifiant_de_run(
        self, client: AsyncClient
    ) -> None:
        """Garde-fou d'ordre de déclaration des routes.

        FastAPI résout dans l'ordre : si `/{run_id}` était déclarée avant
        `/latest`, la route la plus utilisée de la page rendrait un 404.
        """
        response = await client.get(f"{BENCHMARK_URL}/latest")

        assert response.status_code == 200
        assert response.json() is None


class TestHistorique:
    async def test_l_historique_est_pagine_du_plus_recent_au_plus_ancien(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        first = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n"]})
        await _wait_for_done(app, client, first.json()["runId"])
        second = await client.post(BENCHMARK_URL, json={"modelIds": ["yolo11n"]})
        await _wait_for_done(app, client, second.json()["runId"])

        response = await client.get(BENCHMARK_URL, params={"limit": 10})
        payload = response.json()

        assert payload["total"] == 2
        assert payload["items"][0]["runId"] == second.json()["runId"]


class TestAnnulation:
    async def test_supprimer_un_run_termine_le_retire_de_la_base(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        created = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n"]})
        run_id = created.json()["runId"]
        await _wait_for_done(app, client, run_id)

        deleted = await client.delete(f"{BENCHMARK_URL}/{run_id}")

        assert deleted.status_code == 200
        assert (await client.get(f"{BENCHMARK_URL}/{run_id}")).status_code == 404

    async def test_annuler_un_run_inconnu_rend_un_404(self, client: AsyncClient) -> None:
        response = await client.delete(f"{BENCHMARK_URL}/inexistant")

        assert response.status_code == 404


class TestFluxSse:
    async def test_le_flux_envoie_l_etat_courant_puis_se_ferme_sur_un_run_termine(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """L'état courant part **en premier**.

        Un client qui se (re)connecte ne doit pas attendre la prochaine ligne pour
        savoir où en est la mesure.
        """
        created = await client.post(BENCHMARK_URL, json={"modelIds": ["yolov8n"]})
        run_id = created.json()["runId"]
        await _wait_for_done(app, client, run_id)

        async with client.stream("GET", f"{BENCHMARK_URL}/{run_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # L'en-tête qui empêche un proxy de tamponner le flux.
            assert response.headers["X-Accel-Buffering"] == "no"
            body = "".join([chunk async for chunk in response.aiter_text()])

        assert "event: progress" in body
        assert "event: end" in body
        assert run_id in body

    async def test_le_flux_d_un_run_inconnu_rend_un_404_avant_d_ouvrir_le_corps(
        self, client: AsyncClient
    ) -> None:
        """Un 404 dans un corps SSE déjà commencé serait invisible pour le client."""
        response = await client.get(f"{BENCHMARK_URL}/inexistant/events")

        assert response.status_code == 404


class TestFluxSseSurRunEnCours:
    """Le flux consommé **pendant** la mesure, pas après.

    C'est le cas d'usage réel — vingt modèles sur CPU se comptent en minutes — et
    c'est un chemin de code distinct : sur un run déjà terminé, la route envoie
    l'état puis ferme, sans jamais s'abonner au hub. Seule une mesure encore en
    vol exerce la boucle d'abonnement.
    """

    @pytest.fixture
    def benchmark_probe(self) -> FakeProbe:
        """Sonde **lente**, pour que le run soit encore en cours à l'ouverture du flux.

        Bloquante par inférence, comme une vraie mesure : c'est ce qui rend le
        scénario déterministe au lieu de dépendre d'une course.
        """
        from traffic_analysis.features.models_registry.domain.catalogue import CATALOGUE

        return FakeProbe(
            models={model.id: (model.label, model.tier) for model in CATALOGUE},
            block_s=0.02,
        )

    async def test_le_flux_suit_un_run_en_cours_jusqu_a_son_evenement_final(
        self, client: AsyncClient
    ) -> None:
        """Le flux est ouvert sur un run en vol et lu jusqu'à son `end`.

        Chaque ligne arrive à son rythme, et le dernier événement porte le run
        **complet** : un client qui se connecte en cours de route n'a rien à
        rattraper.
        """
        created = await client.post(
            BENCHMARK_URL, json={"modelIds": ["yolov8n", "yolo11n", "yolo11m"], "frames": 2}
        )
        run_id = created.json()["runId"]

        chunks: list[str] = []
        async with client.stream("GET", f"{BENCHMARK_URL}/{run_id}/events") as response:
            async for chunk in response.aiter_text():
                chunks.append(chunk)
                if "event: end" in "".join(chunks):
                    break
        body = "".join(chunks)

        assert "event: progress" in body
        assert "event: end" in body

        # Le dernier événement porte le run **complet** : un client qui se connecte
        # en cours de route n'a rien à rattraper.
        final = json.loads(body.rsplit("data: ", 1)[1].strip())
        assert final["status"] == "done"
        assert final["progress"] == 1.0
        assert [entry["modelId"] for entry in final["entries"]] == [
            "yolov8n",
            "yolo11n",
            "yolo11m",
        ]
