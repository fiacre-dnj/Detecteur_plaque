"""Localisation de plaques, en passe secondaire sur chaque véhicule suivi.

**Pourquoi deux étages plutôt qu'une détection plein cadre.** Une plaque fait
~15 px de large sur un plan 1920×1080, et ~240 px une fois recadrée sur son
véhicule. Le modèle plein cadre ne la voit tout simplement pas.

Le coût est réel et doit être dit dans l'interface : **une inférence par piste et
par frame**, ~880 ms mesuré avec trois pistes. Il croît linéairement avec le
nombre de véhicules à l'écran.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import BoundingBox, PlateDetection

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt

logger = get_logger("traffic_analysis.anpr")

# En dessous, le recadrage ne contient pas assez de pixels pour qu'une plaque
# soit distinguable : l'inférence coûterait sans jamais rien trouver.
MIN_CROP_SIDE_PX = 32


class OnnxPlateDetector:
    """Détecteur de plaques ONNX, chargé **paresseusement**.

    Paresseusement parce que l'absence du fichier ne doit pas empêcher le service
    de démarrer : l'option ANPR est alors signalée indisponible dans `/health` et
    désactivée dans l'interface, et tout le reste fonctionne.
    """

    __slots__ = ("_checked", "_confidence", "_lock", "_model", "_path")

    def __init__(self, model_path: Path, confidence: float) -> None:
        self._path = model_path
        self._confidence = confidence
        self._model: Any = None
        self._checked = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Le fichier de poids est-il présent ?

        Une vérification de présence et non de chargement : charger pour répondre
        à `/health` prendrait des secondes à chaque appel, alors que l'interface
        interroge cette route en permanence.
        """
        return self._path.is_file()

    def detect(self, image: npt.NDArray[np.uint8], box: BoundingBox) -> tuple[PlateDetection, ...]:
        """Cherche une plaque dans `box`, en coordonnées de l'image **complète**.

        Ne lève **jamais** : une passe ANPR ratée rend une liste vide et
        journalise. Un comptage ne doit pas échouer parce qu'une plaque était
        illisible — c'est une option, pas le cœur du travail.
        """
        try:
            crop, origin_x, origin_y = self._crop(image, box)
            if crop is None:
                return ()
            model = self._ensure_loaded()
            if model is None:
                return ()
            return self._infer(model, crop, origin_x, origin_y)
        except Exception as exc:
            logger.warning("passe ANPR en échec", error=str(exc))
            return ()

    def _ensure_loaded(self) -> Any:  # noqa: ANN401 — YOLO n'est pas typé
        """Charge le modèle au premier usage réel, sous verrou."""
        loaded = self._model
        if loaded is not None:
            return loaded
        with self._lock:
            loaded = self._model
            if loaded is not None:
                return loaded
            if self._checked:
                # Déjà tenté et échoué : ne pas réessayer à chaque frame, ce qui
                # produirait des milliers de lignes de journal identiques.
                return None
            self._checked = True
            if not self._path.is_file():
                logger.warning("modèle de plaques absent — ANPR indisponible", path=str(self._path))
                return None
            from ultralytics import YOLO  # type: ignore[attr-defined]

            self._model = YOLO(str(self._path), task="detect")
            logger.info("modèle de plaques chargé", path=str(self._path))
            return self._model

    @staticmethod
    def _crop(
        image: npt.NDArray[np.uint8], box: BoundingBox
    ) -> tuple[npt.NDArray[np.uint8], int, int] | tuple[None, int, int]:
        height, width = image.shape[:2]
        x1 = max(0, int(box.x))
        y1 = max(0, int(box.y))
        x2 = min(width, int(box.x + box.width))
        y2 = min(height, int(box.y + box.height))
        if x2 - x1 < MIN_CROP_SIDE_PX or y2 - y1 < MIN_CROP_SIDE_PX:
            return None, 0, 0
        return image[y1:y2, x1:x2], x1, y1

    def _infer(
        self,
        model: Any,  # noqa: ANN401 — YOLO n'est pas typé
        crop: npt.NDArray[np.uint8],
        origin_x: int,
        origin_y: int,
    ) -> tuple[PlateDetection, ...]:
        results = model.predict(crop, conf=self._confidence, verbose=False)
        if not results:
            return ()
        boxes = getattr(results[0], "boxes", None)
        if boxes is None or len(boxes) == 0:
            return ()

        detections: list[PlateDetection] = []
        for raw, score in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), strict=True):
            x1, y1, x2, y2 = (float(value) for value in raw)
            detections.append(
                PlateDetection(
                    # Réexprimé dans le référentiel de l'image complète : aucune
                    # couche en aval ne doit avoir à savoir qu'il y a eu un crop.
                    box=BoundingBox(
                        x=x1 + origin_x, y=y1 + origin_y, width=x2 - x1, height=y2 - y1
                    ),
                    score=float(score),
                )
            )
        return tuple(detections)
