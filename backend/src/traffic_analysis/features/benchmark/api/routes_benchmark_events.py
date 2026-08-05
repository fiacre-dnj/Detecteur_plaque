"""Flux SSE de progression d'un run de benchmark.

**Le même protocole que celui des jobs**, délibérément : mêmes noms d'événements,
même en-tête `X-Accel-Buffering`, même ping de maintien, même envoi de l'état
courant en premier. Le client réutilise donc son lecteur SSE au lieu d'en écrire un
second, et il n'y a qu'un seul endroit où corriger le tamponnage des proxys.

Un run de benchmark rend ce flux plus utile encore que pour un job : vingt modèles
sur CPU se comptent en minutes, chaque ligne arrive à son rythme, et sans flux la
page resterait immobile assez longtemps pour passer pour une panne.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from traffic_analysis.features.benchmark.api.deps import BenchmarkHubDep, BenchmarkServiceDep
from traffic_analysis.features.benchmark.application.service import describe
from traffic_analysis.features.benchmark.domain.records import is_terminal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from traffic_analysis.features.benchmark.application.service import BenchmarkService
    from traffic_analysis.features.jobs.application.progress_hub import ProgressHub

router = APIRouter(prefix="/benchmark", tags=["benchmark"])

PING_INTERVAL_S = 15.0

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # L'en-tête qui empêche un proxy de tamponner le flux : sans lui, la barre
    # paraît figée pendant des dizaines de secondes (piège 44 de prompt/13).
    "X-Accel-Buffering": "no",
}


@router.get(
    "/{run_id}/events",
    operation_id="streamBenchmarkRunEvents",
    summary="Progression d'un run de benchmark en Server-Sent Events",
    description=(
        "Flux `text/event-stream`, **même protocole que `/jobs/{id}/events`** :\n\n"
        "```\n"
        "event: progress\n"
        'data: {"runId":"…","status":"running","progress":0.35,"entries":[…]}\n\n'
        "event: end\n"
        'data: {"runId":"…","status":"done","progress":1.0,"entries":[…]}\n'
        "```\n\n"
        "Chaque événement porte le run **complet**, lignes déjà mesurées incluses : "
        "un client qui se connecte en cours de route n'a rien à rattraper.\n\n"
        "L'état courant est toujours envoyé en premier, y compris si le run est "
        "déjà terminé — auquel cas le flux envoie `progress` puis `end` et se ferme.\n\n"
        "Un commentaire `: ping` est émis toutes les 15 s pour traverser les proxys."
    ),
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "Flux d'événements"},
        404: {"description": "Run inconnu"},
    },
)
async def stream_events(
    service: BenchmarkServiceDep, hub: BenchmarkHubDep, run_id: str
) -> StreamingResponse:
    # Vérification d'existence **avant** d'ouvrir le flux : un 404 dans un corps
    # SSE déjà commencé serait invisible pour le client.
    await service.get(run_id)
    return StreamingResponse(
        _events(service, hub, run_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _encode(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _events(service: BenchmarkService, hub: ProgressHub, run_id: str) -> AsyncIterator[str]:
    """Produit le flux : état courant, puis mises à jour, puis fin."""
    run = await service.get(run_id)
    current = describe(run)
    yield _encode("progress", current)

    if is_terminal(run.status):
        # Déjà fini : on le dit et on ferme, plutôt que de laisser une connexion
        # ouverte sur un run qui n'émettra plus rien.
        yield _encode("end", current)
        return

    subscription = hub.subscribe(run_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(anext(subscription), timeout=PING_INTERVAL_S)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            except StopAsyncIteration:
                return

            yield _encode("end" if event.terminal else "progress", event.payload)
            if event.terminal:
                return
    finally:
        # Désabonnement garanti : un onglet fermé en plein flux ne doit pas laisser
        # une file grossir côté serveur.
        with suppress(Exception):
            await subscription.aclose()
