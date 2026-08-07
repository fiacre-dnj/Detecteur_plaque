"""Localisation de plaques, en passe secondaire sur chaque véhicule suivi.

**Pourquoi deux étages plutôt qu'une détection plein cadre.** Une plaque fait
~15 px de large sur un plan 1920×1080, et ~240 px une fois recadrée sur son
véhicule. Le modèle plein cadre ne la voit tout simplement pas.

**Le filtre de plausibilité est ce qui rend cet adaptateur utile.** Sans lui, la
sortie brute du modèle part telle quelle : sur 538 détections de vraie
circulation, 112 étaient la **boîte du véhicule entier** — un pare-chocs, une
paire de phares, un bloc de feux arrière — dont certaines à 0,87 de confiance,
c'est-à-dire au-dessus de tout seuil raisonnable. Elles étaient toutes dessinées
à l'écran *et* envoyées à l'OCR, qui y lisait le lettrage de carrosserie
(`SERVICE` sur un utilitaire). Les 426 boîtes retenues par le filtre étaient
toutes de vraies plaques. La séparation est géométrique et nette : une plaque
occupe 11 à 25 % de la largeur de son véhicule, une fausse détection 98 à 100 %.

**Pourquoi une mosaïque, et pourquoi elle est désactivée par défaut.** Le `.onnx`
est figé à `1×3×640×640` : sa grille d'ancres est une constante de l'export, donc
ni la résolution ni la taille du lot ne sont négociables (mesuré : toute autre
forme fait échouer le `Reshape` du DFL). Empaqueter plusieurs recadrages dans une
seule image est donc la seule façon d'amortir l'inférence.

L'intuition « un recadrage de 200 px agrandi à 640 ne gagne rien, donc
l'empaqueter ne coûte rien » est **fausse**, et c'est la mesure qui le dit. Ce qui
décide qu'une plaque est trouvée n'est pas le facteur d'agrandissement mais la
taille de la plaque **dans l'entrée du réseau** — et elle ne dépend que de la
cellule, pas du recadrage :

    plaque_dans_le_réseau ≈ 0,15 × côté_de_cellule

Sur 657 véhicules à 8,2 véhicules par image : côté 1 (cellule 616 px) 760 ms et
100 % de rappel ; côté 2 (302 px) 221 ms et 84 % ; côté 3 (197 px) 116 ms et
56 %. Le défaut est donc **1** : on ne troque pas de la justesse contre du débit
sans que quelqu'un le demande. `TRAFFIC_PLATE_MOSAIC_SIDE=2` est l'échange
raisonnable quand le débit prime.

La gouttière n'est pas cosmétique : sans elle, le champ récepteur du réseau
déborde d'une cellule sur l'autre et fabrique des détections à cheval sur deux
véhicules.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from traffic_analysis.core.logging import get_logger

# Le filtre géométrique vient du **domaine**, par le contrat publié de `counting`
# — comme `BoundingBox`. Il vivait ici, donc derrière `ultralytics`, donc hors de
# portée de la CI : aucun test ne pouvait prouver qu'une boîte « véhicule entier »
# n'atteint pas l'OCR. C'est maintenant vérifiable sur des tuples.
from traffic_analysis.features.counting.application.dto import (
    BoundingBox,
    PlateDetection,
    PlateGeometry,
    is_plausible,
    select_best,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import numpy.typing as npt

logger = get_logger("traffic_analysis.anpr")

# En dessous, le recadrage ne contient pas assez de pixels pour qu'une plaque
# soit distinguable : l'inférence coûterait sans jamais rien trouver.
MIN_CROP_SIDE_PX = 32

#: Côté de l'entrée du réseau. **Constante de l'export, pas un réglage** : la
#: grille d'ancres `8400` est gravée dans le graphe.
NET_SIZE = 640

#: Gouttière entre deux cellules de la mosaïque. 12 px à 640, soit un peu plus que
#: la foulée maximale du réseau (32) ramenée à l'échelle d'une cellule : assez pour
#: que deux véhicules voisins ne partagent aucun champ récepteur utile.
MOSAIC_GUTTER_PX = 12

#: Valeur de remplissage des gouttières et des marges de cellule. 114 est le gris
#: neutre du letterbox d'Ultralytics : le réseau l'a vu à chaque image de son
#: entraînement, il ne l'interprète pas comme un objet.
PAD_VALUE = 114

#: Plafond de la grille. 3×3 donne des cellules de ~197 px, soit une plaque d'une
#: trentaine de pixels dans l'entrée du réseau : la limite basse de ce qu'un YOLO
#: détecte. Au-delà, on ne détecterait plus rien.
MAX_MOSAIC_SIDE = 3

#: Défaut : **pas d'empaquetage**. Voir la docstring du module — la mosaïque échange
#: du rappel contre de la vitesse, et ce n'est pas à l'adaptateur de faire cet
#: arbitrage tout seul.
DEFAULT_MOSAIC_SIDE = 1


@dataclass(frozen=True, slots=True)
class _Placement:
    """Où un recadrage a atterri dans la mosaïque, et comment revenir en arrière."""

    index: int
    origin_x: int
    origin_y: int
    crop_width: int
    crop_height: int
    offset_x: int
    offset_y: int
    placed_width: int
    placed_height: int
    scale: float


class OnnxPlateDetector:
    """Détecteur de plaques ONNX, chargé **paresseusement**.

    Paresseusement parce que l'absence du fichier ne doit pas empêcher le service
    de démarrer : l'option ANPR est alors signalée indisponible dans `/health` et
    désactivée dans l'interface, et tout le reste fonctionne.
    """

    __slots__ = (
        "_checked",
        "_confidence",
        "_geometry",
        "_iou",
        "_lock",
        "_model",
        "_mosaic_side",
        "_path",
    )

    def __init__(
        self,
        model_path: Path,
        confidence: float,
        *,
        iou: float = 0.45,
        mosaic_side: int = DEFAULT_MOSAIC_SIDE,
        geometry: PlateGeometry | None = None,
    ) -> None:
        self._path = model_path
        self._confidence = confidence
        self._iou = iou
        self._mosaic_side = max(1, min(MAX_MOSAIC_SIDE, mosaic_side))
        self._geometry = geometry or PlateGeometry()
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

    def detect(
        self, image: npt.NDArray[np.uint8], box: BoundingBox, confidence: float | None = None
    ) -> tuple[PlateDetection, ...]:
        """Cherche une plaque dans `box`, en coordonnées de l'image **complète**.

        Ne lève **jamais** : une passe ANPR ratée rend une liste vide et
        journalise. Un comptage ne doit pas échouer parce qu'une plaque était
        illisible — c'est une option, pas le cœur du travail.
        """
        return self.detect_many(image, (box,), confidence)[0]

    def detect_many(
        self,
        image: npt.NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
        confidence: float | None = None,
    ) -> tuple[tuple[PlateDetection, ...], ...]:
        """Cherche une plaque dans **chaque** boîte, en une poignée d'inférences.

        Rend exactement un tuple par boîte, dans le même ordre : c'est l'appelant
        qui sait à quelle piste appartient quel recadrage, et lui rendre une liste
        plus courte l'obligerait à deviner. Même contrat d'alignement positionnel
        que `PlateReader.read`, et pour la même raison.

        Ne lève **jamais**.
        """
        if not boxes:
            return ()
        empty: tuple[PlateDetection, ...] = ()
        results: list[tuple[PlateDetection, ...]] = [empty] * len(boxes)
        try:
            model = self._ensure_loaded()
            if model is None:
                return tuple(results)

            crops: list[tuple[int, npt.NDArray[np.uint8], int, int]] = []
            for index, box in enumerate(boxes):
                crop, origin_x, origin_y = self._crop(image, box)
                if crop is not None:
                    crops.append((index, crop, origin_x, origin_y))
            if not crops:
                return tuple(results)

            threshold = self._confidence if confidence is None else confidence
            side = self._mosaic_side
            # `side²` recadrages par inférence. Une grille plus petite que le nombre
            # de recadrages en attente serait du gaspillage, une plus grande
            # rétrécirait les cellules sans rien empaqueter de plus.
            per_tile = side * side
            for start in range(0, len(crops), per_tile):
                chunk = crops[start : start + per_tile]
                for index, found in self._infer_tile(model, chunk, threshold).items():
                    results[index] = found
            return tuple(results)
        except Exception as exc:
            logger.warning("passe ANPR en échec", error=str(exc))
            return tuple(results)

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

    def _infer_tile(
        self,
        model: Any,  # noqa: ANN401 — YOLO n'est pas typé
        chunk: Sequence[tuple[int, npt.NDArray[np.uint8], int, int]],
        threshold: float,
    ) -> dict[int, tuple[PlateDetection, ...]]:
        """Une inférence pour tout un paquet de recadrages."""
        tile, placements = self._pack(chunk)
        # `imgsz` explicite : sans lui, Ultralytics choisit sa valeur par défaut, et
        # une mosaïque redimensionnée casserait la correspondance des cellules.
        # `iou` et `max_det` explicites aussi : les défauts (0,7 et 300) sont
        # calibrés pour une scène COCO, pas pour une classe unique.
        results = model.predict(
            tile,
            conf=threshold,
            iou=self._iou,
            imgsz=NET_SIZE,
            max_det=len(placements) * 8,
            verbose=False,
        )
        if not results:
            return {}
        boxes = getattr(results[0], "boxes", None)
        if boxes is None or len(boxes) == 0:
            return {}

        found: dict[int, list[tuple[_Placement, BoundingBox, float]]] = {}
        for raw, score in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), strict=True):
            x1, y1, x2, y2 = (float(value) for value in raw)
            placement = self._locate(placements, (x1 + x2) / 2.0, (y1 + y2) / 2.0)
            if placement is None:
                # Une boîte tombée dans une gouttière n'appartient à personne.
                continue
            in_crop = self._to_crop(placement, x1, y1, x2, y2)
            if in_crop is not None and self._is_plausible(in_crop, placement):
                found.setdefault(placement.index, []).append((placement, in_crop, float(score)))

        return {index: self._select(candidates) for index, candidates in found.items()}

    def _pack(
        self, chunk: Sequence[tuple[int, npt.NDArray[np.uint8], int, int]]
    ) -> tuple[npt.NDArray[np.uint8], list[_Placement]]:
        """Range les recadrages dans une image 640×640 et note comment en revenir.

        Grille carrée la plus petite qui contienne le paquet : à deux recadrages on
        utilise 2×2 (cellules de 308 px), pas 3×3. Chaque cellule reçoit son
        recadrage **en préservant le rapport d'aspect** et ancré en haut à gauche —
        un centrage ne changerait rien au résultat et ajouterait un terme de plus à
        se tromper dans le calcul retour.
        """
        side = 1
        while side * side < len(chunk):
            side += 1
        cell = (NET_SIZE - (side + 1) * MOSAIC_GUTTER_PX) // side

        tile = np.full((NET_SIZE, NET_SIZE, 3), PAD_VALUE, dtype=np.uint8)
        placements: list[_Placement] = []
        for position, (index, crop, origin_x, origin_y) in enumerate(chunk):
            row, column = divmod(position, side)
            offset_x = MOSAIC_GUTTER_PX + column * (cell + MOSAIC_GUTTER_PX)
            offset_y = MOSAIC_GUTTER_PX + row * (cell + MOSAIC_GUTTER_PX)

            height, width = crop.shape[:2]
            scale = min(cell / width, cell / height)
            placed_width = max(1, round(width * scale))
            placed_height = max(1, round(height * scale))
            # INTER_AREA quand on réduit, INTER_LINEAR quand on agrandit : réduire
            # au plus proche voisin ferait disparaître un caractère sur deux.
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            tile[offset_y : offset_y + placed_height, offset_x : offset_x + placed_width] = (
                cv2.resize(crop, (placed_width, placed_height), interpolation=interpolation)
            )
            placements.append(
                _Placement(
                    index=index,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    crop_width=width,
                    crop_height=height,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    placed_width=placed_width,
                    placed_height=placed_height,
                    scale=scale,
                )
            )
        return tile, placements

    @staticmethod
    def _locate(placements: Sequence[_Placement], x: float, y: float) -> _Placement | None:
        """À quelle cellule appartient une boîte ? Par son **centre**.

        Par le centre et non par un chevauchement : une boîte qui déborde légèrement
        de sa cellule appartient quand même au véhicule dont le centre la désigne,
        et un critère de chevauchement pourrait l'attribuer à deux cellules.
        """
        for placement in placements:
            if (
                placement.offset_x <= x <= placement.offset_x + placement.placed_width
                and placement.offset_y <= y <= placement.offset_y + placement.placed_height
            ):
                return placement
        return None

    @staticmethod
    def _to_crop(
        placement: _Placement, x1: float, y1: float, x2: float, y2: float
    ) -> BoundingBox | None:
        """Une boîte de la mosaïque → une boîte du **recadrage**, découpée à ses bornes.

        On s'arrête au repère du recadrage, sans aller jusqu'à l'image complète :
        c'est dans ce repère que le filtre de plausibilité compare la plaque au
        véhicule qui la porte. Faire la conversion finale d'abord obligerait à
        soustraire l'origine pour comparer, c'est-à-dire à écrire deux fois le
        même changement de repère — et une seule des deux serait relue.

        Le découpage aux bornes garantit qu'une boîte débordant dans la gouttière
        ne rend pas des coordonnées hors du véhicule.
        """
        scale = placement.scale
        left = max(0.0, min((x1 - placement.offset_x) / scale, float(placement.crop_width)))
        right = max(0.0, min((x2 - placement.offset_x) / scale, float(placement.crop_width)))
        top = max(0.0, min((y1 - placement.offset_y) / scale, float(placement.crop_height)))
        bottom = max(0.0, min((y2 - placement.offset_y) / scale, float(placement.crop_height)))
        if right - left <= 0.0 or bottom - top <= 0.0:
            return None
        return BoundingBox(x=left, y=top, width=right - left, height=bottom - top)

    def _is_plausible(self, box: BoundingBox, placement: _Placement) -> bool:
        """La boîte peut-elle être la plaque de **ce** véhicule ?

        Délègue au domaine : la décision est une règle de géométrie, pas une
        affaire d'ONNX, et ici elle serait hors de portée de la CI.
        """
        return is_plausible(
            box,
            float(placement.crop_width),
            float(placement.crop_height),
            self._geometry,
        )

    def _select(
        self, candidates: Sequence[tuple[_Placement, BoundingBox, float]]
    ) -> tuple[PlateDetection, ...]:
        """Les `max_per_vehicle` meilleures, réexprimées dans l'image complète.

        Aucune couche en aval ne doit avoir à savoir qu'il y a eu un recadrage :
        le classement se fait dans le domaine, la remise en repère ici.
        """
        # Les candidates d'un même véhicule partagent leur placement — c'est la
        # cellule de *ce* recadrage. Le prendre une fois évite d'avoir à réapparier
        # une boîte à son placement après le tri du domaine.
        placement = candidates[0][0]
        best = select_best([(box, score) for _, box, score in candidates], self._geometry)
        return tuple(
            PlateDetection(
                box=BoundingBox(
                    x=box.x + placement.origin_x,
                    y=box.y + placement.origin_y,
                    width=box.width,
                    height=box.height,
                ),
                score=score,
            )
            for box, score in best
        )
