"""Registre, franchissements et export CSV, à travers HTTP.

Ces routes existent pour que l'utilisateur puisse **vérifier** un total plutôt que
le croire. Le CSV en est l'aboutissement : il doit s'ouvrir directement dans un
Excel français, sans réencodage ni assistant d'importation.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

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

    async def test_le_registre_expose_le_texte_de_plaque(self, client: AsyncClient) -> None:
        """Les clés doivent être là même quand la lecture n'a pas tourné.

        Le client a une branche par **valeur**, pas une branche par présence de clé :
        une clé absente et une clé nulle ne doivent pas se ressembler côté serveur.
        """
        job_id = await _finished_job(client)

        vehicle = (await client.get(f"/api/v1/jobs/{job_id}/vehicles")).json()["items"][0]

        assert vehicle["plateText"] is None
        assert vehicle["plateTextScore"] is None

    async def test_la_recherche_par_plaque_est_acceptee_et_ne_trouve_rien(
        self, client: AsyncClient
    ) -> None:
        """Le scénario n'active pas l'OCR : la route répond, sans résultat.

        Ce qui est vérifié ici est le **câblage** du paramètre jusqu'au dépôt — la
        sémantique du filtre, elle, est couverte au niveau du dépôt.
        """
        job_id = await _finished_job(client)

        response = await client.get(f"/api/v1/jobs/{job_id}/vehicles?plate_text=AB123")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_une_recherche_de_plaque_trop_longue_est_refusee(
        self, client: AsyncClient
    ) -> None:
        job_id = await _finished_job(client)

        response = await client.get(f"/api/v1/jobs/{job_id}/vehicles?plate_text={'A' * 20}")

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
        assert "Franchissements" in header

    async def test_les_nombres_utilisent_la_virgule_decimale(self, client: AsyncClient) -> None:
        """Sinon Excel lit du texte et refuse de faire la moindre somme."""
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=vehicles")
        ).content.decode("utf-8")

        rows = content.lstrip("﻿").splitlines()[1:]
        assert rows
        # Colonne « Vu de (s) » : des secondes de scène, donc décimales.
        seconds = [row.split(";")[2] for row in rows]
        assert any("," in value for value in seconds), f"aucune virgule décimale : {seconds}"
        assert not any("." in value for value in seconds)

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

    @pytest.mark.parametrize("dataset", ["vehicles", "crossings"])
    async def test_chaque_ligne_a_autant_de_colonnes_que_l_en_tete(
        self, client: AsyncClient, dataset: str
    ) -> None:
        """Le bug classique de ce module, et **il ne lève rien**.

        Ajouter une colonne à l'en-tête sans l'ajouter aux lignes — ou l'inverse —
        décale tout le reste du tableau, et cela ne se voit que dans Excel, une fois
        le fichier transmis à quelqu'un d'autre.
        """
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset={dataset}")
        ).content.decode("utf-8")

        lines = content.lstrip("﻿").splitlines()
        expected = len(lines[0].split(";"))
        assert len(lines) > 1, "aucune ligne de données à vérifier"
        for index, row in enumerate(lines[1:], start=2):
            assert len(row.split(";")) == expected, f"ligne {index} décalée : {row}"

    async def test_les_colonnes_de_plaque_sont_annoncees_par_l_en_tete(
        self, client: AsyncClient
    ) -> None:
        """Le texte lu et sa confiance, voisins du score de détection."""
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=vehicles")
        ).content.decode("utf-8")

        header = content.lstrip("﻿").splitlines()[0].split(";")
        assert header.index("Plaque") == header.index("Confiance lecture") - 1
        assert header.index("Confiance lecture") == header.index("Score de plaque") - 1

    async def test_une_plaque_absente_est_une_case_vide_et_non_le_mot_none(
        self, client: AsyncClient
    ) -> None:
        """Une case vide est triable dans un tableur ; « None » est à nettoyer.

        Le scénario de test n'active pas la lecture de plaques, donc la colonne doit
        être entièrement vide — et surtout pas porter la représentation Python de
        `None`, qui est le défaut silencieux d'un `str()` mal placé.
        """
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=vehicles")
        ).content.decode("utf-8")

        lines = content.lstrip("﻿").splitlines()
        column = lines[0].split(";").index("Plaque")
        values = [row.split(";")[column] for row in lines[1:]]
        assert values
        assert all(value == "" for value in values), values

    async def test_le_csv_des_franchissements_porte_aussi_la_plaque(
        self, client: AsyncClient
    ) -> None:
        job_id = await _finished_job(client)

        content = (
            await client.get(f"/api/v1/jobs/{job_id}/export.csv?dataset=crossings")
        ).content.decode("utf-8")

        header = content.lstrip("﻿").splitlines()[0].split(";")
        assert header[-2:] == ["Plaque", "Confiance lecture"]


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


class TestDeuxExportsDeuxMetiers:
    """L'écart entre l'export de l'API et celui du bouton du registre.

    Deux fichiers CSV portent le même nom de métier et n'ont pas les mêmes
    colonnes. Ce n'est pas un doublon à supprimer — `prompt/05` §266 impose la
    route, et le bouton ne peut pas s'en servir — mais un écart qui doit rester
    **écrit**, sinon il se lit comme un oubli et quelqu'un « corrigera » le mauvais
    côté.

    La différence est structurelle : `job_vehicles` n'a aucune colonne
    `rematch_*` ni `match_score`, ces valeurs ne vivant que dans le
    `result.json.gz`. Et le serveur ne lit jamais les rôles de sens (ADR 0016,
    ADR 0021), donc il ne peut pas nommer un sens autrement que `A→B`.
    """

    def test_l_export_de_l_api_ne_pretend_pas_porter_la_re_detection(self) -> None:
        """Le jour où une migration ajoutera ces colonnes, ce test tombera — et
        c'est précisément le moment où il faudra revoir les deux côtés."""
        from traffic_analysis.features.jobs.application.csv_export import (
            CROSSING_HEADERS,
            VEHICLE_HEADERS,
        )

        assert VEHICLE_HEADERS == (
            "Identifiant",
            "Type",
            "Vu de (s)",
            "Vu jusqu'à (s)",
            "Lignes franchies",
            "Zones visitées",
            "Franchissements",
            "Plaque",
            "Confiance lecture",
            "Score de plaque",
        )
        assert not any("Déjà vu" in header for header in VEHICLE_HEADERS)
        assert "Sens" in CROSSING_HEADERS

    def test_le_client_porte_bien_les_colonnes_que_l_api_ne_peut_pas_porter(self) -> None:
        """Verrouillé **depuis le backend**, en nommant le fichier client.

        Même procédé que `MIN_PLATE_CROP_SIDE_PX` et que la marge de recadrage de
        la ReID : une constante qui vit des deux côtés de la frontière de langage
        n'a pas de compilateur commun, donc c'est un test qui tient les deux bouts.
        """
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / (
            "../frontend/src/features/vehicle-registry/model/exportCsv.ts"
        )
        contenu = source.resolve().read_text(encoding="utf-8")

        # Ce que le bouton porte et que l'API ne peut pas porter.
        assert '"Déjà vu (véhicule)"' in contenu
        assert '"Déjà vu (similarité)"' in contenu
        # Et la route est nommée correctement. Pas d'assertion négative sur
        # `vehicles.csv` : la docstring la cite justement pour dire qu'elle n'a
        # jamais existé, et interdire le mot interdirait de l'expliquer.
        assert "export.csv?dataset=vehicles|crossings" in contenu
