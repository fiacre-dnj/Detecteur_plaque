"""Moteurs factices — le cœur du dispositif de test.

C'est ce qui permet à la CI de tourner **sans GPU, sans poids et sans
ultralytics**. Un test qui a besoin de télécharger 40 Mo est un test mal conçu.

Les images sont des `np.zeros` : les tests du comptage ne dépendent d'aucun pixel.
Les seuls tests qui en dépendent sont ceux de la ré-identification, qui
construisent des crops de couleurs contrôlées.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from traffic_analysis.features.counting.application.ports import EngineFrame
from traffic_analysis.features.counting.domain.models import (
    BoundingBox,
    PlateDetection,
    TrackObservation,
    VideoInfo,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    import numpy.typing as npt

    from traffic_analysis.features.counting.application.ports import EngineSpec

DEFAULT_INFO = VideoInfo(width=1920, height=1080, fps=25.0, frame_count=0)


class FakeEngine:
    """Rejoue une liste de frames préparée à la main.

    Satisfait `DetectionTrackingEngine` sans en hériter : c'est tout l'intérêt des
    `Protocol`.
    """

    def __init__(
        self,
        frames: Sequence[Sequence[TrackObservation]],
        *,
        info: VideoInfo | None = None,
        texture: int = 40,
        fail_with: Exception | None = None,
    ) -> None:
        self._frames = [tuple(frame) for frame in frames]
        self._info = info or VideoInfo(
            width=DEFAULT_INFO.width,
            height=DEFAULT_INFO.height,
            fps=DEFAULT_INFO.fps,
            frame_count=len(self._frames),
        )
        self._texture = texture
        # Permet de tester le chemin d'échec d'un job sans provoquer un vrai bug.
        self._fail_with = fail_with
        self.probe_calls = 0
        self.iterated_frames = 0

    def probe(self, video_path: Path) -> VideoInfo:  # noqa: ARG002
        self.probe_calls += 1
        return self._info

    def iter_video(self, video_path: Path, spec: EngineSpec) -> Iterator[EngineFrame]:  # noqa: ARG002
        """Parcourt les frames préparées, en respectant le pas d'analyse.

        Le pas est appliqué ici comme le ferait `vid_stride` d'Ultralytics, et
        `frame_index = position × stride` : sans cela, les horodatages du test ne
        correspondraient pas à ceux de la production et la progression serait
        testée sur une unité différente de celle qui est servie.
        """
        if self._fail_with is not None:
            raise self._fail_with

        stride = max(1, spec.frame_stride)
        image = self.image()
        for position, tracks in enumerate(self._frames[::stride]):
            frame_index = position * stride
            self.iterated_frames += 1
            yield EngineFrame(
                frame_index=frame_index,
                timestamp_ms=frame_index / self._info.fps * 1000.0,
                image=image,
                tracks=tracks,
            )

    def open_stream(self, spec: EngineSpec) -> FakeStream:  # noqa: ARG002
        return FakeStream(self._frames, self.image())

    def image(self) -> npt.NDArray[np.uint8]:
        """Image texturée : la ré-identification a besoin d'apparence.

        Une image parfaitement noire donnerait un descripteur de norme nulle, donc
        des similarités toutes égales à zéro — les tests d'identité passeraient
        pour de mauvaises raisons.
        """
        image = np.zeros((self._info.height, self._info.width, 3), dtype=np.uint8)
        if self._texture:
            image[:, :] = (self._texture, 90, 200 - self._texture)
            image[::5, :] = (240, 240, 240)
        return image


class FakeStream:
    """Flux de suivi factice, pour le temps réel."""

    def __init__(
        self,
        frames: Sequence[Sequence[TrackObservation]],
        image: npt.NDArray[np.uint8],
    ) -> None:
        self._frames = [tuple(frame) for frame in frames]
        self._image = image
        self._position = 0
        self.closed = False

    def track(
        self,
        image: npt.NDArray[np.uint8],  # noqa: ARG002
        timestamp_ms: float,  # noqa: ARG002
    ) -> tuple[TrackObservation, ...]:
        """Rend la frame suivante, puis boucle sur la dernière.

        Boucler plutôt que s'épuiser : une session temps réel dure aussi longtemps
        que l'utilisateur le veut, et un test ne doit pas avoir à préparer mille
        frames.
        """
        if not self._frames:
            return ()
        tracks = self._frames[min(self._position, len(self._frames) - 1)]
        self._position += 1
        return tracks

    def close(self) -> None:
        self.closed = True


class FakePlateDetector:
    """Détecteur de plaques factice, à disponibilité contrôlable."""

    def __init__(self, *, available: bool = True, score: float = 0.71) -> None:
        self._available = available
        self._score = score
        self.calls = 0

    @property
    def available(self) -> bool:
        return self._available

    def detect(
        self,
        image: npt.NDArray[np.uint8],  # noqa: ARG002
        box: BoundingBox,
    ) -> tuple[PlateDetection, ...]:
        """Rend une plaque plausible, en coordonnées de l'image **complète**.

        Les coordonnées absolues et non relatives au crop : c'est le contrat du
        port, et un test qui accepterait des coordonnées relatives laisserait
        passer un adaptateur qui oublie de les réexprimer.
        """
        self.calls += 1
        if not self._available:
            return ()
        plate = BoundingBox(
            x=box.x + box.width * 0.3,
            y=box.y + box.height * 0.65,
            width=box.width * 0.4,
            height=box.height * 0.15,
        )
        return (PlateDetection(box=plate, score=self._score),)
