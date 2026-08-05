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
from httpx import ASGITransport, AsyncClient

from traffic_analysis.app_factory import create_app
from traffic_analysis.core.clock import FrozenClock
from traffic_analysis.core.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime
    from pathlib import Path

    from fastapi import FastAPI

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
def app(settings: Settings, clock: FrozenClock) -> FastAPI:
    return create_app(settings, clock=clock)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client HTTP branché sur l'application en mémoire.

    `ASGITransport` court-circuite le réseau : pas de port à réserver, donc pas
    de test qui échoue parce qu'un autre test tourne en parallèle.

    Les exceptions non gérées **remontent** au test (comportement par défaut de
    `ASGITransport`). C'est volontaire : un bug imprévu doit apparaître sous forme
    de trace exploitable, pas d'un 500 opaque à déboguer à l'aveugle. Le test qui
    vérifie *la réponse* 500 utilise `client_like_production`.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def client_like_production(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client qui se comporte comme un vrai serveur devant une exception.

    Uvicorn ne propage pas une exception à l'appelant : il laisse le gestionnaire
    produire un 500. C'est le seul moyen de vérifier ce que le client **reçoit**
    réellement — et donc qu'aucun détail interne n'y fuit.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
