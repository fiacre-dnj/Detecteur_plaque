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
d'une milliseconde ; l'écriture disque n'a pas lieu ici du tout, elle est faite en une
passe à la fin de l'analyse.

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

if TYPE_CHECKING:
    import numpy.typing as npt

    from traffic_analysis.features.counting.domain.models import BoundingBox

logger = structlog.get_logger(__name__)

#: Marge ajoutée autour de la boîte du véhicule, en fraction de sa taille.
#:
#: Le détecteur cadre au plus juste : un recadrage collé à sa boîte coupe le
#: pare-chocs et les rétroviseurs. « Seulement la voiture » ne veut pas dire « la
#: voiture amputée » — 6 % rend la vignette lisible sans y faire entrer la voie
#: d'à côté.
VEHICLE_MARGIN = 0.06

#: Côté maximal de la vignette de véhicule, en pixels.
#:
#: La modale ne montre pas plus grand, et c'est ce qui garde le fichier autour de
#: 15 Ko. Réduire coûte moins cher que d'encoder un recadrage 4K en pleine taille.
MAX_VEHICLE_SIDE_PX = 480

#: Largeur maximale de la vignette de plaque. Une plaque est large et basse ; borner
#: la largeur borne les deux.
MAX_PLATE_WIDTH_PX = 320

#: En dessous, il n'y a plus d'image — même borne que le détecteur de plaques.
MIN_CROP_SIDE_PX = 16

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
            vehicle_crop = _crop(image, vehicle, margin=VEHICLE_MARGIN)
            plate_crop = _crop(image, plate, margin=0.0)
            if vehicle_crop is None or plate_crop is None:
                return None

            vehicle_jpeg = _encode(_fit(vehicle_crop, MAX_VEHICLE_SIDE_PX))
            plate_jpeg = _encode(_fit_width(plate_crop, MAX_PLATE_WIDTH_PX))
            if vehicle_jpeg is None or plate_jpeg is None:
                return None
        except Exception:
            # Une capture ratée n'est pas une analyse ratée : le véhicule reste
            # compté et sa plaque publiée, il n'a simplement pas de photo.
            logger.warning("capture de véhicule impossible", exc_info=True)
            return None

        return VehicleSnapshot(vehicle_jpeg=vehicle_jpeg, plate_jpeg=plate_jpeg)


def _crop(
    image: npt.NDArray[np.uint8], box: BoundingBox, *, margin: float
) -> npt.NDArray[np.uint8] | None:
    """Le recadrage borné aux dimensions de l'image, marge comprise.

    Même découpage que `UltralyticsPlateDetector._crop` : les bornes sont **clampées**
    et non supposées valides. Une boîte qui déborde de l'image existe réellement — un
    véhicule à moitié sorti du champ — et un `slice` négatif y rendrait un tableau
    vide, donc un JPEG vide, sans que rien ne lève.
    """
    height, width = image.shape[:2]
    pad_x = box.width * margin
    pad_y = box.height * margin
    x1 = max(0, int(box.x - pad_x))
    y1 = max(0, int(box.y - pad_y))
    x2 = min(width, int(box.x + box.width + pad_x))
    y2 = min(height, int(box.y + box.height + pad_y))
    if x2 - x1 < MIN_CROP_SIDE_PX or y2 - y1 < MIN_CROP_SIDE_PX:
        return None
    return image[y1:y2, x1:x2]


def _fit(crop: npt.NDArray[np.uint8], max_side: int) -> npt.NDArray[np.uint8]:
    """Réduit le recadrage pour que son plus grand côté tienne dans `max_side`.

    **Jamais d'agrandissement** : une vignette de 60 px étirée à 480 n'apporte aucun
    détail, elle coûte du fichier et donne l'illusion d'une image nette.
    """
    height, width = crop.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return crop
    return _resize(crop, max_side / longest)


def _fit_width(crop: npt.NDArray[np.uint8], max_width: int) -> npt.NDArray[np.uint8]:
    """Comme `_fit`, mais sur la largeur : une plaque est large et basse."""
    width = crop.shape[1]
    if width <= max_width:
        return crop
    return _resize(crop, max_width / width)


def _resize(crop: npt.NDArray[np.uint8], factor: float) -> npt.NDArray[np.uint8]:
    """`INTER_AREA`, la seule interpolation correcte pour réduire.

    Les autres échantillonnent au lieu de moyenner, donc font apparaître du crénelage
    sur les caractères d'une plaque — précisément ce qu'on cherche à rendre lisible.
    """
    height, width = crop.shape[:2]
    target = (max(1, int(width * factor)), max(1, int(height * factor)))
    resized = cv2.resize(crop, target, interpolation=cv2.INTER_AREA)
    return resized.astype(np.uint8, copy=False)


def _encode(crop: npt.NDArray[np.uint8]) -> bytes | None:
    ok, buffer = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    return bytes(buffer) if ok else None
