"""Lecture des caractères d'une plaque, en troisième étage de l'ANPR.

Trois étages et non deux : le modèle plein cadre ne voit pas la plaque, le détecteur
de plaques ne lit pas les caractères. Chaque étage recadre plus près.

**Le coût est modeste, et c'est le point.** La détection de plaques domine le temps
d'une frame (`plate_detector.py`), la lecture quelques dizaines de millisecondes pour
tout un lot. L'OCR n'est pas le goulot ; `plate_policy.py` existe donc surtout
pour protéger la **justesse** du vote — ne pas voter quarante fois sur le même
recadrage figé — plutôt que la cadence. C'est aussi ce qui autorise à dépenser
plusieurs *variantes* de prétraitement par plaque : trois fois presque rien reste
presque rien, et une plaque penchée ne se lit pas autrement.

**`onnxruntime` n'est jamais importé au niveau module**, exactement comme
`plate_detector.py` importe `YOLO` dans `_ensure_loaded`. Ce n'est pas un détail de
style : c'est ce qui permet de tester toutes les fonctions pures de ce fichier sans
charger onnxruntime, donc sans subir ses avertissements sous
`filterwarnings = ["error"]`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import BoundingBox, PlateText

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import numpy.typing as npt

logger = get_logger("traffic_analysis.anpr")

#: Sous cette largeur de vignette, il n'y a pas assez de pixels par caractère pour
#: qu'une lecture veuille dire quoi que ce soit : ~4 px par glyphe.
MIN_PLATE_WIDTH_PX = 32
#: Une plaque plus plate que cela est une bande de calandre, pas une plaque.
MIN_PLATE_HEIGHT_PX = 8

#: En dessous, on suréchantillonne **avant** le redimensionnement final. 120 px parce
#: que la cible fait 320 px de large : un recadrage de 60 px poussé directement à 320
#: subit un facteur 5,3 en une seule interpolation, qui étale les jambages. Un CUBIC
#: intermédiaire à facteur modéré, puis le redimensionnement final, conserve des
#: traits nets.
UPSCALE_MIN_WIDTH_PX = 120
#: Plafonné : au-delà il n'y a plus d'information à interpoler, seulement du flou
#: qu'on affirme.
MAX_UPSCALE = 4.0

#: CLAHE et non égalisation globale : une plaque à moitié à l'ombre — une voiture sous
#: un pont — a un histogramme bimodal, et l'égalisation globale brûle la moitié
#: éclairée. 2,0 est la valeur conservatrice usuelle ; plus haut, le bruit du capteur
#: devient des jambages qui n'existent pas.
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID = (8, 8)

#: Hauteur d'entrée de la tête de reconnaissance PP-OCR. **Celle-là est fixe** : le
#: modèle a été entraîné à 48 px de haut, et c'est la dimension qui fixe l'échelle
#: des glyphes.
REC_HEIGHT = 48
#: Largeur de référence de PP-OCR, et **plafond par défaut**.
REC_MAX_WIDTH = 320
#: Plafond dur quand la largeur est négociée avec le modèle. Une plaque plus large
#: que 6,7:1 — un bandeau américain, deux plaques collées — était jusqu'ici comprimée
#: à 320 px, ce qui écrase les glyphes ; le graphe accepte plus large, on le lui donne.
REC_HARD_MAX_WIDTH = 640
#: Largeur minimale d'un tenseur. Sous ~13 pas de temps, le CTC ne peut pas coder
#: sept caractères (il lui faut un blanc entre deux répétitions).
REC_MIN_WIDTH = 64
#: Les largeurs sont arrondies à ce multiple : quelques formes distinctes plutôt
#: qu'une par lot, ce qui laisse onnxruntime réutiliser ses plans d'exécution.
REC_WIDTH_QUANTUM = 32

#: PP-OCR normalise avec 0,5/0,5 par canal, **pas** avec les valeurs ImageNet. Se
#: tromper ici est la deuxième cause la plus fréquente de « le modèle tourne et rend
#: du charabia » — la première étant l'étirement au lieu du remplissage.
REC_MEAN = 0.5
REC_STD = 0.5

#: Sous cet angle, redresser ne gagne rien et coûte une interpolation qui adoucit les
#: traits. Au-dessus, ce n'est plus une plaque penchée mais une estimation d'angle qui
#: s'est accrochée à autre chose — une ombre, un bord de carrosserie.
MIN_SKEW_DEG = 1.5
MAX_SKEW_DEG = 25.0

#: Fractions rognées par la variante « encart ». Le détecteur cadre volontiers le
#: **cadre** de la plaque — la bordure peinte, les vis, le liseré européen bleu — et
#: ces pixels-là entrent dans les pas de temps du CTC comme s'ils étaient des glyphes.
INSET_VERTICAL = 0.08
INSET_HORIZONTAL = 0.03

#: Fractions rognées **à gauche seulement**, chacune donnant une variante de plus.
#:
#: **C'est la variante la plus payante de tout le dispositif, et sa raison est mesurée.**
#: Le modèle est `en_PP-OCRv3_rec` : son alphabet est l'ASCII imprimable, et rien
#: d'autre. Une plaque dont le premier caractère n'appartient pas à cet alphabet — un
#: idéogramme de province chinois, un blason régional — ne se lit pas « en moins » :
#: le CTC doit bien émettre quelque chose pour ces pas de temps, et ce quelque chose
#: **contamine le caractère voisin**. Mesuré sur 40 vignettes de vraie circulation
#: (`苏A·96886`, `苏A·R606L`, …) : la chaîne rendait `96886` et `R606L`, c'est-à-dire
#: la plaque **moins sa première lettre**, avec une confiance de 0,90 qui ne
#: signalait rien. Le même recadrage privé de son bord gauche rend `A96886` à 0,97.
#:
#: Deux fractions et non une, parce que la largeur de la cellule à retirer dépend du
#: nombre de caractères de la plaque, que l'on ne connaît pas : 0,14 ≈ une cellule
#: d'une plaque à sept cases, 0,22 ≈ une cellule d'une plaque courte. C'est le
#: décodage qui départage, à confiance cumulée, comme pour toutes les variantes.
#:
#: **Les valeurs ne sont pas le maximum d'un balayage**, délibérément : sur ce corpus
#: `(0,16 ; 0,22)` publiait une plaque juste de plus, et `(0,16 ; 0,24)` la reperdait.
#: Un point de pourcentage qui fait basculer un résultat sur six plaques est du
#: surajustement, pas une mesure. `(0,14 ; 0,22)` est au milieu de la zone plate
#: (14–22 % rendent tous 2 à 4 plaques justes sur 6, contre 1 sans rognage) **et**
#: le meilleur sur le contrôle indépendant — l'échelle de vérité terrain synthétique,
#: qui n'a aucun idéogramme, passe de 40 à 43 lectures justes sur 56.
#:
#: **Rien n'est retiré au cas latin.** Sur une plaque française, rogner 14 % coupe le
#: premier caractère, la variante rend une chaîne plus courte, et la confiance
#: cumulée la fait perdre. Une variante ne peut que gagner ou être ignorée.
LEFT_INSET_FRACTIONS: tuple[float, ...] = (0.14, 0.22)

#: Sous cette largeur, une variante rognée n'a plus assez de colonnes pour valoir
#: une inférence : on ne la construit pas.
MIN_VARIANT_WIDTH_PX = 32


@dataclass(frozen=True, slots=True)
class Reading:
    """Une sortie de décodage CTC, avec le détail que le vote consommera.

    `char_scores` et non seulement `score` : le consensus par caractère de
    `plate_vote.py` a besoin de savoir **quel caractère** hésitait. Une moyenne dit
    qu'une lecture était moyenne, elle ne dit pas où.
    """

    text: str
    score: float
    char_scores: tuple[float, ...]

    @property
    def total(self) -> float:
        """Confiance **cumulée**, critère de choix entre variantes de prétraitement.

        Cumulée et non moyenne, délibérément : entre une lecture de trois caractères
        à 0,99 et une de sept à 0,85, la moyenne préfère la première alors qu'elle a
        manqué quatre glyphes. La somme (2,97 contre 5,95) préfère celle qui a lu
        le plus, aussi sûrement — ce qu'on veut, sans avoir à inventer un facteur de
        longueur.
        """
        return float(sum(self.char_scores))


def _as_u8(array: Any) -> npt.NDArray[np.uint8]:  # noqa: ANN401 — les stubs de cv2 élargissent
    """Rétrécit le dtype qu'`cv2` élargit dans ses stubs.

    `asarray` et non `astype` : sur un tableau déjà en `uint8` — ce que rendent
    toujours les opérations d'ici — c'est une vue, pas une copie. Affirmer le type
    sans le vérifier laisserait passer un tenseur mal normalisé si une étape amont
    changeait de dtype ; ici on le garantit.
    """
    return np.asarray(array, dtype=np.uint8)


def charset_from_lines(lines: Sequence[str]) -> tuple[str, ...]:
    """Alphabet du décodage CTC, **blanc compris**.

    L'indice 0 est le blanc du CTC et n'est aucun caractère : le dictionnaire de
    PaddleOCR ne le contient pas, il est implicite. L'oublier décale tout l'alphabet
    d'un cran, ce qui produit des chaînes lisibles et entièrement fausses — le pire
    mode de panne possible, puisqu'une chaîne affichée est crue.

    **Aucune ligne n'est écartée, et surtout pas les lignes « vides ».** `en_dict.txt`
    contient une ligne dont le seul contenu est **un espace** : c'est un caractère de
    l'alphabet, pas un blanc de mise en forme. Le filtrer décale de deux crans tout ce
    qui suit — mesuré sur le vrai modèle, qui rend 97 classes là où le filtrage n'en
    construisait que 95. On ne retire donc que la fin de ligne, comme le fait
    `BaseRecLabelDecode` de PaddleOCR (`strip("\\n").strip("\\r\\n")`, pas `strip()`).
    """
    return ("", *(line.rstrip("\r\n") for line in lines))


def charset_from_metadata(raw: str) -> tuple[str, ...]:
    """Alphabet lu dans les **métadonnées du modèle**, blanc compris.

    PaddlePaddle grave la liste des caractères dans le `.onnx` sous la clé
    `character`. C'est la seule source qui ne puisse pas se désynchroniser du
    modèle : elle voyage avec lui. Le fichier de dictionnaire, lui, est un second
    artefact qu'on peut remplacer, tronquer ou confondre avec celui d'un autre
    export — et ADR 0007 raconte ce que ça coûte.

    La chaîne se termine par un saut de ligne : `split` produit alors une dernière
    entrée vide qu'il faut écarter, sans quoi l'alphabet compte un caractère de trop
    et le contrôle de cohérence rejette un modèle parfaitement valide.
    """
    entries = raw.split("\n")
    if entries and entries[-1] == "":
        entries.pop()
    return ("", *entries)


def as_probabilities(logits: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Garantit des probabilités, que l'export porte son softmax ou non.

    Les exports PP-OCR rec l'embarquent en général, mais pas tous. Sans ce
    garde-fou, une « confiance » de 37,4 traverse le fil et le seuil de publication ne
    veut plus rien dire.

    Forme stable par soustraction du maximum : un `exp` sur des logits bruts
    déborderait, et un `RuntimeWarning: overflow` de numpy fait échouer **toute** la
    suite de tests (`filterwarnings = ["error"]`).
    """
    array = np.asarray(logits, dtype=np.float32)
    # Déjà normalisé : somme à 1 sur l'axe des classes, et rien de négatif.
    if array.min() >= 0.0 and np.allclose(array.sum(axis=-1), 1.0, atol=1e-3):
        return array
    shifted = array - array.max(axis=-1, keepdims=True)
    exponentiated = np.exp(shifted)
    return (exponentiated / exponentiated.sum(axis=-1, keepdims=True)).astype(np.float32)


def ctc_greedy_decode(
    probs: npt.NDArray[np.float32], charset: Sequence[str]
) -> tuple[Reading, ...]:
    """Décodage CTC glouton d'un lot, avec sa confiance globale et par caractère.

    **Deux effondrements, dans cet ordre : répétitions consécutives d'abord, blancs
    ensuite.** L'inverse fusionnerait le double L de `ALL` en un seul, parce que le
    blanc qui les sépare est précisément ce qui les distingue.

    La confiance est la moyenne des probabilités maximales des pas de temps
    **retenus**, jamais des `T` pas de temps. Une plaque de sept caractères occupe une
    dizaine de pas sur les quarante que rend le modèle : moyenner la traîne de blancs
    — dont la probabilité maximale frôle 1,0 — tirerait toute confiance vers 0,95 et
    rendrait n'importe quel seuil inopérant.
    """
    indices = probs.argmax(axis=2)
    confidences = probs.max(axis=2)

    decoded: list[Reading] = []
    for row, scores in zip(indices, confidences, strict=True):
        characters: list[str] = []
        kept: list[float] = []
        previous = -1
        for position, index in enumerate(row):
            index_int = int(index)
            # Le blanc — index 0 — est retenu comme séparateur pour `previous`, mais
            # jamais émis ni compté dans la confiance.
            if index_int != previous and 0 < index_int < len(charset):
                characters.append(charset[index_int])
                kept.append(float(scores[position]))
            previous = index_int
        score = sum(kept) / len(kept) if kept else 0.0
        decoded.append(Reading(text="".join(characters), score=score, char_scores=tuple(kept)))
    return tuple(decoded)


def target_width(prepared_width: int, prepared_height: int, ceiling: int) -> int:
    """Largeur du tenseur pour une vignette, à rapport d'aspect conservé."""
    scaled = round(prepared_width * REC_HEIGHT / max(1, prepared_height))
    return max(REC_MIN_WIDTH, min(ceiling, int(scaled)))


def batch_width(widths: Sequence[int], ceiling: int) -> int:
    """Largeur commune d'un lot : le maximum, arrondi au quantum.

    Une largeur commune parce qu'un lot est un seul tenseur. Le maximum plutôt qu'une
    valeur fixe parce que c'est là qu'est l'économie : un lot de vignettes à 4,7:1 —
    la proportion d'une plaque européenne — tient en 226 px, et calculer 320 colonnes
    dont 94 de remplissage revient à payer 40 % de convolutions pour du vide.
    """
    if not widths:
        return REC_MIN_WIDTH
    largest = max(widths)
    quantised = -(-largest // REC_WIDTH_QUANTUM) * REC_WIDTH_QUANTUM
    return max(REC_MIN_WIDTH, min(ceiling, quantised))


def to_tensor(
    prepared: npt.NDArray[np.uint8], width: int = REC_MAX_WIDTH
) -> npt.NDArray[np.float32]:
    """Une vignette prétraitée → un tenseur `(3, 48, width)` normalisé.

    **Rapport d'aspect conservé, puis remplissage à droite** — jamais un étirement à
    la largeur cible. C'est ce que fait `RecResizeImg` de PaddleOCR, et l'oublier est
    la première cause de « le modèle tourne et rend du charabia » : étirer `AB-123-CD`
    de 140 px à 320 px déforme les glyphes au-delà de ce que le modèle a jamais vu.

    Le remplissage vaut **0,0 dans l'espace normalisé**, pas 0 dans l'espace des
    pixels : on écrit l'image normalisée dans un tableau de zéros, on ne remplit pas de
    noir avant de normaliser. Du noir normalisé vaudrait −1,0, et la dizaine de pas de
    temps correspondants porterait un signal fort au lieu de rien.
    """
    tensor = np.zeros((3, REC_HEIGHT, width), dtype=np.float32)
    height, source_width = prepared.shape[:2]
    columns = max(1, min(width, round(source_width * REC_HEIGHT / max(1, height))))
    resized = cv2.resize(prepared, (columns, REC_HEIGHT), interpolation=cv2.INTER_LINEAR)
    normalised = (resized.astype(np.float32) / 255.0 - REC_MEAN) / REC_STD
    tensor[:, :, :columns] = np.transpose(normalised, (2, 0, 1))
    return tensor


def estimate_skew(grey: npt.NDArray[np.uint8]) -> float:
    """Inclinaison de la ligne de texte, en degrés. `0` si rien de fiable.

    On soude les caractères en une seule bande par fermeture horizontale, puis on
    demande à `minAreaRect` l'angle de cette bande. Passer par les caractères plutôt
    que par les bords de la plaque est délibéré : le détecteur rend une boîte
    **alignée sur les axes**, donc ses bords ne portent aucune information d'angle —
    seul le contenu en porte.

    La polarité est déduite, jamais supposée : une plaque française est sombre sur
    clair, une plaque de nuit sous éclairage infrarouge souvent l'inverse. On garde
    la polarité où le texte est minoritaire, ce qu'il est toujours.

    Ne corrige que la rotation **dans le plan**. Une plaque vue de trois quarts
    demanderait ses quatre coins, que ce détecteur ne rend pas.
    """
    height, width = grey.shape[:2]
    if height < 8 or width < 24:
        return 0.0
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if float(binary.mean()) > 127.0:
        binary = cv2.bitwise_not(binary)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, width // 8), 3))
    band = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    points = cv2.findNonZero(band)
    if points is None or len(points) < 24:
        return 0.0

    angle = float(cv2.minAreaRect(points)[2])
    # `minAreaRect` rend l'angle du côté « le plus horizontal » selon la version
    # d'OpenCV : (-90, 0] historiquement, [0, 90) depuis la 4.5. On ramène dans
    # (-45, 45], le seul intervalle où « redresser » a un sens pour du texte.
    if angle > 45.0:
        angle -= 90.0
    elif angle <= -45.0:
        angle += 90.0
    if not MIN_SKEW_DEG <= abs(angle) <= MAX_SKEW_DEG:
        return 0.0
    return angle


def deskew(grey: npt.NDArray[np.uint8], angle: float) -> npt.NDArray[np.uint8]:
    """Redresse d'`angle` degrés, en agrandissant le cadre pour ne rien couper.

    `BORDER_REPLICATE` et non un remplissage constant : une bande noire le long d'un
    bord devient, après le passage en 48 px de haut, une colonne de pas de temps à
    fort signal que le CTC lit volontiers comme un caractère.
    """
    height, width = grey.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    bound_width = int(height * sine + width * cosine)
    bound_height = int(height * cosine + width * sine)
    matrix[0, 2] += bound_width / 2.0 - width / 2.0
    matrix[1, 2] += bound_height / 2.0 - height / 2.0
    return _as_u8(
        cv2.warpAffine(
            grey,
            matrix,
            (max(1, bound_width), max(1, bound_height)),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
    )


class OnnxPlateReader:
    """Lecteur de plaques onnxruntime, chargé **paresseusement**.

    Paresseusement pour la même raison que `UltralyticsPlateDetector` : l'absence des
    fichiers ne doit pas empêcher le service de démarrer. L'option est alors signalée
    indisponible dans `/health`, désactivée dans l'interface, et **la détection de
    plaques continue de fonctionner** — l'OCR est une option de l'option.
    """

    __slots__ = (
        "_charset_path",
        "_checked",
        "_clahe",
        "_dynamic_width",
        "_intra_op_threads",
        "_left_insets",
        "_loaded",
        "_lock",
        "_min_score",
        "_path",
        "_variants",
    )

    def __init__(
        self,
        model_path: Path,
        charset_path: Path,
        *,
        min_score: float = 0.5,
        intra_op_threads: int = 0,
        variants: bool = True,
        dynamic_width: bool = True,
        left_insets: Sequence[float] = LEFT_INSET_FRACTIONS,
    ) -> None:
        self._path = model_path
        self._charset_path = charset_path
        self._min_score = min_score
        self._intra_op_threads = intra_op_threads
        self._variants = variants
        self._dynamic_width = dynamic_width
        # Triées et dédoublonnées : deux fractions égales coûteraient deux inférences
        # pour un tenseur identique, et l'ordre décide de rien d'autre que de la
        # lisibilité des journaux.
        self._left_insets = tuple(sorted({float(f) for f in left_insets if 0.0 < float(f) < 0.9}))
        self._loaded: tuple[Any, tuple[str, ...]] | None = None
        self._checked = False
        self._clahe: Any = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Les **deux** fichiers sont-ils présents ? Les deux, ou rien.

        Un `argmax` qui indexe un dictionnaire absent — ou d'une autre taille que celle
        du modèle — ne lève pas forcément : il rend une chaîne fausse et parfaitement
        plausible. Répondre « disponible » avec un seul des deux produirait des plaques
        inventées.

        Une vérification de présence et non de chargement : l'interface interroge
        `/health` en permanence.
        """
        return self._path.is_file() and self._charset_path.is_file()

    def read(
        self, image: npt.NDArray[np.uint8], boxes: Sequence[BoundingBox]
    ) -> tuple[PlateText | None, ...]:
        """Lit un lot de plaques. Ne lève **jamais**.

        Le tableau de résultats est pré-rempli de `None` : **c'est** l'implémentation
        du contrat d'alignement positionnel du port. Une vignette écartée par
        `_prepare` laisse un trou, elle ne décale pas les suivantes.

        Chaque plaque produit une à trois *variantes* de prétraitement, toutes
        envoyées dans le **même** lot. Le coût fixe d'une inférence domine sur un
        tenseur de cette taille : trois variantes en un appel coûtent nettement moins
        que trois appels, et la meilleure des trois lit des plaques que la seule
        chaîne d'origine manquait.
        """
        # `np.stack([])` lève : le cas vide se traite avant tout le reste.
        if not boxes:
            return ()
        results: list[PlateText | None] = [None] * len(boxes)
        try:
            loaded = self._ensure_loaded()
            if loaded is None:
                return tuple(results)
            session, charset = loaded

            owners: list[int] = []
            crops: list[npt.NDArray[np.uint8]] = []
            for index, box in enumerate(boxes):
                for variant in self._prepare(image, box):
                    owners.append(index)
                    crops.append(variant)
            if not crops:
                return tuple(results)

            ceiling = REC_HARD_MAX_WIDTH if self._dynamic_width else REC_MAX_WIDTH
            widths = [target_width(crop.shape[1], crop.shape[0], ceiling) for crop in crops]
            width = batch_width(widths, ceiling) if self._dynamic_width else REC_MAX_WIDTH

            batch = np.stack([to_tensor(crop, width) for crop in crops])
            outputs = session.run(None, {session.get_inputs()[0].name: batch})
            decoded = ctc_greedy_decode(as_probabilities(outputs[0]), charset)

            # La meilleure variante de chaque plaque, à la confiance **cumulée**.
            best: dict[int, Reading] = {}
            for owner, reading in zip(owners, decoded, strict=True):
                if not reading.text:
                    continue
                incumbent = best.get(owner)
                if incumbent is None or reading.total > incumbent.total:
                    best[owner] = reading

            for owner, reading in best.items():
                if reading.score >= self._min_score:
                    results[owner] = PlateText(
                        text=reading.text,
                        score=reading.score,
                        char_scores=reading.char_scores,
                    )
            return tuple(results)
        except Exception as exc:
            logger.warning("lecture de plaque en échec", error=str(exc))
            return tuple(results)

    def _ensure_loaded(self) -> tuple[Any, tuple[str, ...]] | None:
        """Charge modèle et dictionnaire au premier usage réel, sous verrou."""
        loaded = self._loaded
        if loaded is not None:
            return loaded
        with self._lock:
            loaded = self._loaded
            if loaded is not None:
                return loaded
            if self._checked:
                # Déjà tenté et échoué : ne pas réessayer à chaque frame, ce qui
                # produirait des milliers de lignes de journal identiques.
                return None
            self._checked = True

            # Deux avertissements distincts : « lequel des deux manque » est la
            # première question que se pose l'opérateur.
            if not self._path.is_file():
                logger.warning("modèle de lecture absent — OCR indisponible", path=str(self._path))
                return None
            if not self._charset_path.is_file():
                logger.warning(
                    "dictionnaire de caractères absent — OCR indisponible",
                    path=str(self._charset_path),
                )
                return None

            # Import local, jamais au niveau module : voir la docstring du module.
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = self._intra_op_threads
            # Provider explicite : laisser onnxruntime choisir émet un avertissement
            # sur certaines versions, et un avertissement fait échouer la suite.
            session = ort.InferenceSession(
                str(self._path), options, providers=["CPUExecutionProvider"]
            )
            charset = self._resolve_charset(
                session, self._charset_path.read_text(encoding="utf-8").splitlines()
            )
            if charset is None:
                return None

            # Une seule fois, pas par vignette : `createCLAHE` alloue sa table de
            # correspondance à chaque appel.
            self._clahe = cv2.createCLAHE(CLAHE_CLIP_LIMIT, CLAHE_TILE_GRID)
            self._loaded = (session, charset)
            logger.info(
                "modèle de lecture de plaques chargé",
                path=str(self._path),
                charset_size=len(charset),
            )
            return self._loaded

    @classmethod
    def _resolve_charset(cls, session: Any, lines: Sequence[str]) -> tuple[str, ...] | None:  # noqa: ANN401
        """Alphabet aligné sur la sortie du modèle, ou `None` s'ils ne correspondent pas.

        **C'est la seule protection réelle contre le mode de panne le plus vicieux de
        tout ce dispositif.** Un dictionnaire qui ne correspond pas au modèle ne lève
        rien : il rend des chaînes fausses et parfaitement plausibles. Le cas concret
        est qu'on pointe le réglage sur l'export chinois à 6625 classes et que le
        décodage construit des plaques à partir des premiers caractères d'un autre
        alphabet.

        **La source de vérité est le modèle lui-même quand il la porte.** PaddlePaddle
        grave son alphabet dans les métadonnées du `.onnx` sous la clé `character` ;
        cet alphabet-là ne peut pas se désynchroniser, il voyage avec les poids. Le
        fichier reste exigé — `available` en dépend, et un opérateur doit pouvoir
        *voir* l'alphabet — mais il devient une seconde opinion, pas l'autorité. Quand
        les deux divergent, on le journalise et on suit le modèle.
        """
        base = charset_from_lines(lines)
        embedded = cls._embedded_charset(session)
        classes = session.get_outputs()[0].shape[-1]

        if embedded is not None:
            if len(base) != len(embedded):
                logger.warning(
                    "dictionnaire différent de l'alphabet gravé — le modèle fait foi",
                    file_size=len(base),
                    model_size=len(embedded),
                )
            resolved = cls._match_classes(embedded, classes)
            if resolved is not None:
                return resolved
            # Les métadonnées existent mais ne collent pas à la sortie : cas assez
            # anormal pour ne pas décider tout seul, on retombe sur le fichier.
            logger.warning(
                "alphabet gravé incohérent avec la sortie du modèle — repli sur le fichier",
                model_classes=classes,
                embedded_size=len(embedded),
            )

        resolved = cls._match_classes(base, classes)
        if resolved is not None:
            return resolved
        logger.error(
            "dictionnaire incompatible avec le modèle — OCR désactivée",
            model_classes=classes,
            charset_size=len(base),
            hint="les deux fichiers doivent venir du même export (voir ADR 0007)",
        )
        return None

    @staticmethod
    def _embedded_charset(session: Any) -> tuple[str, ...] | None:  # noqa: ANN401
        """L'alphabet gravé dans les métadonnées, ou `None` si le modèle n'en porte pas."""
        try:
            metadata = session.get_modelmeta().custom_metadata_map or {}
        except Exception:
            # Un export qui n'expose pas de métadonnées n'est pas une erreur : c'est
            # le cas de tout `.onnx` ne venant pas de PaddlePaddle. On retombe
            # simplement sur le fichier de dictionnaire.
            return None
        raw = metadata.get("character")
        if not raw:
            return None
        return charset_from_metadata(raw)

    @staticmethod
    def _match_classes(charset: tuple[str, ...], classes: object) -> tuple[str, ...] | None:
        """Ajuste l'alphabet à la sortie du modèle, ou `None` si l'écart est inexplicable.

        **L'espace de `use_space_char` est ajouté seulement s'il manque exactement une
        classe.** PaddleOCR l'ajoute à la fin de l'alphabet quand le modèle a été
        entraîné avec, et le fichier de dictionnaire ne le contient pas : on ne peut donc
        pas savoir d'avance s'il faut l'ajouter. Le déduire de l'écart est vérifiable —
        on n'ajoute que ce qui fait correspondre les tailles **exactement**, et un écart
        de deux ou plus reste un refus. L'espace en fin d'alphabet ne décale rien de ce
        qui précède, et la normalisation du domaine le retire de toute façon.

        Une dimension de sortie dynamique n'est pas vérifiable ici : on laisse passer
        plutôt que de refuser un modèle valide, le script de récupération ayant déjà fait
        le contrôle à un instant choisi.
        """
        if not isinstance(classes, int):
            return charset
        if classes == len(charset):
            return charset
        if classes == len(charset) + 1:
            logger.info(
                "espace ajouté à l'alphabet pour correspondre au modèle",
                detail="le modèle a été entraîné avec use_space_char",
                charset_size=classes,
            )
            return (*charset, " ")
        return None

    def _prepare(
        self, image: npt.NDArray[np.uint8], box: BoundingBox
    ) -> tuple[npt.NDArray[np.uint8], ...]:
        """Recadre et prépare **les variantes** d'une vignette, ou rien si elle ne vaut rien.

        La chaîne de base est celle de PP-OCR, dans cet ordre : niveaux de gris,
        suréchantillonnage conditionnel, CLAHE, retour sur trois canaux.

        Le passage en niveaux de gris n'est pas gratuit à justifier — le modèle a été
        entraîné en couleur — mais le contraste d'une plaque est de la luminance, et
        sur un recadrage de 60 px de large la chrominance sous-échantillonnée en 4:2:0
        par le codec n'apporte que du bruit.

        Les variantes ne s'ajoutent que lorsqu'elles ont une chance de changer quelque
        chose, jamais autrement — une variante identique à la première coûterait une
        inférence pour rien :

        - **redressée**, si et seulement si un angle exploitable a été mesuré ;
        - **encart**, qui rogne le cadre de la plaque. Le détecteur cadre le rectangle
          entier, liseré compris, et ce liseré entre dans les pas de temps du CTC ;
        - **rognées à gauche**, une par fraction de `LEFT_INSET_FRACTIONS`. Elles
          existent pour un caractère de tête que l'alphabet du modèle ne contient pas
          — un idéogramme de province — et qui, faute de classe où aller, contamine la
          lettre voisine. C'est la variante la plus payante du dispositif, et sa
          docstring de constante porte la mesure.

        C'est le décodage qui départage, à confiance cumulée : on ne cherche pas à
        savoir *a priori* laquelle est la bonne, on les lit et on garde celle qui a lu
        le plus de caractères le plus sûrement. Une variante qui coupe un vrai
        caractère rend donc une chaîne plus courte, et **perd** — c'est ce qui rend
        l'ajout strictement additif.
        """
        height, width = image.shape[:2]
        x1 = max(0, int(box.x))
        y1 = max(0, int(box.y))
        x2 = min(width, int(box.x + box.width))
        y2 = min(height, int(box.y + box.height))
        if x2 - x1 < MIN_PLATE_WIDTH_PX or y2 - y1 < MIN_PLATE_HEIGHT_PX:
            return ()

        grey = _as_u8(cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY))
        variants = [self._finish(grey)]
        if not self._variants:
            return tuple(variants)

        angle = estimate_skew(grey)
        if angle != 0.0:
            variants.append(self._finish(deskew(grey, angle)))

        crop_height, crop_width = grey.shape[:2]
        top = int(crop_height * INSET_VERTICAL)
        bottom = crop_height - top
        left = int(crop_width * INSET_HORIZONTAL)
        right = crop_width - left
        if bottom - top >= MIN_PLATE_HEIGHT_PX and right - left >= MIN_PLATE_WIDTH_PX:
            variants.append(self._finish(_as_u8(grey[top:bottom, left:right])))

        for fraction in self._left_insets:
            cut = int(crop_width * fraction)
            if crop_width - cut >= MIN_VARIANT_WIDTH_PX:
                variants.append(self._finish(_as_u8(grey[:, cut:])))
        return tuple(variants)

    def _finish(self, source: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Suréchantillonnage conditionnel, CLAHE, retour sur trois canaux."""
        grey = source
        crop_width = grey.shape[1]
        if crop_width < UPSCALE_MIN_WIDTH_PX:
            factor = min(MAX_UPSCALE, UPSCALE_MIN_WIDTH_PX / crop_width)
            grey = _as_u8(
                cv2.resize(
                    grey,
                    (int(grey.shape[1] * factor), int(grey.shape[0] * factor)),
                    interpolation=cv2.INTER_CUBIC,
                )
            )

        if self._clahe is not None:
            grey = _as_u8(self._clahe.apply(grey))
        # La tête attend trois canaux. `astype` plutôt qu'une annotation : les stubs de
        # `cv2` élargissent le dtype, et affirmer `uint8` sans le garantir laisserait
        # passer un tenseur mal normalisé si une étape amont changeait de type.
        return cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR).astype(np.uint8)
