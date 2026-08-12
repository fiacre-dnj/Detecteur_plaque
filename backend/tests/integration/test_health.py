"""Les trois sondes de santé, et ce qu'elles promettent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from traffic_analysis import __version__
from traffic_analysis.core.middleware.request_id import HEADER_NAME

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

    from traffic_analysis.core.clock import FrozenClock
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


async def test_health_expose_le_diagnostic_complet(client: AsyncClient) -> None:
    """Tout ce que le badge d'état du frontend affiche en permanence.

    Chaque champ doit être calculable **sans charger de modèle** : le badge est
    interrogé sur tous les écrans, et le consulter ne doit pas coûter plus cher
    que d'utiliser le service.
    """
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "test"
    # La fixture fixe le device : ce test vérifie que le badge rend un diagnostic
    # cohérent, pas ce que la machine de test a sous le capot. Les cinq raisons
    # possibles sont couvertes en unitaire (`TestDiagnosticMateriel`).
    assert body["device"] == "cpu"
    assert body["deviceReason"] == "configuré explicitement"
    assert body["gpuName"] is None
    assert body["half"] is False
    assert body["ultralyticsVersion"]
    # Aucun modèle chargé tant qu'aucune analyse n'a tourné.
    assert body["loadedModels"] == []
    assert body["maxLoadedModels"] >= 1
    # La fixture injecte un détecteur et un lecteur de plaques factices disponibles.
    assert body["plateAvailable"] is True
    assert body["plateOcrAvailable"] is True
    # `null` et non `false` : la fixture pose `warmup=False`, donc l'auto-test n'a pas
    # tourné. Les confondre ferait passer tout démarrage sans préchauffage — la CI,
    # les tests, un conteneur réglé pour booter vite — pour une ANPR en panne.
    assert body["plateLoadable"] is None
    assert body["defaultModelId"] == "yolov8n"


async def test_l_anpr_absente_est_signalee_sans_empecher_le_service(
    settings: Settings, clock: FrozenClock
) -> None:
    """L'absence du modèle de plaques ne casse pas le démarrage.

    C'est une exigence explicite : le service démarre, `/health` le dit, et
    l'interface désactive l'option. Refuser de booter pour un modèle optionnel
    serait disproportionné.
    """
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    from tests.support.engine import FakeEngine, FakePlateDetector
    from traffic_analysis.app_factory import create_app

    app = create_app(
        settings,
        clock=clock,
        engine=FakeEngine([]),
        plate_detector=FakePlateDetector(available=False),
    )
    transport = ASGITransport(app=app)
    async with (
        LifespanManager(app),
        Client(transport=transport, base_url="http://test") as client,
    ):
        body = (await client.get("/api/v1/health")).json()

    assert body["status"] == "ok"
    assert body["plateAvailable"] is False


async def test_la_lecture_absente_est_signalee_sans_desactiver_la_detection(
    settings: Settings, clock: FrozenClock
) -> None:
    """Détecteur présent, lecteur absent — l'état de tout déploiement neuf.

    Les deux drapeaux sont **indépendants**, et c'est tout l'enjeu : si l'absence du
    modèle de lecture faisait retomber `plateAvailable` à faux, un serveur sans OCR
    perdrait aussi les boîtes qu'il sait produire. L'interface s'appuie sur cette
    distinction pour proposer la détection sans promettre la lecture.
    """
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    from tests.support.engine import FakeEngine, FakePlateDetector, FakePlateReader
    from traffic_analysis.app_factory import create_app

    app = create_app(
        settings,
        clock=clock,
        engine=FakeEngine([]),
        plate_detector=FakePlateDetector(),
        plate_reader=FakePlateReader(available=False),
    )
    transport = ASGITransport(app=app)
    async with (
        LifespanManager(app),
        Client(transport=transport, base_url="http://test") as client,
    ):
        health = (await client.get("/api/v1/health")).json()
        models = (await client.get("/api/v1/models")).json()

    assert health["status"] == "ok"
    assert health["plateAvailable"] is True
    assert health["plateOcrAvailable"] is False
    # Le catalogue porte la même distinction : l'interface lit l'un ou l'autre.
    assert models["plateAvailable"] is True
    assert models["plateOcrAvailable"] is False


class TestAutoTestDuDetecteur:
    """`plateAvailable` dit « le fichier est là », `plateLoadable` « il marche ».

    La distinction existe parce que la confondre a coûté un projet entier ici :
    `available` n'est qu'un `is_file()` — délibérément, l'interface interroge
    `/health` en permanence — donc un poids corrompu, tronqué, ou dont le suffixe
    contredit le format rend `plateAvailable: true` puis échoue au chargement. Zéro
    plaque à chaque image, aucune exception, un drapeau vert.

    L'auto-test est appelé explicitement ici plutôt qu'attendu du préchauffage de
    fond : un test dont le verdict dépend de l'ordonnancement d'une tâche ne prouve
    rien, et borner l'attente par un nombre d'itérations est interdit dans ce dépôt.
    Ce que ces tests couvrent est le chaînon service → route ; que le démarrage
    l'appelle est vérifié par `_warmup` lui-même.
    """

    async def test_un_detecteur_sain_est_signale_chargeable(
        self, settings: Settings, clock: FrozenClock
    ) -> None:
        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport
        from httpx import AsyncClient as Client

        from tests.support.engine import FakeEngine, FakePlateDetector
        from traffic_analysis.app_factory import create_app

        detector = FakePlateDetector()
        app = create_app(settings, clock=clock, engine=FakeEngine([]), plate_detector=detector)
        transport = ASGITransport(app=app)
        async with (
            LifespanManager(app),
            Client(transport=transport, base_url="http://test") as client,
        ):
            await app.state.container.model_service.probe_plates()
            body = (await client.get("/api/v1/health")).json()

        assert body["plateAvailable"] is True
        assert body["plateLoadable"] is True

    async def test_des_poids_presents_mais_illisibles_sont_nommes(
        self, settings: Settings, clock: FrozenClock
    ) -> None:
        """**L'état que ce champ existe pour rendre visible.**

        Les poids sont là — `plateAvailable` reste vrai, et c'est correct : le fichier
        existe. Mais ils ne se chargent pas. Sans `plateLoadable`, cet état est
        indistinguable d'un fonctionnement normal depuis l'extérieur.
        """
        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport
        from httpx import AsyncClient as Client

        from tests.support.engine import FakeEngine, FakePlateDetector
        from traffic_analysis.app_factory import create_app

        detector = FakePlateDetector(available=True, loadable=False)
        app = create_app(settings, clock=clock, engine=FakeEngine([]), plate_detector=detector)
        transport = ASGITransport(app=app)
        async with (
            LifespanManager(app),
            Client(transport=transport, base_url="http://test") as client,
        ):
            await app.state.container.model_service.probe_plates()
            body = (await client.get("/api/v1/health")).json()

        assert body["plateAvailable"] is True
        assert body["plateLoadable"] is False

    async def test_un_detecteur_absent_ne_se_teste_pas(
        self, settings: Settings, clock: FrozenClock
    ) -> None:
        """Absent ⇒ `null`, jamais `false`, et **aucune inférence tentée**.

        Un déploiement neuf n'a pas de modèle de plaques. Signaler « auto-test en
        échec » y serait un faux positif, et c'est exactement le bruit qui apprend à
        un opérateur à ignorer le champ.
        """
        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport
        from httpx import AsyncClient as Client

        from tests.support.engine import FakeEngine, FakePlateDetector
        from traffic_analysis.app_factory import create_app

        detector = FakePlateDetector(available=False)
        app = create_app(settings, clock=clock, engine=FakeEngine([]), plate_detector=detector)
        transport = ASGITransport(app=app)
        async with (
            LifespanManager(app),
            Client(transport=transport, base_url="http://test") as client,
        ):
            await app.state.container.model_service.probe_plates()
            body = (await client.get("/api/v1/health")).json()

        assert body["plateAvailable"] is False
        assert body["plateLoadable"] is None
        assert detector.probes == 0


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
