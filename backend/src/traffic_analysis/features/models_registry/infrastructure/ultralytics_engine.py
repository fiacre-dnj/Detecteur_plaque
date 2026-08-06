"""Adaptateur Ultralytics — **le seul importateur d'`ultralytics` du projet**.

C'est ici, et nulle part ailleurs, que `Results`/`Boxes`/`xyxy` deviennent des
`TrackObservation` du domaine. Un test d'architecture le vérifie.

Le temps de scène est vrai **par construction** : `timestamp_ms` vient de
`frame_index / fps`, jamais d'une horloge. Introduire `time.time()` ici casserait
d'un coup les débits, les vitesses et les gates de ré-identification.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from traffic_analysis.core.errors import UnsupportedMediaError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import (
    BoundingBox,
    EngineFrame,
    TrackObservation,
    VideoInfo,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import numpy as np
    import numpy.typing as npt

    from traffic_analysis.features.counting.application.ports import EngineSpec
    from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry

logger = get_logger("traffic_analysis.engine")

# Cadence de repli quand le conteneur n'en déclare pas. 30 est le choix le moins
# faux : sur- ou sous-estimer décale tous les horodatages métier.
DEFAULT_FPS = 30.0

# `parents[5]` mène à `backend/` : infrastructure → models_registry → features →
# traffic_analysis → src → backend. Compté à la main, ce décalage a été **faux**
# (`parents[4]`, donc `backend/src/config/`) et l'erreur ne se voyait qu'à
# l'exécution d'une vraie analyse : les tests injectent un `FakeEngine` et ne
# passent jamais ici. D'où le test d'existence ci-dessous, qui échoue au
# chargement du module plutôt qu'au milieu d'un job.
CONFIG_DIR = Path(__file__).resolve().parents[5] / "config"
TRACKER_CONFIG = CONFIG_DIR / "botsort_reid.yaml"


class UltralyticsEngine:
    """Détection et suivi par Ultralytics, derrière le port du domaine."""

    __slots__ = ("_registry",)

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def probe(self, video_path: Path) -> VideoInfo:
        """Dimensions, cadence et nombre d'images — et validation de format.

        Une vidéo qu'OpenCV ne peut pas ouvrir n'est pas une vidéo, quoi qu'en
        dise son extension ou son `content-type`.
        """
        import cv2

        capture = cv2.VideoCapture(str(video_path))
        try:
            if not capture.isOpened():
                raise UnsupportedMediaError("Ce fichier n'a pas pu être ouvert comme une vidéo.")
            fps = float(capture.get(cv2.CAP_PROP_FPS)) or DEFAULT_FPS
            info = VideoInfo(
                width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                # Une cadence nulle ou aberrante rendrait tous les horodatages
                # infinis : on retombe sur la valeur de repli.
                fps=fps if fps > 0 else DEFAULT_FPS,
                frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            )
        finally:
            capture.release()
        return info

    def iter_video(self, video_path: Path, spec: EngineSpec) -> Iterator[EngineFrame]:
        """Parcourt la vidéo sous un **unique bail** de modèle.

        Un bail pour toute l'itération : deux `track()` simultanés sur la même
        instance partageraient l'état de suivi et mélangeraient deux vidéos.
        """
        info = self.probe(video_path)
        stride = max(1, spec.frame_stride)

        with self._registry.lease(spec.model_id) as model:
            results = model.track(
                source=str(video_path),
                stream=True,
                tracker=str(TRACKER_CONFIG),
                conf=spec.confidence,
                iou=spec.iou,
                classes=list(spec.class_ids),
                # **NMS inter-classes**, et c'est le piège 5 de prompt/13. Le NMS
                # par défaut d'Ultralytics est *class-aware* : il ne compare que
                # des boîtes de même classe. Une camionnette scorée `car 0.52`
                # **et** `truck 0.41` survit donc en double, devient deux pistes,
                # deux identités, et compte deux fois. Nos quatre classes sont
                # mutuellement exclusives sur un objet physique, donc la
                # suppression doit ignorer la classe.
                agnostic_nms=True,
                device=self._registry.device(),
                half=self._registry.half(),
                vid_stride=stride,
                persist=True,
                verbose=False,
            )
            for position, result in enumerate(results):
                frame_index = position * stride
                yield EngineFrame(
                    frame_index=frame_index,
                    # Temps de scène, vrai par construction.
                    timestamp_ms=frame_index / info.fps * 1000.0,
                    image=result.orig_img,
                    tracks=_to_observations(result),
                )

    def open_stream(self, spec: EngineSpec) -> UltralyticsStream:
        """Ouvre un flux persistant pour le temps réel.

        Le bail reste ouvert jusqu'à `close()` : c'est ce qui fait d'une suite
        d'images un **flux** plutôt que des frames indépendantes.
        """
        return UltralyticsStream(self._registry, spec)


class UltralyticsStream:
    """Suivi image par image, avec état persistant entre les appels."""

    __slots__ = ("_lease", "_model", "_registry", "_spec")

    def __init__(self, registry: ModelRegistry, spec: EngineSpec) -> None:
        self._registry = registry
        self._spec = spec
        # Le gestionnaire de contexte est conservé et fermé à la main : le bail
        # doit survivre à l'appel qui l'ouvre, contrairement à `iter_video`.
        self._lease = registry.lease(spec.model_id)
        self._model = self._lease.__enter__()

    def track(
        self,
        image: npt.NDArray[np.uint8],
        timestamp_ms: float,  # noqa: ARG002 — le temps vient du client en temps réel
    ) -> tuple[TrackObservation, ...]:
        results = self._model.track(
            source=image,
            # `persist=True` est ce qui fait d'une suite d'images un flux : sans
            # lui, chaque frame repartirait avec des identifiants neufs et rien
            # ne serait jamais suivi.
            persist=True,
            tracker=str(TRACKER_CONFIG),
            conf=self._spec.confidence,
            iou=self._spec.iou,
            classes=list(self._spec.class_ids),
            # Voir le mode différé : NMS inter-classes, sinon une camionnette
            # survit en `car` **et** en `truck` et compte deux fois.
            agnostic_nms=True,
            device=self._registry.device(),
            half=self._registry.half(),
            verbose=False,
        )
        return _to_observations(results[0]) if results else ()

    def close(self) -> None:
        """Ferme le flux et **rend le bail**. Idempotent."""
        if self._lease is not None:
            self._lease.__exit__(None, None, None)
            self._lease = None  # type: ignore[assignment]


def _to_observations(result: Any) -> tuple[TrackObservation, ...]:  # noqa: ANN401
    """Traduit un `Results` d'Ultralytics en vocabulaire du domaine.

    `boxes.id is None` est **normal** sur les premières frames : le tracker n'a
    encore rien confirmé. Ce n'est pas une erreur, et lever ici ferait échouer
    toute analyse dès sa première image (piège 33 de prompt/13).
    """
    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.id is None:
        return ()

    names: dict[int, str] = getattr(result, "names", {}) or {}
    xyxy = boxes.xyxy.cpu().numpy()
    ids = boxes.id.cpu().numpy().astype(int)
    classes = boxes.cls.cpu().numpy().astype(int)
    scores = boxes.conf.cpu().numpy()

    observations: list[TrackObservation] = []
    # `strict=True` : une désynchronisation entre boîtes, ids, classes et scores
    # doit **lever**, pas produire des chiffres. Un décalage d'un élément
    # attribuerait chaque score au mauvais véhicule, sans rien casser d'autre.
    for box, track_id, class_id, score in zip(xyxy, ids, classes, scores, strict=True):
        x1, y1, x2, y2 = (float(value) for value in box)
        observations.append(
            TrackObservation(
                track_id=int(track_id),
                class_id=int(class_id),
                label=names.get(int(class_id), str(int(class_id))),
                score=float(score),
                box=BoundingBox(x=x1, y=y1, width=x2 - x1, height=y2 - y1),
            )
        )
    return tuple(observations)
