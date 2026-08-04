"""Le `request_id` doit apparaître dans les journaux, pas seulement dans la réponse.

C'est tout l'intérêt du mécanisme : l'utilisateur cite l'identifiant affiché par
l'interface, et une seule recherche dans les journaux remonte la chaîne complète.
Si l'identifiant n'est que dans l'en-tête HTTP, il ne sert à rien.

Ces tests exercent le chemin réel — middleware, `ContextVar`, processeur
structlog, rendu — plutôt que d'inspecter la configuration : c'est le résultat qui
compte, et la configuration a déjà changé une fois sans que le résultat suive.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import TYPE_CHECKING

import pytest

from traffic_analysis.core.logging import configure_logging, get_logger
from traffic_analysis.core.middleware.request_id import HEADER_NAME
from traffic_analysis.core.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from httpx import AsyncClient


def _settings(log_format: str) -> Settings:
    return Settings(_env_file=None, env="test", log_format=log_format)  # type: ignore[call-arg,arg-type]


@pytest.fixture
def console_log() -> Iterator[StringIO]:
    """Journaux rendus en console, dirigés vers un tampon lisible par le test."""
    buffer = StringIO()
    configure_logging(_settings("console"), stream=buffer)
    yield buffer
    # Rendre la journalisation à son état normal : sans cela, les tests suivants
    # écriraient dans un tampon détruit.
    configure_logging(_settings("console"))


@pytest.fixture
def json_log() -> Iterator[StringIO]:
    """Journaux rendus en JSON — ce que voit un collecteur en production."""
    buffer = StringIO()
    configure_logging(_settings("json"), stream=buffer)
    yield buffer
    configure_logging(_settings("console"))


def _records(buffer: StringIO, containing: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in buffer.getvalue().splitlines()
        if containing in line and line.startswith("{")
    ]


async def test_un_journal_emis_pendant_la_requete_porte_son_request_id(
    app: FastAPI, client: AsyncClient, console_log: StringIO
) -> None:
    logger = get_logger("test.correlation")

    @app.get("/api/v1/_test/log")
    async def emit_log() -> dict[str, str]:
        logger.info("évènement métier")
        return {"ok": "1"}

    response = await client.get("/api/v1/_test/log", headers={HEADER_NAME: "corr-abc-123"})

    assert response.status_code == 200
    assert "request_id=corr-abc-123" in console_log.getvalue()


async def test_le_format_json_serialise_le_request_id(
    app: FastAPI, client: AsyncClient, json_log: StringIO
) -> None:
    """Le champ doit être une **clé**, pas un fragment de texte.

    Un collecteur de journaux n'indexe que ce qui est structuré : un identifiant
    noyé dans le message ne se cherche pas.
    """
    logger = get_logger("test.correlation.json")

    @app.get("/api/v1/_test/log-json")
    async def emit_log() -> dict[str, str]:
        logger.warning("piste perdue", track_id=7)
        return {"ok": "1"}

    await client.get("/api/v1/_test/log-json", headers={HEADER_NAME: "corr-json-9"})

    records = _records(json_log, "piste perdue")
    assert records, "le journal attendu n'a pas été émis"
    assert records[-1]["request_id"] == "corr-json-9"
    assert records[-1]["track_id"] == 7
    assert records[-1]["level"] == "warning"


async def test_deux_requetes_ne_partagent_pas_leur_identifiant(
    app: FastAPI, client: AsyncClient, json_log: StringIO
) -> None:
    """Le contexte est isolé par requête.

    Un identifiant stocké dans une variable de module fuirait d'une requête à
    l'autre et corrélerait des évènements sans rapport — ce qui est pire que pas
    de corrélation du tout. C'est ce que le `ContextVar` garantit.
    """
    logger = get_logger("test.isolation")

    @app.get("/api/v1/_test/log-isolation")
    async def emit_log() -> dict[str, str]:
        logger.info("marqueur d'isolation")
        return {"ok": "1"}

    await client.get("/api/v1/_test/log-isolation", headers={HEADER_NAME: "premiere"})
    await client.get("/api/v1/_test/log-isolation", headers={HEADER_NAME: "seconde"})

    identifiers = [record["request_id"] for record in _records(json_log, "marqueur d'isolation")]
    assert identifiers == ["premiere", "seconde"]


def test_hors_requete_le_champ_est_absent_plutot_que_factice(json_log: StringIO) -> None:
    """Une tâche de fond ne doit pas journaliser `request_id: "unknown"`.

    Un champ toujours présent mais parfois faux est pire qu'un champ absent : il
    fait croire à une corrélation qui n'existe pas.
    """
    get_logger("test.tache_de_fond").info("purge TTL terminée", removed=3)

    records = _records(json_log, "purge TTL")
    assert records
    assert "request_id" not in records[-1]


def test_le_rendu_console_ne_colore_pas_un_tampon(console_log: StringIO) -> None:
    """Les séquences d'échappement ANSI sont du bruit hors d'un terminal.

    Dans un fichier de journal ou dans une assertion, elles rendent le texte
    illisible et font échouer des comparaisons pourtant correctes.
    """
    get_logger("test.couleurs").info("sans couleur")

    assert "\x1b[" not in console_log.getvalue()
