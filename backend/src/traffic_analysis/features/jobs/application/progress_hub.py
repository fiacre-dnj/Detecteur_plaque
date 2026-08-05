"""Diffusion de la progression : un publieur, N abonnés SSE.

Le service d'analyse ne connaît **aucun** transport. Il pousse un événement dans
le hub ; qui l'écoute et par quel protocole ne le regarde pas.

Deux contraintes de concurrence gouvernent ce module :

- la progression est publiée **depuis un thread worker**, alors que les abonnés
  vivent dans la boucle asyncio. Le passage se fait par
  `loop.call_soon_threadsafe` — un état muté depuis deux threads est un bug qui ne
  se reproduit qu'en charge ;
- un abonné lent ne doit jamais ralentir l'analyse. Chaque abonné a sa propre file
  bornée, et une file pleine **perd l'événement le plus ancien** : pour une barre
  de progression, la valeur la plus récente est la seule qui compte.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from traffic_analysis.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = get_logger("traffic_analysis.progress")

# Assez pour absorber une rafale, assez petit pour qu'un abonné bloqué ne retienne
# pas un historique inutile : seule la dernière valeur intéresse une barre.
SUBSCRIBER_QUEUE_SIZE = 16


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Un événement de progression, prêt à être encodé en SSE.

    `terminal` marque le dernier événement d'un job : c'est lui qui permet au
    flux SSE de se fermer proprement au lieu de rester ouvert pour rien.
    """

    job_id: str
    payload: dict[str, Any]
    terminal: bool = False


class ProgressHub:
    """Publie les événements de progression vers les abonnés d'un job."""

    __slots__ = ("_last", "_loop", "_subscribers")

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[ProgressEvent]]] = {}
        # Dernier état connu par job. C'est ce qui permet à un client qui se
        # (re)connecte de savoir immédiatement où en est l'analyse, au lieu
        # d'attendre la prochaine frame — sur un job long, l'attente se compte en
        # secondes et l'interface paraît cassée.
        self._last: dict[str, ProgressEvent] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Mémorise la boucle vers laquelle republier depuis un thread worker."""
        self._loop = loop

    def last_event(self, job_id: str) -> ProgressEvent | None:
        return self._last.get(job_id)

    def publish(self, event: ProgressEvent) -> None:
        """Publie depuis la boucle asyncio."""
        self._last[event.job_id] = event
        for queue in tuple(self._subscribers.get(event.job_id, ())):
            self._offer(queue, event)

    def publish_threadsafe(self, event: ProgressEvent) -> None:
        """Publie **depuis un thread worker**.

        Repasse par la boucle plutôt que de toucher directement aux files : les
        `asyncio.Queue` ne sont pas sûres entre threads, et le bug qui en résulte
        n'apparaît qu'en charge, ce qui le rend très coûteux à diagnostiquer.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            # Hors boucle (test synchrone, arrêt en cours) : la publication
            # directe est sûre puisqu'il n'y a personne d'autre pour toucher
            # l'état.
            self.publish(event)
            return
        loop.call_soon_threadsafe(self.publish, event)

    @staticmethod
    def _offer(queue: asyncio.Queue[ProgressEvent], event: ProgressEvent) -> None:
        """Dépose l'événement, en écartant le plus ancien si la file est pleine.

        Écarter et non bloquer : un abonné lent — un onglet en veille, un proxy
        qui tamponne — ne doit jamais ralentir l'analyse elle-même.
        """
        if queue.full():
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with suppress(asyncio.QueueFull):
            queue.put_nowait(event)

    async def subscribe(self, job_id: str) -> AsyncGenerator[ProgressEvent, None]:
        """S'abonne aux événements d'un job jusqu'à son événement terminal.

        Le désabonnement est garanti par un `finally` : un client qui ferme son
        onglet en plein flux ne doit pas laisser une file grossir indéfiniment.
        """
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.setdefault(job_id, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.terminal:
                    return
        finally:
            subscribers = self._subscribers.get(job_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    del self._subscribers[job_id]

    def forget(self, job_id: str) -> None:
        """Oublie l'état d'un job purgé, pour borner la mémoire du hub."""
        self._last.pop(job_id, None)
