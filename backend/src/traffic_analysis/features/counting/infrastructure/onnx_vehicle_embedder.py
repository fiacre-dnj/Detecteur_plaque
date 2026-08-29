"""Encodeur d'apparence de véhicule — OSNet-AIN sur `onnxruntime`.

**Pourquoi ici et pas dans `models_registry/infrastructure/`.** Ce module a besoin de
la définition partagée de « la vignette d'un véhicule » (`vehicle_crop`), qui vit dans
cette feature ; et il n'importe pas `ultralytics`, dont `models_registry` détient le
monopole. Le port qu'il implémente est dans `counting/application/ports.py`, juste à
côté.

**Le modèle.** `vehicle-reid-0001` de l'Open Model Zoo : OSNet-AIN entraîné sur
VeRi-776, rank-1 96,31 % / mAP 85,15 %, 2,18 MParams, licence MIT. Le `model.yml`
annonce une entrée figée `1×3×208×208` ; le graphe réel est **entièrement dynamique**
(`batch_size, channels, height, width`), vérifié à l'inspection. On encode donc par
lot, ce qui est le bon sens ici — contrairement à l'OCR, où grouper est 1,6× plus lent
parce que `batch_width` aligne tout le lot sur la vignette la plus large (ADR 0030).
Ici toutes les vignettes sont redimensionnées au même carré : le lot est gratuit.

**CPU, et c'est assumé.** `onnxruntime` n'a pas de provider CUDA sur cette machine
(vérifié : `['AzureExecutionProvider', 'CPUExecutionProvider']`), donc cet étage est
cloué au processeur comme l'OCR — **21,8 ms mesurés par vignette**. C'est acceptable
parce qu'on encode **quelques fois dans la vie d'un véhicule** : la règle monotone
d'ADR 0042, transposée, plus la marge de largeur d'ADR 0050.

Cette docstring a longtemps annoncé « une fois par véhicule », et c'était faux : la
règle monotone seule (« plus large que la meilleure vue ») est vraie à presque chaque
image d'un véhicule qui approche, donc on encodait par image. Ce que la mesure
d'ADR 0048 comptait — « 8 véhicules suivis, 2 encodés » — était un nombre de
*véhicules*, pas d'*encodages*. C'est exactement l'erreur qu'ADR 0032 a documentée sur
le détecteur de plaques, refaite ici et corrigée par la marge.

**Le prétraitement a été mesuré, et le résultat est contre-intuitif.** Le README de
l'OMZ ne documente ni moyenne ni écart-type, ce qui ressemblait au piège du
dictionnaire décalé d'ADR 0007 — un prétraitement faux ne lève rien, il rend des
embeddings plausibles et dégradés. Mesuré sur 12 vraies vignettes
(`scripts/reid_bench.py --variants`) :

- **la normalisation d'intensité n'a aucun effet** : `cos(x/255, (x/255 - mean)/std)`
  et même `cos(x/255, x)` valent **1,0**. Ce n'est pas un hasard, c'est
  l'architecture : le « AIN » d'OSNet-AIN est de l'*Adaptive Instance Normalization*,
  qui normalise par canal et par échantillon sur les dimensions spatiales — le réseau
  est donc invariant à toute transformation affine par canal de son entrée. C'est
  pourquoi l'OMZ n'en documente pas : il n'en a pas besoin. Aucune normalisation
  d'intensité n'est donc appliquée ici, parce qu'une arithmétique dont on a **prouvé**
  qu'elle ne change rien est du code mort qui prétend compter ;
- **l'ordre des canaux, lui, décide tout** : `cos(rgb, bgr)` descend à **0,508** et
  vaut 0,714 en moyenne. Le graphe attend du **RGB** — la conversion IR de l'OMZ passe
  `--reverse_input_channels`, et la mesure le confirme : en RGB l'écart same/diff vaut
  +0,694 contre +0,642 en BGR. Nos images étant en BGR partout (c'est ce qu'attend
  Ultralytics), l'inversion se fait ici et elle n'est pas décorative.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog

from traffic_analysis.features.counting.application.ports import VehicleAppearance
from traffic_analysis.features.counting.domain.appearance import cosine_similarity
from traffic_analysis.features.counting.infrastructure.vehicle_crop import (
    VEHICLE_MARGIN,
    crop,
    sharpness,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import numpy.typing as npt

    from traffic_analysis.features.counting.domain.models import BoundingBox

logger = structlog.get_logger(__name__)

#: Côté de l'entrée du réseau. C'est la taille d'entraînement du modèle : la changer
#: n'est pas un réglage de vitesse mais un changement de domaine, et OSNet est un
#: réseau à échelles multiples dont les branches sont calibrées pour ce côté.
NET_SIZE = 208

#: Dimension du vecteur rendu. Vérifiée au chargement contre la sortie réelle du
#: graphe — un modèle substitué qui rendrait 256 ou 2048 se comparerait sinon très
#: bien à lui-même et pas du tout aux embeddings déjà en mémoire.
EMBEDDING_DIM = 512

#: Vignettes par appel au réseau. Le graphe est dynamique, donc le lot n'est qu'un
#: compromis mémoire : 16 recadrages de 208² en float32 pèsent 8,3 Mo.
MAX_BATCH = 16


class OnnxVehicleEmbedder:
    """Implémentation `onnxruntime` de `VehicleEmbedder`. Ne lève jamais.

    Chargement **paresseux** et à double verrou, comme `OnnxPlateReader` : `available`
    ne doit pas charger un modèle, parce que `/health` est interrogé en permanence, et
    un échec de chargement ne doit pas être retenté à chaque image.
    """

    __slots__ = (
        "_checked",
        "_intra_op_threads",
        "_lock",
        "_min_sharpness",
        "_min_width_px",
        "_path",
        "_session",
    )

    def __init__(
        self,
        model_path: Path,
        *,
        min_vehicle_width_px: float = 96.0,
        min_sharpness: float = 8.0,
        intra_op_threads: int = 0,
    ) -> None:
        self._path = model_path
        self._min_width_px = min_vehicle_width_px
        self._min_sharpness = min_sharpness
        #: `0` laisse onnxruntime prendre tous les cœurs, ce qui est **1,9× pire**
        #: que le défaut mesuré ici sur 12 fils (31,9 ms contre 17,0). Le budget
        #: vient de `Settings.resolved_reid_intra_op_threads`, avec repli sur
        #: `inference_threads` — le même câblage que l'OCR, resté absent ici.
        self._intra_op_threads = intra_op_threads
        self._session: Any = None
        self._checked = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Le fichier est là — **présence seulement**, jamais chargement.

        Même règle que `UltralyticsPlateDetector.available` et pour la même raison :
        `/health` est interrogé en permanence, et y charger 8,8 Mo d'ONNX en ferait un
        point de contention. `probe()` répond à l'autre question.
        """
        return self._path.is_file()

    def probe(self) -> bool:
        """Charge et fait **une** inférence à vide. Rend `False` sans lever.

        C'est ce qui sépare `reidAvailable` de `reidLoadable` : un `.pt` déposé sous un
        nom en `.onnx`, un fichier tronqué, un graphe dont la sortie n'a pas la bonne
        dimension — tout cela passe `available` et échoue ici. « Poids présents,
        recherche muette, tout vert par ailleurs » est l'état qu'on refuse.
        """
        try:
            if self._ensure_loaded() is None:
                return False
            blank = np.zeros((NET_SIZE, NET_SIZE, 3), dtype=np.uint8)
            return self._infer([blank]) is not None
        except Exception:
            logger.error("auto-test de l'encodeur de ressemblance en échec", exc_info=True)
            return False

    def embed(
        self,
        image: npt.NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
    ) -> tuple[VehicleAppearance | None, ...]:
        """Un élément par boîte, dans le même ordre. Ne lève jamais."""
        empty: tuple[VehicleAppearance | None, ...] = (None,) * len(boxes)
        if not boxes:
            return ()
        try:
            if self._ensure_loaded() is None:
                return empty

            # Les recadrages retenus **et leur position d'origine** : c'est cette
            # seconde liste qui garantit l'alignement positionnel du contrat. Sans
            # elle, un véhicule trop petit décalerait tous ses suivants d'un cran.
            thumbs: list[npt.NDArray[np.uint8]] = []
            slots: list[int] = []
            for index, box in enumerate(boxes):
                thumb = self._thumb_for(image, box)
                if thumb is None:
                    continue
                thumbs.append(thumb)
                slots.append(index)

            if not thumbs:
                return empty

            vectors = self._infer(thumbs)
            if vectors is None:
                return empty

            out: list[VehicleAppearance | None] = list(empty)
            for slot, vector in zip(slots, vectors, strict=True):
                out[slot] = VehicleAppearance(vector=vector)
            return tuple(out)
        except Exception:
            logger.warning("encodage d'apparence impossible", exc_info=True)
            return empty

    def embed_query(self, payload: bytes) -> VehicleAppearance | None:
        """Décode l'image de requête et l'encode. Sans plancher de taille.

        Le décodage vit ici et non dans le service, parce que `cv2` est interdit dans
        `application/**` : les octets voyagent, les pixels restent dans l'adaptateur.

        Aucun `crop` : l'appelant a déjà réduit l'image à la vignette du véhicule
        cherché — le client cadre avant l'envoi. Redécouper serait un second cadrage
        par-dessus le premier, donc deux cadrages différents des deux côtés de la
        comparaison, ce que `vehicle_crop` existe précisément pour empêcher.
        """
        try:
            if self._ensure_loaded() is None:
                return None
            import cv2

            decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            if decoded is None or min(decoded.shape[:2]) < 1:
                logger.warning("image de requête illisible", octets=len(payload))
                return None
            # BGR, comme partout ailleurs dans ce projet : `IMREAD_COLOR` le garantit,
            # et c'est `_preprocess` qui inverse vers le RGB attendu par le graphe.
            # `astype` explicite : `imdecode` est typé « entier ou flottant » et
            # `IMREAD_COLOR` rend toujours du `uint8`, mais le vérificateur ne le
            # sait pas — et le reste de la chaîne est typé sur `uint8`.
            thumb: npt.NDArray[np.uint8] = np.ascontiguousarray(decoded, dtype=np.uint8)
            vectors = self._infer([thumb])
            if vectors is None:
                return None
            return VehicleAppearance(vector=vectors[0])
        except Exception:
            logger.warning("encodage de l'image de requête impossible", exc_info=True)
            return None

    # ── Interne ──────────────────────────────────────────────────────────────

    def _thumb_for(
        self, image: npt.NDArray[np.uint8], box: BoundingBox
    ) -> npt.NDArray[np.uint8] | None:
        """La vignette d'un véhicule, ou `None` si elle ne vaut rien.

        Les deux planchers sont **la** raison pour laquelle cet étage ne coûte presque
        rien, et ils sont la transposition directe d'ADR 0039 : ne pas payer une
        inférence pour un résultat dont on sait déjà qu'il n'aura pas de valeur. Sous
        208 px d'entrée, agrandir un recadrage de 60 px n'ajoute aucune information —
        l'embedding ressemble surtout au flou.
        """
        if box.width < self._min_width_px:
            return None
        thumb = crop(image, box, margin=VEHICLE_MARGIN)
        if thumb is None:
            return None
        # Copie, pas la vue : `crop` rend une vue sur l'image parente, et la retenir
        # le temps du lot retiendrait 6 Mo par véhicule en 1080p.
        thumb = np.ascontiguousarray(thumb)
        # La netteté est un **plancher** et non un critère de rang : celui-ci est la
        # largeur de boîte, que le domaine évalue avant tout recadrage. Voir
        # `AnalysisSession.should_embed`.
        if sharpness(thumb) < self._min_sharpness:
            return None
        return thumb

    def _infer(
        self, thumbs: Sequence[npt.NDArray[np.uint8]]
    ) -> list[npt.NDArray[np.float32]] | None:
        """Encode un lot de vignettes et rend des vecteurs **normalisés L2**.

        Normalisé ici et nulle part ailleurs : c'est ce qui fait de la similarité
        cosinus un produit scalaire, et ce qui évite que deux consommateurs
        normalisent différemment — ou qu'un seul l'oublie, auquel cas les scores
        sortiraient de [-1, 1] sans que rien ne le signale.
        """
        session = self._ensure_loaded()
        if session is None:
            return None
        out: list[npt.NDArray[np.float32]] = []
        for start in range(0, len(thumbs), MAX_BATCH):
            batch = _preprocess(thumbs[start : start + MAX_BATCH])
            raw = np.asarray(session.run(None, {session.get_inputs()[0].name: batch})[0])
            if raw.ndim != 2 or raw.shape[1] != EMBEDDING_DIM:
                # Refus explicite plutôt qu'une comparaison entre dimensions
                # différentes : celle-ci lèverait au premier produit scalaire, très
                # loin d'ici — ou pire, se tairait si les tailles étaient compatibles
                # par accident. Même doctrine que le dictionnaire d'OCR, dont une
                # taille inattendue fait refuser le chargement (ADR 0007).
                #
                # Ici et non au chargement : la forme déclarée du graphe est
                # symbolique, seule la sortie réelle est un nombre.
                logger.error(
                    "dimension d'embedding inattendue — encodeur refusé",
                    expected=EMBEDDING_DIM,
                    actual=str(raw.shape),
                    path=str(self._path),
                )
                # Le rendre inutilisable pour de bon : le graphe ne changera pas de
                # forme d'une image à l'autre, donc réessayer produirait la même
                # erreur à chaque véhicule de chaque image.
                self._session = None
                return None
            out.extend(_l2_normalise(raw.astype(np.float32, copy=False)))
        return out

    def _ensure_loaded(self) -> Any:  # noqa: ANN401
        """Charge au premier usage réel, sous verrou, et rend la session ou `None`.

        La **session** sert de sentinelle et non un booléen, exactement comme
        `OnnxPlateReader._ensure_loaded` rend son couple : un drapeau lu avant le verrou
        puis relu dedans se fait étroitement narrower par mypy, qui déclare alors la
        seconde branche inatteignable. `_checked` n'est donc consulté que **sous** le
        verrou, et il n'existe que pour ne pas réessayer un chargement déjà échoué —
        sinon un modèle illisible serait rechargé à chaque image, plus cher que
        l'inférence qu'on cherche à faire.
        """
        session = self._session
        if session is not None:
            return session
        with self._lock:
            session = self._session
            if session is not None:
                return session
            if self._checked:
                return None
            self._checked = True

            if not self._path.is_file():
                logger.info("encodeur de ressemblance absent", path=str(self._path))
                return None
            try:
                # Import local : `onnxruntime` pèse au chargement, et la CI doit
                # pouvoir importer ce module sans lui.
                import onnxruntime as ort

                options = ort.SessionOptions()
                if self._intra_op_threads > 0:
                    options.intra_op_num_threads = self._intra_op_threads
                # Le modèle bavarde à chaque chargement (initialiseurs inutilisés
                # d'un export torch) : des dizaines de lignes de journal qui ne
                # décrivent rien d'actionnable.
                options.log_severity_level = 3
                loaded = ort.InferenceSession(
                    str(self._path), options, providers=["CPUExecutionProvider"]
                )
            except Exception:
                logger.error(
                    "chargement de l'encodeur de ressemblance impossible",
                    path=str(self._path),
                    exc_info=True,
                )
                return None

            # **La dimension n'est pas vérifiable ici**, et l'avoir cru une fois est
            # instructif : ce graphe déclare sa sortie `['batch_size', 'dim']`, donc
            # `shape[-1]` rend la *chaîne* `"dim"` et non `512`. Une garde
            # `isinstance(dim, int) and dim != EMBEDDING_DIM` ne se déclenche donc
            # jamais sur un modèle à formes dynamiques — c'est-à-dire sur celui-ci.
            # Un contrôle annoncé et inerte est pire que pas de contrôle (ADR 0016) :
            # il est déplacé dans `_infer`, où la sortie est concrète.
            self._session = loaded
            logger.info(
                "encodeur de ressemblance chargé",
                path=str(self._path),
                declared_shape=str(loaded.get_outputs()[0].shape),
            )
            return loaded


def _preprocess(thumbs: Sequence[npt.NDArray[np.uint8]]) -> npt.NDArray[np.float32]:
    """BGR → RGB, étirement au carré du réseau, échelle [0, 1]. Rien de plus.

    **L'inversion des canaux est la seule étape qui compte, et elle compte beaucoup** :
    mesuré sur de vraies vignettes, `cos(rgb, bgr)` descend à 0,508. Se tromper ici ne
    lève pas — cela rend des embeddings cohérents entre eux et médiocres, donc une
    recherche qui « marche » mal.

    **Aucune normalisation d'intensité**, et c'est un choix mesuré et non un oubli :
    OSNet-AIN normalise par instance, donc `cos(x/255, (x/255 - mean)/std) = 1,0` et
    même `cos(x/255, x) = 1,0`. Le `/255` lui-même ne sert donc qu'à rester dans le
    domaine où le réseau a été exporté. Voir la docstring du module.

    L'étirement est un redimensionnement au carré et non un letterbox : c'est ce que
    fait `torchreid` à l'entraînement, et l'entrée doit ressembler à ce que le réseau a
    vu. Un letterbox introduirait des bandes qu'il n'a jamais rencontrées.
    """
    import cv2

    batch = np.empty((len(thumbs), 3, NET_SIZE, NET_SIZE), dtype=np.float32)
    for index, thumb in enumerate(thumbs):
        resized = cv2.resize(thumb, (NET_SIZE, NET_SIZE), interpolation=cv2.INTER_LINEAR)
        rgb = resized[..., ::-1]
        batch[index] = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
    return batch


def _l2_normalise(raw: npt.NDArray[np.float32]) -> list[npt.NDArray[np.float32]]:
    """Normalise chaque ligne, et rend un vecteur nul tel quel.

    Un vecteur de norme nulle ne porte aucune information d'apparence ; le diviser
    produirait des `NaN` qui contamineraient toutes les comparaisons ultérieures en
    restant invisibles — `NaN < seuil` est faux, donc le véhicule disparaîtrait
    simplement des résultats.
    """
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    safe = np.where(norms < 1e-12, 1.0, norms)
    return [row.astype(np.float32, copy=False) for row in raw / safe]


#: Réexporté depuis le domaine : c'est **là** que « se ressembler » est défini, et il
#: n'en existe qu'une définition. Ce module produit les vecteurs, il ne juge pas.
__all__ = [
    "EMBEDDING_DIM",
    "MAX_BATCH",
    "NET_SIZE",
    "OnnxVehicleEmbedder",
    "cosine_similarity",
]
