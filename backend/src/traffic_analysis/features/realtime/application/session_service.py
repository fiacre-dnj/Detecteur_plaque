"""Le service de session temps réel.

Il détient trois choses, et rien d'autre : le **compteur de sessions actives**, le
**flux de suivi** (donc le bail du modèle), et la **session de comptage du domaine**.

Deux règles gouvernent ce module.

**Une session par serveur.** Chaque session immobilise une instance de modèle via un
bail. Deux sessions simultanées sur la même instance partageraient l'état de suivi et
**mélangeraient deux flux vidéo** — des chiffres plausibles et complètement faux
(invariant 9). La place est donc réservée **avant `accept()`** côté route, ce qui
permet de refuser en 1013 sans jamais avoir ouvert la connexion.

**La géométrie est établie à partir de la première frame reçue.** Le serveur compte
dans l'espace de l'image qu'il reçoit, jamais dans celui que le client prétend
utiliser. C'est ce qui rend le contrôle de dimensions du message `ready` utile : le
serveur dit ce qu'il a vu, et le client vérifie que c'est ce qu'il croyait envoyer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio.to_thread

from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import AnalysisJobConfig, AnalysisSession
from traffic_analysis.features.counting.application.serializers import (
    serialise_crossing,
    serialise_stats,
    serialise_track,
    serialise_zone_event,
)

if TYPE_CHECKING:
    from typing import Any

    import numpy as np
    import numpy.typing as npt

    from traffic_analysis.features.counting.application.ports import (
        DetectionTrackingEngine,
        TrackingStream,
    )

logger = get_logger("traffic_analysis.realtime")


class SessionBusyError(RuntimeError):
    """Toutes les sessions temps réel sont occupées.

    Une exception dédiée pour que la route puisse fermer en **1013** (« réessayez
    plus tard ») plutôt qu'en 1008 : la requête du client est valide, c'est le
    serveur qui est saturé, et cette différence dit au client s'il doit réessayer.
    """


class RealtimeSessionService:
    """Ouvre, alimente et ferme une session de comptage en direct."""

    __slots__ = ("_active", "_engine", "_max_sessions")

    def __init__(self, engine: DetectionTrackingEngine, *, max_sessions: int = 1) -> None:
        self._engine = engine
        self._max_sessions = max_sessions
        self._active = 0

    def try_acquire(self) -> bool:
        """Réserve une place **sans attendre**.

        Sans attente délibérément : la route doit pouvoir répondre 1013 tout de
        suite. Faire patienter un client sur un handshake qui n'aboutira peut-être
        jamais est pire qu'un refus explicite qu'il peut retenter.

        Un compteur entier plutôt qu'un `asyncio.Semaphore` : ce dernier n'expose
        pas d'acquisition non bloquante, et la contourner demandait de piloter la
        coroutine à la main — trop subtil pour ce qu'on en fait. La boucle asyncio
        est mono-thread et il n'y a aucun `await` entre le test et l'incrément, donc
        un simple compteur est exactement aussi correct et se lit d'un coup d'œil.
        """
        if self._active >= self._max_sessions:
            return False
        self._active += 1
        return True

    def release(self) -> None:
        """Rend la place. **Toujours** appelée depuis un `finally`."""
        self._active = max(0, self._active - 1)

    @property
    def active(self) -> int:
        """Sessions en cours — exposé pour `/health` et les tests."""
        return self._active

    def open(self, config: AnalysisJobConfig) -> LiveSession:
        """Ouvre un flux de suivi et la session de comptage associée.

        Le flux prend le bail du modèle **et le garde** jusqu'à `close()` : c'est ce
        qui fait d'une suite d'images un flux plutôt que des frames indépendantes.
        """
        stream = self._engine.open_stream(config.engine_spec())
        return LiveSession(stream, config)


class LiveSession:
    """Une session en direct : un flux de suivi et une session de comptage.

    La session du domaine est créée **paresseusement**, à la première frame : ses
    dimensions viennent de l'image reçue, et les inventer avant serait exactement
    l'erreur que le message `ready` existe pour rendre visible.
    """

    __slots__ = ("_config", "_counting", "_frame_index", "_height", "_stream", "_width")

    def __init__(self, stream: TrackingStream, config: AnalysisJobConfig) -> None:
        self._stream = stream
        self._config = config
        # `AnalysisSession | None` et non `Any` : le type dit que la session peut ne
        # pas exister encore, ce qui est exactement l'invariant de ce module — les
        # dimensions viennent de la première frame reçue.
        self._counting: AnalysisSession | None = None
        self._frame_index = 0
        self._width = 0
        self._height = 0

    @property
    def frame_size(self) -> tuple[int, int] | None:
        """Dimensions réellement reçues, ou `None` avant la première frame."""
        return (self._width, self._height) if self._counting is not None else None

    async def process(self, image: npt.NDArray[np.uint8], timestamp_ms: float) -> dict[str, Any]:
        """Traite une frame et rend le `frameResult` sérialisé.

        Le suivi part dans un **thread worker** : il touche PyTorch et bloque
        (invariant 11). Le laisser dans la boucle figerait tout le service, y compris
        les autres requêtes HTTP et la sonde de vivacité.
        """
        counting = self._counting
        if counting is None:
            counting = self._start_counting(image)

        observations = await anyio.to_thread.run_sync(
            lambda: self._stream.track(image, timestamp_ms)
        )
        outcome = counting.feed(self._frame_index, timestamp_ms, observations)
        self._frame_index += 1

        return {
            "timestampMs": timestamp_ms,
            "frameIndex": outcome.frame_index,
            "frameWidth": self._width,
            "frameHeight": self._height,
            "tracks": [serialise_track(track) for track in outcome.tracks],
            "crossings": [serialise_crossing(event) for event in outcome.crossings],
            "zoneEvents": [serialise_zone_event(event) for event in outcome.zone_events],
            "stats": serialise_stats(counting.stats()),
        }

    def _start_counting(self, image: npt.NDArray[np.uint8]) -> AnalysisSession:
        """Crée la session de comptage aux dimensions **de l'image reçue**."""

        self._height = int(image.shape[0])
        self._width = int(image.shape[1])
        counting = AnalysisSession(self._config.session_config(), self._width, self._height)
        self._counting = counting
        logger.info("session temps réel démarrée", width=self._width, height=self._height)
        return counting

    def close(self) -> None:
        """Ferme le flux et **rend le bail du modèle**. Idempotent.

        Un bail non rendu immobilise une instance de modèle jusqu'au redémarrage du
        service : plus aucune analyse ne peut l'utiliser, et rien ne l'explique.
        """
        try:
            self._stream.close()
        except Exception as exc:  # pragma: no cover — garde-fou
            logger.warning("fermeture du flux en échec", error=str(exc))
