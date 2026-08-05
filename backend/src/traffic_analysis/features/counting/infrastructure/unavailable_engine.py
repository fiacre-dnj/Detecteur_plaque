"""Moteur de repli, quand aucun moteur de vision n'est disponible.

Ce n'est pas du code « au cas où » : c'est ce qui permet au service de démarrer et
de répondre à `/health` sur une machine où `ultralytics` n'est pas installable, au
lieu de refuser de booter. L'erreur arrive alors au **premier usage réel**, elle
est explicite, et elle dit quoi faire.

L'alternative — un `None` dans le conteneur — produirait une `AttributeError`
opaque au milieu d'une analyse, trente secondes après le dépôt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from traffic_analysis.core.errors import UnavailableError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from traffic_analysis.features.counting.application.ports import (
        EngineFrame,
        EngineSpec,
        TrackingStream,
    )
    from traffic_analysis.features.counting.domain.models import VideoInfo

MESSAGE = (
    "Aucun moteur de détection n'est configuré sur ce serveur. "
    "Vérifiez l'installation d'Ultralytics et le répertoire des poids."
)


class UnavailableEngine:
    """Satisfait `DetectionTrackingEngine` et refuse tout, clairement."""

    def probe(self, video_path: Path) -> VideoInfo:  # noqa: ARG002
        self._fail()

    def iter_video(self, video_path: Path, spec: EngineSpec) -> Iterator[EngineFrame]:  # noqa: ARG002
        self._fail()

    def open_stream(self, spec: EngineSpec) -> TrackingStream:  # noqa: ARG002
        self._fail()

    @staticmethod
    def _fail() -> NoReturn:
        raise UnavailableError(MESSAGE, code="engine_unavailable")
