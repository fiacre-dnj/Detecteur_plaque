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

**Pourquoi une mosaïque, et pourquoi elle est désactivée par défaut.** Elle est née
d'une contrainte qui n'existe plus : l'export `.onnx` d'origine était figé à
`1×3×640×640`, sa grille d'ancres gravée dans le graphe, donc ni la résolution ni la
taille du lot n'étaient négociables — empaqueter plusieurs recadrages dans une seule
image était la seule façon d'amortir l'inférence. Depuis le passage en `.pt`
([ADR 0015](../../../../../docs/adr/0015-le-detecteur-de-plaques-en-pt.md)), le lot
et la résolution sont libres : `predict()` accepte une liste de recadrages et les
traite en un seul appel, ce qui amortit mieux **et** sans rien perdre.

**Cette phrase a longtemps décrit une intention et non le code.** `detect_many`
découpait bien le travail en paquets de `side²` recadrages — mais avec le défaut
`side = 1`, cela faisait *un paquet par véhicule*, donc un `predict` par véhicule.
Le coût fixe d'un appel était payé autant de fois qu'il y avait de pistes.
`_infer_batch` est le chemin annoncé, enfin écrit : mesuré sur vidéo réelle à 3,7
véhicules par image, **217 ms → 107 ms par image, soit ~2×** (1,80 à 2,10 selon la
passe). Le lot y est une dimension de **tenseur** — chaque recadrage garde son
letterbox 640×640 — et non un empaquetage en pixels : rien n'est troqué contre du
rappel, contrairement à la mosaïque ci-dessous.

**Les boîtes ne sont pas identiques au bit près, et il faut savoir pourquoi.**
Mesuré sur 240 véhicules : **aucune plaque gagnée ni perdue** — même nombre de
détections sur 240/240 — mais une IoU de 0,943 au minimum, 0,959 en médiane, entre
la boîte d'avant et celle d'après. L'écart est sub-pixel et il a une cause précise :
l'ancien chemin passait par `_pack`, donc par un redimensionnement du recadrage vers
sa cellule, **avant** le letterbox d'Ultralytics. Le lot n'a plus que le letterbox.
C'est un rééchantillonnage de moins, donc la boîte du lot est la plus fidèle des
deux — mais une comparaison au pixel près entre deux versions du dépôt échouera, et
c'est attendu.

La mosaïque reste néanmoins ici, inchangée et désactivée par défaut, parce
que son arbitrage a été mesuré et qu'il garde sa valeur sur une machine sans GPU.
L'intuition « un recadrage de 200 px agrandi à 640 ne gagne rien, donc l'empaqueter
ne coûte rien » est **fausse**, et c'est la mesure qui le dit.

Ce qui décide qu'une plaque est trouvée n'est pas le facteur d'agrandissement mais la
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
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import numpy.typing as npt

logger = get_logger("traffic_analysis.anpr")

# En dessous, le recadrage ne contient pas assez de pixels pour qu'une plaque
# soit distinguable : l'inférence coûterait sans jamais rien trouver.
MIN_CROP_SIDE_PX = 32

#: Côté de l'entrée du réseau.
#:
#: C'était une **constante de l'export** au temps du `.onnx` — la grille d'ancres
#: `8400` était gravée dans le graphe, et toute autre forme faisait échouer le
#: `Reshape` du DFL. Depuis le `.pt` (ADR 0015) c'est un choix, gardé à 640 parce
#: que c'est la résolution d'entraînement du modèle : monter plus haut interpole des
#: pixels que le réseau n'a jamais vus à cette échelle, et cela se mesure au banc
#: avant de se décider.
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

#: Recadrages par appel à `predict` sur le chemin par défaut (`_infer_batch`).
#:
#: Le lot est une dimension de **tenseur**, pas de pixels : chaque recadrage garde son
#: propre letterbox 640×640, donc `N` recadrages occupent `N×3×640×640` flottants, soit
#: ~4,9 Mo par recadrage. 16 tient largement dans les 4 Go de la carte de cette machine
#: tout en amortissant le coût fixe d'un `predict` sur les scènes ordinaires — au-delà,
#: une intersection chargée pourrait faire déborder une carte plus petite, et une
#: erreur de mémoire GPU ferait échouer *toute* la passe ANPR d'une image.
MAX_BATCH = 16


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


class UltralyticsPlateDetector:
    """Détecteur de plaques chargé par Ultralytics, **paresseusement**.

    Paresseusement parce que l'absence du fichier ne doit pas empêcher le service
    de démarrer : l'option ANPR est alors signalée indisponible dans `/health` et
    désactivée dans l'interface, et tout le reste fonctionne.

    **Le nom ne dit plus un format, et c'est voulu.** La classe s'appelait
    `OnnxPlateDetector` ; elle n'a jamais fait que passer son chemin à
    `YOLO(path, task="detect")`, qui accepte indifféremment un `.pt` et un `.onnx`.
    Le format est maintenant un `.pt` (ADR 0015), et un nom qui affirme un format
    que la classe n'impose pas est un nom qui finira par mentir.
    """

    __slots__ = (
        "_checked",
        "_confidence",
        "_device",
        "_device_provider",
        "_geometry",
        "_half",
        "_half_provider",
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
        device_provider: Callable[[], str] | None = None,
        half_provider: Callable[[], bool] | None = None,
    ) -> None:
        """`device_provider` et `half_provider` **délèguent au registre**.

        Deux appelables et non deux valeurs, parce que le registre ne décide de son
        device qu'au premier besoin : il sonde le GPU, lit sa capacité de calcul et
        peut retomber sur le CPU. Copier sa décision à la construction du conteneur
        la figerait avant qu'elle soit prise.

        Et deux appelables **du registre** plutôt qu'une détection propre à cet
        adaptateur, parce qu'il n'y a qu'une bonne réponse par machine : c'est le
        registre qui applique la règle « fp16 seulement à partir de Volta »
        d'ADR 0012 — sur une carte Pascal le fp16 est *plus lent* que le fp32,
        38,9 ms contre 48,9 mesurées. Deux détections indépendantes finiraient par
        se contredire, et celle du détecteur de plaques serait la moins testée.

        `None` laisse Ultralytics choisir seul, ce qui est le comportement d'avant
        ADR 0015 : les doublures de test n'ont pas à connaître un registre.
        """
        self._path = model_path
        self._confidence = confidence
        self._iou = iou
        self._mosaic_side = max(1, min(MAX_MOSAIC_SIDE, mosaic_side))
        self._geometry = geometry or PlateGeometry()
        self._model: Any = None
        self._checked = False
        self._lock = threading.Lock()
        self._device_provider = device_provider
        self._half_provider = half_provider
        self._device: str | None = None
        self._half = False

    @property
    def available(self) -> bool:
        """Le fichier de poids est-il présent ?

        Une vérification de présence et non de chargement : charger pour répondre
        à `/health` prendrait des secondes à chaque appel, alors que l'interface
        interroge cette route en permanence.

        **Ce que ce drapeau ne dit pas**, et qui a coûté cher ici : rien sur la
        lisibilité du fichier. Un poids corrompu, tronqué, ou d'un format que le
        suffixe contredit passe ce test et rend `available: true`, puis échoue au
        chargement — donc zéro plaque à chaque image, avec un drapeau vert.
        `probe()` répond à l'autre question, une fois, au démarrage.
        """
        return self._path.is_file()

    def _runtime_kwargs(self) -> dict[str, Any]:
        """Arguments de `predict` qui décrivent le matériel, pas la tâche.

        Omis quand aucun fournisseur n'a été injecté : passer `device=None`
        explicitement n'est pas neutre côté Ultralytics.
        """
        kwargs: dict[str, Any] = {}
        if self._device is not None:
            kwargs["device"] = self._device
            kwargs["half"] = self._half
        return kwargs

    def probe(self) -> bool:
        """Charge le modèle et lance **une** inférence. Ne lève jamais.

        L'auto-test que `available` ne peut pas faire. Il existe parce que ce projet
        a payé trois fois le même mode de panne — un `.env` commenté, un
        dictionnaire d'OCR décalé d'un cran, un suffixe qui trompe le choix de
        backend : à chaque fois un drapeau vert, un pipeline muet, et aucun message
        qui mentionne la cause. Une inférence sur une image de synthèse au démarrage
        transforme les trois en une ligne de journal.

        Rend `True` si le modèle est chargé **et** inférable. Le résultat de la
        détection n'a aucune importance : une image noire ne contient aucune plaque,
        et c'est très bien — ce qu'on teste est le chemin, pas la justesse.
        """
        if not self.available:
            return False
        try:
            model = self._ensure_loaded()
            if model is None:
                return False
            probe_image = np.zeros((NET_SIZE, NET_SIZE, 3), dtype=np.uint8)
            model.predict(
                probe_image,
                conf=self._confidence,
                iou=self._iou,
                imgsz=NET_SIZE,
                max_det=1,
                verbose=False,
                **self._runtime_kwargs(),
            )
        except Exception as exc:
            logger.error(
                "modèle de plaques présent mais inutilisable — ANPR indisponible",
                path=str(self._path),
                error=str(exc),
            )
            return False
        logger.info("auto-test du détecteur de plaques réussi", path=str(self._path))
        return True

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
            if side == 1:
                # Le chemin par défaut : **un lot**, pas une inférence par véhicule.
                for start in range(0, len(crops), MAX_BATCH):
                    chunk = crops[start : start + MAX_BATCH]
                    for index, found in self._infer_batch(model, chunk, threshold, image).items():
                        results[index] = found
                return tuple(results)

            # `side²` recadrages par inférence. Une grille plus petite que le nombre
            # de recadrages en attente serait du gaspillage, une plus grande
            # rétrécirait les cellules sans rien empaqueter de plus.
            per_tile = side * side
            for start in range(0, len(crops), per_tile):
                chunk = crops[start : start + per_tile]
                for index, found in self._infer_tile(model, chunk, threshold, image).items():
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

            # Le device est résolu **ici** et non à la construction : le registre ne
            # sonde le GPU qu'au premier besoin, et le sonder plus tôt aurait figé sa
            # décision avant qu'elle soit prise.
            if self._device_provider is not None:
                self._device = self._device_provider()
            if self._half_provider is not None:
                self._half = self._half_provider()

            self._model = YOLO(str(self._path), task="detect")
            logger.info(
                "modèle de plaques chargé",
                path=str(self._path),
                device=self._device or "auto",
                half=self._half,
            )
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

    def _infer_batch(
        self,
        model: Any,  # noqa: ANN401 — YOLO n'est pas typé
        chunk: Sequence[tuple[int, npt.NDArray[np.uint8], int, int]],
        threshold: float,
        image: npt.NDArray[np.uint8],
    ) -> dict[int, tuple[PlateDetection, ...]]:
        """Une inférence pour **tous** les recadrages du paquet, sans mosaïque.

        **C'est le chemin par défaut depuis qu'il est mesuré**, et il remplace une
        boucle qui appelait `predict` une fois par véhicule. La docstring du module
        annonçait déjà qu'un `.pt` accepte une liste et la traite en un seul appel ;
        le code, lui, empaquetait un seul recadrage par mosaïque et rappelait le
        modèle pour le suivant. Mesuré sur vidéo réelle, 3,7 véhicules par image :
        **217 ms → 107 ms par image, soit 2,04×**, sans qu'aucune boîte change — le
        coût fixe d'un `predict` (préparation, transfert, synchronisation) était payé
        autant de fois qu'il y avait de véhicules.

        **Rien à voir avec la mosaïque, et c'est l'intérêt.** Elle empaquette
        plusieurs recadrages dans *une image* et paie donc une perte de résolution
        (ADR 0008 : côté 2, 3,4× pour −16 % de rappel). Ici chaque recadrage garde son
        propre letterbox 640×640 : le lot est une dimension de **tenseur**, pas de
        pixels. Le rappel est identique à celui du chemin séquentiel, boîte pour
        boîte.

        Ultralytics rend un résultat par image d'entrée, **dans l'ordre d'entrée**, et
        ses boîtes sont déjà exprimées dans le repère de *cette* image — donc dans
        celui du recadrage. Le placement construit ici est neutre (`scale=1`, décalages
        nuls) : il ne sert qu'à porter l'origine du recadrage jusqu'à `_select`, ce qui
        laisse le filtre de plausibilité, le classement du domaine et la mesure de
        netteté **partagés** avec le chemin mosaïque plutôt que réécrits.
        """
        placements = [
            _Placement(
                index=index,
                origin_x=origin_x,
                origin_y=origin_y,
                crop_width=crop.shape[1],
                crop_height=crop.shape[0],
                offset_x=0,
                offset_y=0,
                placed_width=crop.shape[1],
                placed_height=crop.shape[0],
                scale=1.0,
            )
            for index, crop, origin_x, origin_y in chunk
        ]
        # `max_det` par **image** ici, là où la mosaïque le compte pour toute la
        # grille : les deux chemins ne comptent pas la même chose.
        results = model.predict(
            [crop for _, crop, _, _ in chunk],
            conf=threshold,
            iou=self._iou,
            imgsz=NET_SIZE,
            max_det=8,
            verbose=False,
            **self._runtime_kwargs(),
        )

        found: dict[int, list[tuple[_Placement, BoundingBox, float]]] = {}
        for placement, result in zip(placements, results, strict=True):
            boxes = getattr(result, "boxes", None)
            if boxes is None or len(boxes) == 0:
                continue
            for raw, score in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), strict=True):
                x1, y1, x2, y2 = (float(value) for value in raw)
                in_crop = BoundingBox(x=x1, y=y1, width=x2 - x1, height=y2 - y1)
                if in_crop.width <= 0.0 or in_crop.height <= 0.0:
                    continue
                if self._is_plausible(in_crop, placement):
                    found.setdefault(placement.index, []).append((placement, in_crop, float(score)))

        return {index: self._select(candidates, image) for index, candidates in found.items()}

    def _infer_tile(
        self,
        model: Any,  # noqa: ANN401 — YOLO n'est pas typé
        chunk: Sequence[tuple[int, npt.NDArray[np.uint8], int, int]],
        threshold: float,
        image: npt.NDArray[np.uint8],
    ) -> dict[int, tuple[PlateDetection, ...]]:
        """Une inférence pour tout un paquet de recadrages.

        `image` est l'image **source complète** : elle sert à mesurer la netteté de
        chaque vignette retenue, sur les pixels d'origine plutôt que sur ceux de la
        mosaïque, où la vignette a déjà été redimensionnée.
        """
        tile, placements = self._pack(chunk)
        # `imgsz` explicite : sans lui, Ultralytics choisit sa valeur par défaut, et
        # une mosaïque redimensionnée casserait la correspondance des cellules.
        # `iou` et `max_det` explicites aussi : les défauts (0,7 et 300) sont
        # calibrés pour une scène COCO, pas pour une classe unique.
        # `device` et `half` explicites : sans eux, Ultralytics refait sa propre
        # détection de matériel par modèle, et le détecteur de plaques pouvait
        # atterrir ailleurs que le détecteur de véhicules sur la même machine.
        results = model.predict(
            tile,
            conf=threshold,
            iou=self._iou,
            imgsz=NET_SIZE,
            max_det=len(placements) * 8,
            verbose=False,
            **self._runtime_kwargs(),
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

        return {index: self._select(candidates, image) for index, candidates in found.items()}

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
        self,
        candidates: Sequence[tuple[_Placement, BoundingBox, float]],
        image: npt.NDArray[np.uint8],
    ) -> tuple[PlateDetection, ...]:
        """Les `max_per_vehicle` meilleures, réexprimées dans l'image complète.

        Aucune couche en aval ne doit avoir à savoir qu'il y a eu un recadrage :
        le classement se fait dans le domaine, la remise en repère ici.

        La **netteté** est mesurée ici parce que c'est la seule couche qui ait à la
        fois les pixels et le droit d'importer `cv2` : `test_architecture.py`
        l'interdit dans `application` et dans `domain`. Elle est mesurée sur
        l'image source et non sur la mosaïque, où la vignette a déjà été
        redimensionnée — une netteté mesurée après interpolation décrirait
        l'interpolation, pas la prise de vue.
        """
        # Les candidates d'un même véhicule partagent leur placement — c'est la
        # cellule de *ce* recadrage. Le prendre une fois évite d'avoir à réapparier
        # une boîte à son placement après le tri du domaine.
        placement = candidates[0][0]
        best = select_best([(box, score) for _, box, score in candidates], self._geometry)
        detections: list[PlateDetection] = []
        for box, score in best:
            absolute = BoundingBox(
                x=box.x + placement.origin_x,
                y=box.y + placement.origin_y,
                width=box.width,
                height=box.height,
            )
            detections.append(
                PlateDetection(
                    box=absolute,
                    score=score,
                    sharpness=self._sharpness(image, absolute),
                )
            )
        return tuple(detections)

    @staticmethod
    def _sharpness(image: npt.NDArray[np.uint8], box: BoundingBox) -> float:
        """Variance du laplacien de la vignette — la mesure de flou usuelle.

        Coût : quelques microsecondes sur une vignette de 60×20, contre 93 ms
        d'inférence. Ne lève jamais : une vignette hors cadre ou dégénérée rend
        `0.0`, que la politique interprète comme « non mesurée » et non comme
        « parfaitement floue » — elle retombe alors sur la largeur seule.
        """
        height, width = image.shape[:2]
        x1 = max(0, int(box.x))
        y1 = max(0, int(box.y))
        x2 = min(width, int(box.x + box.width))
        y2 = min(height, int(box.y + box.height))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return 0.0
        crop = image[y1:y2, x1:x2]
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        return float(cv2.Laplacian(grey, cv2.CV_64F).var())
