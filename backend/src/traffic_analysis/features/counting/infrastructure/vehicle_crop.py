"""« La vignette d'un véhicule » — une seule définition, deux consommateurs.

Ce module existe parce que deux étages recadrent le **même** objet et doivent le
recadrer **identiquement** :

- `opencv_snapshot_encoder`, qui en fait un JPEG montré à l'utilisateur ;
- `onnx_vehicle_embedder`, qui en fait un vecteur d'apparence.

Et surtout, le second recadre à la fois les véhicules de la vidéo **et** l'image de
requête importée par l'utilisateur. Si ces deux chemins ne partageaient pas la marge,
la comparaison serait faussée d'une façon indétectable : deux vignettes du même
véhicule, cadrées différemment, rendent des embeddings différents. La similarité
resterait plausible et sans rapport avec la ressemblance réelle — la panne silencieuse
type de ce projet. Voir ADR 0048.

`MIN_CROP_SIDE_PX` est le plancher d'existence d'une image, pas un plancher de
qualité : celui-là est un réglage, et il vit dans les `Settings`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

    from traffic_analysis.features.counting.domain.models import BoundingBox

#: Marge ajoutée autour de la boîte du véhicule, en fraction de sa taille.
#:
#: Le détecteur cadre au plus juste : un recadrage collé à sa boîte coupe le
#: pare-chocs et les rétroviseurs. « Seulement la voiture » ne veut pas dire « la
#: voiture amputée » — 6 % rend la vignette lisible sans y faire entrer la voie
#: d'à côté.
VEHICLE_MARGIN = 0.06

#: En dessous, il n'y a plus d'image — même borne que le détecteur de plaques.
MIN_CROP_SIDE_PX = 16


def crop(
    image: npt.NDArray[np.uint8], box: BoundingBox, *, margin: float
) -> npt.NDArray[np.uint8] | None:
    """Le recadrage borné aux dimensions de l'image, marge comprise.

    Même découpage que `UltralyticsPlateDetector._crop` : les bornes sont **clampées**
    et non supposées valides. Une boîte qui déborde de l'image existe réellement — un
    véhicule à moitié sorti du champ — et un `slice` négatif y rendrait un tableau
    vide, donc un JPEG vide, sans que rien ne lève.

    Rend une **vue** et non une copie : `image[y1:y2, x1:x2]` retient l'image parente
    entière, 6 Mo en 1080p. L'appelant doit encoder ou copier tout de suite, jamais
    retenir la vue.
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


def fit(crop_image: npt.NDArray[np.uint8], max_side: int) -> npt.NDArray[np.uint8]:
    """Réduit le recadrage pour que son plus grand côté tienne dans `max_side`.

    **Jamais d'agrandissement** : une vignette de 60 px étirée à 480 n'apporte aucun
    détail, elle coûte du fichier et donne l'illusion d'une image nette.
    """
    height, width = crop_image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return crop_image
    return resize(crop_image, max_side / longest)


def fit_width(crop_image: npt.NDArray[np.uint8], max_width: int) -> npt.NDArray[np.uint8]:
    """Comme `fit`, mais sur la largeur : une plaque est large et basse."""
    width = crop_image.shape[1]
    if width <= max_width:
        return crop_image
    return resize(crop_image, max_width / width)


def resize(crop_image: npt.NDArray[np.uint8], factor: float) -> npt.NDArray[np.uint8]:
    """`INTER_AREA`, la seule interpolation correcte pour réduire.

    Les autres échantillonnent au lieu de moyenner, donc font apparaître du crénelage
    sur les caractères d'une plaque — précisément ce qu'on cherche à rendre lisible.
    """
    height, width = crop_image.shape[:2]
    target = (max(1, int(width * factor)), max(1, int(height * factor)))
    resized = cv2.resize(crop_image, target, interpolation=cv2.INTER_AREA)
    return resized.astype(np.uint8, copy=False)


def sharpness(crop_image: npt.NDArray[np.uint8]) -> float:
    """Variance du laplacien — la mesure de netteté déjà utilisée pour l'OCR.

    La même métrique que `plate_ocr_min_sharpness` et pour la même raison : un
    recadrage assez grand mais flou de mouvement rend un résultat instable. La
    réutiliser plutôt qu'en inventer une autre garde les deux réglages comparables
    entre eux.
    """
    grey = cv2.cvtColor(crop_image, cv2.COLOR_BGR2GRAY) if crop_image.ndim == 3 else crop_image
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())
