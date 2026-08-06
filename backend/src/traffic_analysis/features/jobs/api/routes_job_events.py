"""Flux SSE de progression d'un job.

Quatre règles, chacune correspondant à une façon de rendre une barre de
progression menteuse :

1. **L'état courant part en premier.** Un client qui se (re)connecte ne doit pas
   attendre la prochaine image pour savoir où en est l'analyse.
2. **`X-Accel-Buffering: no`.** Sans cet en-tête, un proxy tamponne le flux et la
   barre paraît figée pendant des dizaines de secondes (piège 44 de prompt/13).
3. **Un `ping` toutes les 15 s.** Un flux silencieux est coupé par la plupart des
   intermédiaires ; le commentaire SSE `: ping` le maintient sans polluer le
   client.
4. **Le SSE est un accélérateur, pas la vérité.** Le client double d'un sondage
   lent sur `GET /jobs/{id}` ; le serveur doit donc rester correct même si
   personne ne consomme jamais ce flux.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from traffic_analysis.features.jobs.api.deps import JobManagerDep, ProgressHubDep
from traffic_analysis.features.jobs.domain.status import is_terminal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from traffic_analysis.features.jobs.application.job_manager import JobManager
    from traffic_analysis.features.jobs.application.progress_hub import ProgressHub

router = APIRouter(prefix="/jobs", tags=["jobs"])

PING_INTERVAL_S = 15.0

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # L'en-tête qui empêche un proxy de tamponner le flux.
    "X-Accel-Buffering": "no",
}


@router.get(
    "/{job_id}/events",
    operation_id="streamAnalysisJobEvents",
    summary="Progression d'un job en Server-Sent Events",
    description=(
        "Flux `text/event-stream`. Trois types d'événements :\n\n"
        "```\n"
        "event: progress\n"
        'data: {"jobId":"…","status":"running","progress":0.12,…}\n\n'
        "event: preview\n"
        'data: {"jobId":"…","frameIndex":120,"timestampMs":4000.0,'
        '"frameWidth":1280,"frameHeight":720,"tracks":[…],"crossings":[…],'
        '"zoneEvents":[…],"stats":{…}}\n\n'
        "event: end\n"
        'data: {"jobId":"…","status":"done","progress":1.0,…}\n'
        "```\n\n"
        "L'événement `preview` est un **aperçu échantillonné** de l'analyse en "
        "cours — les pistes de l'image analysée, les événements survenus depuis "
        "l'aperçu précédent, et les compteurs courants. Sa forme est celle du "
        "`frameResult` du temps réel. Il est publié au plus toutes les "
        "`TRAFFIC_PREVIEW_INTERVAL_MS` millisecondes (0 = désactivé), n'est "
        "jamais persisté, et **un client peut l'ignorer entièrement** : la "
        "vérité de l'avancement reste `progress` et le sondage.\n\n"
        "L'**état courant est toujours envoyé en premier**, y compris si le job "
        "est déjà terminé — auquel cas le flux envoie `progress` puis `end` et se "
        "ferme immédiatement.\n\n"
        "Un commentaire `: ping` est émis toutes les 15 s pour traverser les "
        "proxys. Ce flux est un accélérateur : le client doit aussi sonder "
        "`GET /jobs/{id}` toutes les 3 s, car un SSE peut tomber sans prévenir."
    ),
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "Flux d'événements"},
        404: {"description": "Job inconnu"},
    },
)
async def stream_events(
    manager: JobManagerDep, hub: ProgressHubDep, job_id: str
) -> StreamingResponse:
    # La vérification d'existence a lieu **avant** d'ouvrir le flux : un 404 dans
    # un corps SSE déjà commencé serait invisible pour le client.
    await manager.get(job_id)
    return StreamingResponse(
        _events(manager, hub, job_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _encode(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _events(manager: JobManager, hub: ProgressHub, job_id: str) -> AsyncIterator[str]:
    """Produit le flux : état courant, puis mises à jour, puis fin."""
    record = await manager.get(job_id)
    current = manager.describe(record)
    yield _encode("progress", current)

    if is_terminal(record.status):
        # Déjà fini : on le dit et on ferme, plutôt que de laisser une connexion
        # ouverte sur un job qui n'émettra plus rien.
        yield _encode("end", current)
        return

    subscription = hub.subscribe(job_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(anext(subscription), timeout=PING_INTERVAL_S)
            except TimeoutError:
                # Commentaire SSE : maintient la connexion sans que le client ait
                # à filtrer un faux événement.
                yield ": ping\n\n"
                continue
            except StopAsyncIteration:
                return

            yield _encode("end" if event.terminal else event.kind, event.payload)
            if event.terminal:
                return
    finally:
        # Désabonnement garanti : un onglet fermé en plein flux ne doit pas
        # laisser une file grossir côté serveur.
        with suppress(Exception):
            await subscription.aclose()
