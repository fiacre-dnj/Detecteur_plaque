"""Fixtures d'application, de client et de configuration.

**Ce fichier ne contient que des fixtures.** Les helpers vivent dans
`tests/support/`, importés en `from tests.support.… import …`.

La raison est concrète : la roue `ultralytics` embarque son propre paquet
`tests`. Un `from tests.conftest import quelque_chose` peut donc résoudre vers
*ses* fichiers au lieu des nôtres, et le message d'erreur ne dit rien d'utile
(piège 50 de prompt/13).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from tests.support.builders import CAR, TRUCK, compose, straight_line, track_path
from tests.support.engine import FakeEngine, FakePlateDetector
from traffic_analysis.app_factory import create_app
from traffic_analysis.core.clock import FrozenClock
from traffic_analysis.core.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime
    from pathlib import Path

    from fastapi import FastAPI

    from traffic_analysis.features.counting.application.dto import TrackObservation

# Instant de référence des tests. Fixe, pour qu'un test qui compare des dates
# soit reproductible en janvier comme en juillet.
FROZEN_NOW_ISO = "2026-08-05T10:12:00+00:00"


@pytest.fixture
def frozen_now() -> datetime:
    from datetime import datetime as dt

    return dt.fromisoformat(FROZEN_NOW_ISO)


@pytest.fixture
def clock(frozen_now: datetime) -> FrozenClock:
    return FrozenClock(frozen_now)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Configuration de test, isolée sur disque.

    `warmup=False` est obligatoire : un préchauffage chargerait un vrai modèle,
    donc téléchargerait des dizaines de mégaoctets depuis la CI.

    `_env_file=None` empêche pydantic-settings de lire un `.env` présent sur la
    machine du développeur : sinon un test passe chez l'un et échoue chez l'autre.
    """
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        data_dir=tmp_path / "data",
        weights_dir=tmp_path / "weights",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'traffic.db'}",
        warmup=False,
        docs_enabled=True,
        max_upload_mb=5,
        log_format="console",
    )


@pytest.fixture
def traversing_frames() -> list[list[TrackObservation]]:
    """Scénario par défaut du moteur factice : deux véhicules qui traversent.

    Il y a un franchissement dans chaque sens, donc les tests d'intégration
    exercent un résultat non trivial sans avoir à décrire une scène eux-mêmes.
    """
    return compose(
        track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=16)),
        track_path(2, TRUCK, straight_line((1200.0, 800.0), (1200.0, 250.0), steps=16)),
    )


@pytest.fixture
def fake_engine(traversing_frames: list[list[TrackObservation]]) -> FakeEngine:
    return FakeEngine(traversing_frames)


@pytest.fixture
def plate_detector() -> FakePlateDetector:
    return FakePlateDetector()


@pytest.fixture
def app(
    settings: Settings,
    clock: FrozenClock,
    fake_engine: FakeEngine,
    plate_detector: FakePlateDetector,
) -> FastAPI:
    return create_app(
        settings,
        clock=clock,
        engine=fake_engine,
        plate_detector=plate_detector,
    )


async def _client(app: FastAPI, *, raise_app_exceptions: bool) -> AsyncIterator[AsyncClient]:
    """Client HTTP avec **le `lifespan` réellement exécuté**.

    `ASGITransport` ne déclenche pas le `lifespan` de lui-même. Sans lui, le
    `JobManager` n'a ni sémaphore ni boucle attachée, et tout test de job échoue
    sur une erreur qui ne dit rien de la cause.
    """
    from httpx import ASGITransport as Transport

    transport = Transport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with (
        LifespanManager(app),
        AsyncClient(transport=transport, base_url="http://test") as http_client,
    ):
        yield http_client


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client HTTP branché sur l'application en mémoire.

    `ASGITransport` court-circuite le réseau : pas de port à réserver, donc pas
    de test qui échoue parce qu'un autre test tourne en parallèle.

    Les exceptions non gérées **remontent** au test. C'est volontaire : un bug
    imprévu doit apparaître sous forme de trace exploitable, pas d'un 500 opaque à
    déboguer à l'aveugle. Le test qui vérifie *la réponse* 500 utilise
    `client_like_production`.
    """
    async for http_client in _client(app, raise_app_exceptions=True):
        yield http_client


@pytest.fixture
async def client_like_production(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client qui se comporte comme un vrai serveur devant une exception.

    Uvicorn ne propage pas une exception à l'appelant : il laisse le gestionnaire
    produire un 500. C'est le seul moyen de vérifier ce que le client **reçoit**
    réellement — et donc qu'aucun détail interne n'y fuit.
    """
    async for http_client in _client(app, raise_app_exceptions=False):
        yield http_client
