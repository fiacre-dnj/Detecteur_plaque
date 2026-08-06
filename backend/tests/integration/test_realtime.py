"""Le WebSocket temps réel : protocole, sécurité, et libération du bail.

Ces tests utilisent `TestClient` de Starlette et non `httpx.AsyncClient` : ce dernier
ne sait pas parler WebSocket. Le client est donc **synchrone**, ce qui convient — le
protocole est séquencé, et un test qui l'exerce pas à pas est plus lisible qu'un test
concurrent.

Quatre propriétés sont vérifiées ici, et chacune correspond à un mode de défaillance
distinct :

1. **l'origine est refusée avant tout** — un WebSocket n'est pas protégé par la
   politique de même origine ;
2. **une seconde session est refusée en 1013**, pas en 1008 : la requête est valide,
   c'est le serveur qui est saturé, et le client doit savoir qu'il peut réessayer ;
3. **`ready` renvoie les dimensions réellement reçues** — le filet contre une
   géométrie non mise à l'échelle, qui compterait 25 % à côté sans aucune erreur ;
4. **le bail du modèle est rendu** à la fermeture, même anormale.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from tests.support.builders import CAR, compose, straight_line, track_path
from tests.support.engine import FakeEngine, FakePlateDetector
from tests.support.websocket import TestClient
from traffic_analysis.app_factory import create_app
from traffic_analysis.features.realtime.api.protocol import (
    CLOSE_POLICY_VIOLATION,
    CLOSE_TRY_AGAIN_LATER,
    MAX_CLOSE_REASON_BYTES,
    truncate_reason,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from traffic_analysis.core.settings import Settings

WS_URL = "/api/v1/realtime"

#: Dimensions du JPEG envoyé par les tests. Volontairement **différentes** de la
#: 1920×1080 du `FakeEngine` : c'est ce qui prouve que le serveur compte dans
#: l'espace de l'image reçue, et non dans celui qu'il aurait pu supposer.
FRAME_WIDTH = 640
FRAME_HEIGHT = 360

LINE = {
    "id": "l1",
    "name": "Voie nord",
    "a": {"x": 0, "y": 200},
    "b": {"x": 640, "y": 200},
}


def _init_payload(**overrides: Any) -> str:  # noqa: ANN401
    request: dict[str, Any] = {"modelId": "yolov8n", "lines": [LINE]}
    request.update(overrides)
    return json.dumps({"type": "init", "request": request})


def _jpeg(width: int = FRAME_WIDTH, height: int = FRAME_HEIGHT) -> bytes:
    """Un vrai JPEG encodé, pour que `cv2.imdecode` réussisse.

    Un contenu factice ne suffirait pas : `decode_jpeg` rend `None` sur un buffer
    illisible, et le test vérifierait alors le chemin d'erreur en croyant vérifier le
    chemin normal.
    """
    import cv2

    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (60, 90, 120)
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return bytes(buffer)


@pytest.fixture
def realtime_frames() -> list[list[Any]]:
    """Un véhicule qui traverse la ligne, pour que le comptage produise un événement."""
    return compose(track_path(1, CAR, straight_line((300.0, 80.0), (300.0, 320.0), steps=10)))


@pytest.fixture
def realtime_app(settings: Settings, realtime_frames: list[list[Any]]) -> FastAPI:
    """Application avec un moteur factice qui rejoue la traversée."""
    return create_app(
        settings,
        engine=FakeEngine(realtime_frames),
        plate_detector=FakePlateDetector(available=False),
    )


class TestOrigine:
    """La vérification qu'aucun middleware CORS ne fait à notre place."""

    def test_une_origine_inconnue_est_refusee_en_1008(self, realtime_app: FastAPI) -> None:
        """Sans cette garde, n'importe quelle page web peut consommer le GPU.

        Le `CORSMiddleware` ne voit **jamais** passer un handshake WebSocket : pas de
        préflight, pas d'en-tête à exiger. La vérification doit donc être explicite.
        """
        with (
            TestClient(realtime_app) as client,
            pytest.raises(WebSocketDisconnect) as caught,
            client.websocket_connect(
                WS_URL, headers={"origin": "http://evil.example"}
            ) as websocket,
        ):
            websocket.receive_text()

        assert caught.value.code == CLOSE_POLICY_VIOLATION

    def test_une_origine_autorisee_passe(self, realtime_app: FastAPI) -> None:
        with (
            TestClient(realtime_app) as client,
            client.websocket_connect(
                WS_URL, headers={"origin": "http://localhost:5173"}
            ) as websocket,
        ):
            websocket.send_text(_init_payload())
            assert websocket.receive_json()["type"] == "ready"

    def test_une_origine_absente_passe_car_ce_n_est_pas_un_navigateur(
        self, realtime_app: FastAPI
    ) -> None:
        """`curl` et les clients natifs n'envoient pas d'`Origin`.

        Ce sont précisément les clients qui ne sont pas soumis au risque : il n'y a pas
        de page tierce, donc pas de confusion d'autorité à exploiter. Les refuser
        casserait tous les outils de diagnostic sans rien protéger de plus.
        """
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            assert websocket.receive_json()["type"] == "ready"

    def test_le_prefixe_ne_suffit_pas_a_autoriser_une_origine(self, realtime_app: FastAPI) -> None:
        """La comparaison est **exacte**, pas par préfixe.

        `http://localhost:5173.evil.com` commence par une origine autorisée : un
        `startswith` l'accepterait.
        """
        with (
            TestClient(realtime_app) as client,
            pytest.raises(WebSocketDisconnect) as caught,
            client.websocket_connect(
                WS_URL, headers={"origin": "http://localhost:5173.evil.com"}
            ) as websocket,
        ):
            websocket.receive_text()

        assert caught.value.code == CLOSE_POLICY_VIOLATION


class TestInit:
    def test_un_init_invalide_ferme_en_1008_avec_sa_raison(self, realtime_app: FastAPI) -> None:
        """Une géométrie vide ne produirait aucun compteur : refusée tôt et clairement."""
        with (
            TestClient(realtime_app) as client,
            pytest.raises(WebSocketDisconnect) as caught,
            client.websocket_connect(WS_URL) as websocket,
        ):
            websocket.send_text(json.dumps({"type": "init", "request": {"modelId": "yolov8n"}}))
            websocket.receive_json()

        assert caught.value.code == CLOSE_POLICY_VIOLATION

    def test_un_modele_inconnu_est_refuse(self, realtime_app: FastAPI) -> None:
        with (
            TestClient(realtime_app) as client,
            pytest.raises(WebSocketDisconnect) as caught,
            client.websocket_connect(WS_URL) as websocket,
        ):
            websocket.send_text(_init_payload(modelId="yolo42x"))
            websocket.receive_json()

        assert caught.value.code == CLOSE_POLICY_VIOLATION

    def test_ready_annonce_le_modele_et_le_device(self, realtime_app: FastAPI) -> None:
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            ready = websocket.receive_json()

        assert ready["type"] == "ready"
        assert ready["modelId"] == "yolov8n"
        assert ready["device"] != ""

    def test_ready_ne_pretend_pas_connaitre_les_dimensions_avant_la_premiere_frame(
        self, realtime_app: FastAPI
    ) -> None:
        """`null` et non une valeur inventée.

        Le serveur ne peut pas connaître les dimensions avant d'avoir reçu une image.
        En inventer serait exactement le mensonge que ce message existe pour empêcher.
        """
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            ready = websocket.receive_json()

        assert ready["frameWidth"] is None
        assert ready["frameHeight"] is None


class TestFrames:
    def test_une_frame_produit_un_frameResult(self, realtime_app: FastAPI) -> None:
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            websocket.receive_json()

            websocket.send_text(json.dumps({"type": "frame", "timestampMs": 0}))
            websocket.send_bytes(_jpeg())
            result = websocket.receive_json()

        assert result["type"] == "frameResult"
        assert result["timestampMs"] == 0
        assert "tracks" in result
        assert "stats" in result

    def test_le_frameResult_rapporte_les_dimensions_REELLEMENT_recues(
        self, realtime_app: FastAPI
    ) -> None:
        """**Le test le plus important du lot.**

        Le client réduit ses frames à ~960 px et doit mettre sa géométrie à la même
        échelle. S'il oublie, une ligne tracée sur du 1280 est appliquée à du 960 :
        comptée 25 % à côté, **sans aucune erreur**. Le serveur dit ce qu'il a reçu ;
        le client compare et refuse s'il y a un écart.

        Le JPEG fait 640×360, différent de la 1920×1080 du `FakeEngine` : le serveur
        doit rapporter ce qu'il a **décodé**, pas ce qu'il aurait pu supposer.
        """
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            websocket.receive_json()
            websocket.send_text(json.dumps({"type": "frame", "timestampMs": 0}))
            websocket.send_bytes(_jpeg())
            result = websocket.receive_json()

        assert result["frameWidth"] == FRAME_WIDTH
        assert result["frameHeight"] == FRAME_HEIGHT

    def test_les_horodatages_du_client_sont_respectes(self, realtime_app: FastAPI) -> None:
        """Le temps de scène vient du client : c'est lui qui sait où il en est.

        Y substituer l'horloge du serveur casserait les débits et les vitesses
        (invariant 1).
        """
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            websocket.receive_json()

            stamps = []
            for timestamp in (0, 40, 80):
                websocket.send_text(json.dumps({"type": "frame", "timestampMs": timestamp}))
                websocket.send_bytes(_jpeg())
                stamps.append(websocket.receive_json()["timestampMs"])

        assert stamps == [0, 40, 80]

    def test_l_index_de_frame_progresse(self, realtime_app: FastAPI) -> None:
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            websocket.receive_json()

            indices = []
            for timestamp in (0, 40):
                websocket.send_text(json.dumps({"type": "frame", "timestampMs": timestamp}))
                websocket.send_bytes(_jpeg())
                indices.append(websocket.receive_json()["frameIndex"])

        assert indices == [0, 1]

    def test_une_image_illisible_est_signalee_SANS_fermer_la_session(
        self, realtime_app: FastAPI
    ) -> None:
        """Un JPEG tronqué par le réseau est un incident **normal** en temps réel.

        Le client en enverra un autre dans 30 ms. Fermer obligerait à tout
        reconstruire — géométrie, bail, session — pour un octet perdu.
        """
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            websocket.receive_json()

            websocket.send_text(json.dumps({"type": "frame", "timestampMs": 0}))
            websocket.send_bytes(b"ceci n'est pas un jpeg")
            error = websocket.receive_json()

            # La session **vit toujours** : la frame suivante est traitée.
            websocket.send_text(json.dumps({"type": "frame", "timestampMs": 40}))
            websocket.send_bytes(_jpeg())
            recovered = websocket.receive_json()

        assert error["type"] == "error"
        assert error["code"] == "undecodable_frame"
        assert recovered["type"] == "frameResult"

    def test_un_entete_de_frame_invalide_est_signale_sans_fermer(
        self, realtime_app: FastAPI
    ) -> None:
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            websocket.receive_json()

            websocket.send_text(json.dumps({"type": "frame", "timestampMs": -5}))
            error = websocket.receive_json()

            websocket.send_text(json.dumps({"type": "frame", "timestampMs": 0}))
            websocket.send_bytes(_jpeg())
            recovered = websocket.receive_json()

        assert error["code"] == "invalid_frame_header"
        assert recovered["type"] == "frameResult"


class TestSessionUnique:
    def test_une_seconde_session_est_refusee_en_1013_et_non_en_1008(
        self, realtime_app: FastAPI
    ) -> None:
        """**1013 et non 1008**, et la distinction est utile au client.

        1008 dit « ta requête est fautive, ne réessaie pas » ; 1013 dit « réessaie
        plus tard ». Ici la requête est parfaitement valide : c'est le serveur qui est
        saturé. Confondre les deux ferait abandonner un client qui devrait patienter.
        """
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as first:
            first.send_text(_init_payload())
            first.receive_json()

            with (
                pytest.raises(WebSocketDisconnect) as caught,
                client.websocket_connect(WS_URL) as second,
            ):
                second.receive_text()

        assert caught.value.code == CLOSE_TRY_AGAIN_LATER

    def test_la_place_est_rendue_apres_fermeture(self, realtime_app: FastAPI) -> None:
        """Sans cette libération, une seule session épuiserait le serveur définitivement."""
        # Deux connexions **successives**, délibérément non fusionnées : c'est la
        # fermeture de la première qui doit rendre la place à la seconde.
        with TestClient(realtime_app) as client:
            with client.websocket_connect(WS_URL) as first:
                first.send_text(_init_payload())
                first.receive_json()

            with client.websocket_connect(WS_URL) as second:
                second.send_text(_init_payload())
                assert second.receive_json()["type"] == "ready"

    def test_le_bail_du_modele_est_rendu_a_la_fermeture(self, realtime_app: FastAPI) -> None:
        """Un bail non rendu immobilise une instance jusqu'au redémarrage.

        Le `FakeStream` enregistre sa fermeture, ce qui rend la vérification directe.
        """
        container = realtime_app.state.container
        with TestClient(realtime_app) as client, client.websocket_connect(WS_URL) as websocket:
            websocket.send_text(_init_payload())
            websocket.receive_json()
            websocket.send_text(json.dumps({"type": "frame", "timestampMs": 0}))
            websocket.send_bytes(_jpeg())
            websocket.receive_json()

        # Aucune session active après la fermeture.
        assert container.realtime_service.active == 0


class TestRaisonDeFermeture:
    def test_une_raison_longue_est_tronquee_pour_tenir_dans_la_trame(self) -> None:
        """La RFC 6455 borne le corps de fermeture à 125 octets, dont 2 pour le code.

        Une raison plus longue fait échouer la **fermeture elle-même** : le client
        reçoit une coupure brutale au lieu de son explication.
        """
        long_reason = "é" * 200
        truncated = truncate_reason(long_reason)

        assert len(truncated.encode("utf-8")) <= MAX_CLOSE_REASON_BYTES

    def test_une_raison_courte_est_intacte(self) -> None:
        assert truncate_reason("Origine non autorisée.") == "Origine non autorisée."

    def test_la_troncature_compte_les_OCTETS_et_non_les_caracteres(self) -> None:
        """Un message français est plein d'accents, qui pèsent deux octets en UTF-8.

        Compter les caractères laisserait passer 123 caractères pour 140 octets, et la
        fermeture échouerait.
        """
        # 100 caractères accentués = 200 octets : au-delà de la limite.
        truncated = truncate_reason("é" * 100)

        assert len(truncated.encode("utf-8")) <= MAX_CLOSE_REASON_BYTES
        assert len(truncated) < 100
