"""Recadrage et encodage JPEG d'une capture de véhicule — le seul endroit à pixels.

**Pourquoi ce paquet existe.** `cv2` est interdit dans `features/*/domain/**` et
dans `features/*/application/**` (`tests/test_architecture.py`), et c'est cette
interdiction qui permet à la CI de tourner sans GPU, sans poids et sans OpenCV utile.
La décision « faut-il capturer » vit donc dans le domaine, et les pixels ici.

**Ce que ce module coûte, et pourquoi c'est acceptable.** Il n'est appelé que
lorsqu'une lecture de plaque bat la meilleure déjà retenue pour ce véhicule — quelques
fois dans la vie d'un véhicule, et jamais pour ceux dont aucune plaque n'est lue. Sur
une vraie scène, cela représente une poignée de véhicules sur une centaine suivis. Le
recadrage est un `slice` gratuit ; l'encodage d'une vignette de 480 px coûte moins
d'une milliseconde ; l'écriture disque n'a pas lieu ici du tout — elle est faite par
l'appelant, **au fil de l'analyse depuis ADR 0046** et non plus en une passe finale.
Ce qui borne le débit d'écriture est donc la règle monotone, pas le regroupement.

**Encoder tout de suite plutôt que garder les pixels** règle un piège de mémoire :
`image[y1:y2, x1:x2]` est une **vue**, pas une copie. Retenir la vue retiendrait
l'image parente entière — 6 Mo en 1080p, 25 Mo en 4K — pour chaque véhicule dont on
garde la meilleure capture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
import structlog

from traffic_analysis.features.counting.application.ports import VehicleSnapshot
from traffic_analysis.features.counting.infrastructure.vehicle_crop import (
    VEHICLE_MARGIN,
    crop,
    fit,
    fit_width,
)

if TYPE_CHECKING:
    import numpy.typing as npt

    from traffic_analysis.features.counting.domain.models import BoundingBox

logger = structlog.get_logger(__name__)

#: Côté maximal de la vignette de véhicule, en pixels.
#:
#: La modale ne montre pas plus grand, et c'est ce qui garde le fichier autour de
#: 15 Ko. Réduire coûte moins cher que d'encoder un recadrage 4K en pleine taille.
MAX_VEHICLE_SIDE_PX = 480

#: Largeur maximale de la vignette de plaque. Une plaque est large et basse ; borner
#: la largeur borne les deux.
MAX_PLATE_WIDTH_PX = 320

#: Qualité JPEG. 82 est le point où l'artefact cesse de se voir sur une plaque
#: recadrée ; au-delà le fichier grossit sans que rien ne se lise mieux.
JPEG_QUALITY = 82


class OpenCvSnapshotEncoder:
    """Implémentation OpenCV de `VehicleSnapshotEncoder`. Ne lève jamais."""

    __slots__ = ()

    def encode(
        self,
        image: npt.NDArray[np.uint8],
        vehicle: BoundingBox,
        plate: BoundingBox,
    ) -> VehicleSnapshot | None:
        try:
            vehicle_thumb = crop(image, vehicle, margin=VEHICLE_MARGIN)
            plate_thumb = crop(image, plate, margin=0.0)
            if vehicle_thumb is None or plate_thumb is None:
                return None

            vehicle_jpeg = _encode(fit(vehicle_thumb, MAX_VEHICLE_SIDE_PX))
            plate_jpeg = _encode(fit_width(plate_thumb, MAX_PLATE_WIDTH_PX))
            if vehicle_jpeg is None or plate_jpeg is None:
                return None
        except Exception:
            # Une capture ratée n'est pas une analyse ratée : le véhicule reste
            # compté et sa plaque publiée, il n'a simplement pas de photo.
            logger.warning("capture de véhicule impossible", exc_info=True)
            return None

        return VehicleSnapshot(vehicle_jpeg=vehicle_jpeg, plate_jpeg=plate_jpeg)


def _encode(thumb: npt.NDArray[np.uint8]) -> bytes | None:
    """`thumb` et non `crop` : ce dernier nomme la fonction importée de `vehicle_crop`.

    Un paramètre qui masque une fonction du module est le genre de collision qui ne
    lève que le jour où l'on ajoute un appel dans le corps.
    """
    ok, buffer = cv2.imencode(".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    return bytes(buffer) if ok else None
