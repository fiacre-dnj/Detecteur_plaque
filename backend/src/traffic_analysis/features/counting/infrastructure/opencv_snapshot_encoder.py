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

#: Plancher d'existence de la **vignette de plaque**, plus bas que celui du véhicule.
#:
#: Mesuré, et c'est ce qui a fait ajouter cette constante : sur une vue de circulation
#: réelle, les plaques localisées font 27 à 88 px de large pour **9 à 28 px de haut**.
#: Le plancher de 16 px de `vehicle_crop` — qui est celui d'une entrée de réseau —
#: refusait donc la capture **entière**, véhicule compris, exactement dans le cas
#: qu'ADR 0051 existe pour servir : la plaque vue mais illisible. La panne était
#: silencieuse : `encode` rend `None`, rien n'est enregistré, et l'analyse se termine
#: sans une photo ni un message.
#:
#: 8 px et non 1 : en dessous il n'y a plus rien à agrandir, et une « plaque » de 6×3
#: px n'est pas une plaque mais un artefact du détecteur — la refuser refuse aussi la
#: photo du véhicule, ce qui est le bon comportement puisqu'il n'y avait rien à
#: montrer.
MIN_PLATE_CROP_SIDE_PX = 8


class OpenCvSnapshotEncoder:
    """Implémentation OpenCV de `VehicleSnapshotEncoder`. Ne lève jamais."""

    __slots__ = ()

    def encode(
        self,
        image: npt.NDArray[np.uint8],
        vehicle: BoundingBox,
        plate: BoundingBox | None,
    ) -> VehicleSnapshot | None:
        try:
            vehicle_thumb = crop(image, vehicle, margin=VEHICLE_MARGIN)
            if vehicle_thumb is None:
                return None
            plate_thumb = (
                None
                if plate is None
                else crop(image, plate, margin=0.0, min_side=MIN_PLATE_CROP_SIDE_PX)
            )
            # **Refus total et jamais dégradation.** Rendre la vignette de véhicule
            # sans celle de la plaque quand une plaque était demandée donnerait un
            # `snapshotKind == "plate_text"` sans plaque à montrer : un contrat qui se
            # contredit, et un écran qui annonce « plaque lue » sans la montrer.
            if plate is not None and plate_thumb is None:
                return None

            vehicle_jpeg = _encode(fit(vehicle_thumb, MAX_VEHICLE_SIDE_PX))
            if vehicle_jpeg is None:
                return None
            plate_jpeg = (
                None if plate_thumb is None else _encode(fit_width(plate_thumb, MAX_PLATE_WIDTH_PX))
            )
            if plate is not None and plate_jpeg is None:
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
