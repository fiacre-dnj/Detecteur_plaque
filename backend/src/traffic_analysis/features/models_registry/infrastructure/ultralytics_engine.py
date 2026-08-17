"""Adaptateur Ultralytics — **le seul importateur d'`ultralytics` du projet**.

C'est ici, et nulle part ailleurs, que `Results`/`Boxes`/`xyxy` deviennent des
`TrackObservation` du domaine. Un test d'architecture le vérifie.

Le temps de scène est vrai **par construction** : `timestamp_ms` vient de
`frame_index / fps`, jamais d'une horloge. Introduire `time.time()` ici casserait
d'un coup les débits, les vitesses et les gates de ré-identification.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

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

#: Côté d'entrée du réseau par défaut. C'est **exactement** ce qu'Ultralytics
#: appliquait quand personne ne le passait : le rendre explicite ne change aucun
#: chiffre, il rend seulement réglable ce qui était subi.
DEFAULT_IMGSZ = 640

#: Largeur attendue de `boxes.data` en suivi : `[x1, y1, x2, y2, id, conf, cls]`.
TRACKED_BOX_COLUMNS = 7

# `parents[5]` mène à `backend/` : infrastructure → models_registry → features →
# traffic_analysis → src → backend. Compté à la main, ce décalage a été **faux**
# (`parents[4]`, donc `backend/src/config/`) et l'erreur ne se voyait qu'à
# l'exécution d'une vraie analyse : les tests injectent un `FakeEngine` et ne
# passent jamais ici. D'où le test d'existence ci-dessous, qui échoue au
# chargement du module plutôt qu'au milieu d'un job.
CONFIG_DIR = Path(__file__).resolve().parents[5] / "config"
TRACKER_CONFIG = CONFIG_DIR / "botsort_reid.yaml"


@lru_cache(maxsize=1)
def _base_tracker() -> dict[str, Any]:
    """Le fichier de suivi versionné, lu une fois par processus."""
    import yaml

    loaded: dict[str, Any] = yaml.safe_load(TRACKER_CONFIG.read_text(encoding="utf-8"))
    return loaded


def detector_floor() -> float:
    """Seuil de confiance à passer au **détecteur**, et non au comptage.

    **C'est le mécanisme BYTE, et il était débranché.** ByteTrack — dont BoT-SORT
    hérite — sépare les détections en deux bandes (`byte_tracker.py`, `_split`) :

    - **haute** (`≥ track_high_thresh`) — première association, et seule à pouvoir
      *créer* une piste (`new_track_thresh`) ;
    - **basse** (`track_low_thresh < score < track_high_thresh`) — seconde
      association, qui sert **uniquement à prolonger une piste existante**, par
      recouvrement de boîtes seul (`iou_distance`, seuil 0,5).

    Toute la valeur du tracker tient dans cette seconde bande : c'est elle qui
    tient un véhicule dont la confiance plonge le temps d'une occlusion partielle,
    d'un flou de mouvement ou d'un reflet.

    Or Ultralytics filtre les détections **avant** que le tracker les voie : en
    passant `conf = 0.35` (le seuil de l'utilisateur) à `track()`, rien n'atteignait
    jamais la bande basse, qui va de 0,1 à 0,25. La seconde association était du
    code mort, et une confiance qui plongeait une seule image coupait la piste.
    Une piste coupée, c'est un numéro de véhicule neuf, un ré-amorçage du compteur
    de lignes, et **un franchissement perdu** s'il tombe dans cette fenêtre.

    Le détecteur reçoit donc `track_low_thresh` ; le seuil de l'utilisateur devient
    `track_high_thresh` et `new_track_thresh` (voir `resolved_tracker_config`). La
    création de pistes est **inchangée** — il faut toujours atteindre le seuil de
    l'utilisateur — seule la survie d'une piste déjà née s'améliore.
    """
    return float(_base_tracker()["track_low_thresh"])


@lru_cache(maxsize=32)
def resolved_tracker_config(gmc_method: str, high_thresh: float) -> Path:
    """Chemin du tracker à utiliser, mouvement et seuil de piste imposés.

    Ultralytics ne prend sa configuration de suivi **que** sous forme de chemin de
    fichier : il n'existe aucune façon de lui passer un réglage en mémoire. Rendre
    `gmc_method` réglable — et, depuis, faire suivre le seuil de l'utilisateur
    jusqu'au tracker — demande donc d'écrire un fichier dérivé.

    `high_thresh` est le seuil de confiance de la requête. Il est posé **à la fois**
    sur `track_high_thresh` et sur `new_track_thresh`, et les deux comptent :

    - `track_high_thresh` sépare les deux bandes d'association. Sans lui, toutes
      les détections seraient « hautes » et la bande basse resterait vide, ce qui
      est exactement la panne que `detector_floor` décrit ;
    - `new_track_thresh` garde la **création** de pistes au seuil de l'utilisateur.
      C'est lui qui rend le changement strictement additif : une détection faible
      peut prolonger une piste, jamais en ouvrir une.

    Quand le fichier de base dit déjà la même chose, **il est rendu tel quel** : pas
    de copie, pas de fichier temporaire, et le chemin journalisé reste celui que le
    dépôt versionne.

    L'écriture est atomique (fichier temporaire puis `replace`) parce que deux
    processus peuvent démarrer en même temps — un rechargement `--reload` en
    développement suffit — et qu'un fichier YAML lu à moitié écrit ferait échouer
    une analyse avec un message parlant de syntaxe, très loin de la cause.

    `lru_cache` : un fichier par couple (mouvement, seuil) et par processus. Le
    seuil vient de la requête, donc quelques valeurs distinctes au plus — d'où les
    32 entrées, contre 8 quand seul le mouvement variait.
    """
    import yaml

    base = _base_tracker()
    overrides = {
        "gmc_method": gmc_method,
        "track_high_thresh": high_thresh,
        "new_track_thresh": high_thresh,
    }
    if all(base.get(key) == value for key, value in overrides.items()):
        return TRACKER_CONFIG

    slug = f"botsort-gmc-{gmc_method}-hi-{high_thresh:.2f}.yaml"
    target = Path(tempfile.gettempdir()) / "traffic-analysis" / slug
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    staging.write_text(
        yaml.safe_dump({**base, **overrides}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    staging.replace(target)
    return target


def _first_analysed_index(start_ms: float, fps: float, stride: int) -> int:
    """Index de la première image à analyser pour une borne de début donnée.

    **Doit rester d'accord avec le filtre d'`AnalysisService`**, qui garde les
    images dont `timestamp_ms >= start_ms`. Comme `timestamp_ms = index / fps`,
    cela donne `index >= start_ms × fps / 1000` ; et comme seules les images
    d'index multiple de `stride` sont analysées, on remonte au multiple suivant.

    Se tromper d'un cran ne lève rien : trop bas, l'application rejetterait les
    premières images décodées (du travail perdu, invisible) ; trop haut, la fenêtre
    perdrait une image que l'utilisateur a demandée, et personne ne le verrait
    jamais. D'où le calcul explicite, testé, plutôt qu'une soustraction au vol.
    """
    if start_ms <= 0.0 or fps <= 0.0:
        return 0
    first = ceil(start_ms * fps / 1000.0)
    return ceil(first / max(1, stride)) * max(1, stride)


class UltralyticsEngine:
    """Détection et suivi par Ultralytics, derrière le port du domaine."""

    __slots__ = ("_batch", "_gmc", "_imgsz", "_registry")

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        gmc_method: str | None = None,
        imgsz: int = DEFAULT_IMGSZ,
        batch: int = 1,
    ) -> None:
        """Les trois réglages de **déploiement** du moteur.

        Ils vivent ici et non dans `EngineSpec`, qui porte la **requête** : la
        taille d'entrée, le lot et la compensation de mouvement arbitrent du débit
        contre de la précision ou de la mémoire — un choix de machine, que
        l'utilisateur d'une analyse ne peut pas juger depuis sa vidéo. Même
        frontière que pour les réglages d'OCR (ADR 0008 §4).

        `gmc_method` à `None` garde ce que dit le fichier de configuration.

        Tout est journalisé au démarrage : c'est la seule trace qui distingue « le
        réglage a été pris en compte » de « les valeurs par défaut tournent
        toujours », et les deux produisent des analyses qui fonctionnent.
        """
        self._registry = registry
        self._imgsz = imgsz
        self._batch = max(1, batch)
        # Le mouvement seul est un réglage de déploiement ; le fichier de suivi, lui,
        # ne peut plus être résolu ici : il porte désormais le seuil de confiance de
        # **la requête** (voir `detector_floor`). Il est donc résolu par course.
        self._gmc = gmc_method if gmc_method is not None else str(_base_tracker()["gmc_method"])
        logger.info(
            "moteur configuré",
            gmc=self._gmc,
            tracker=str(TRACKER_CONFIG),
            detector_floor=detector_floor(),
            imgsz=self._imgsz,
            batch=self._batch,
        )

    def _tracker_for(self, spec: EngineSpec) -> Path:
        """Le fichier de suivi de cette course : mouvement de déploiement, seuil de requête."""
        return resolved_tracker_config(self._gmc, spec.confidence)

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

        **Deux chemins, un seul contrat.** Sans début demandé, la vidéo part au
        chargeur d'Ultralytics, qui la décode par lots et sait la lire vite. Avec un
        début, ce chargeur ne sert plus à rien : il **ne sait pas se déplacer** —
        `LoadImagesAndVideos` ouvre à zéro et avance —, donc analyser à partir de la
        cinquantième minute d'un fichier d'une heure coûterait cinquante minutes
        d'inférence sur des images jetées. Le second chemin décode alors lui-même,
        après un déplacement, et confie les images une par une au modèle, exactement
        comme le fait déjà le temps réel.

        Ce que les deux chemins garantissent identiquement, et qu'il ne faut pas
        casser : `frame_index` est l'index **dans le fichier**, donc `timestamp_ms`
        reste du temps de scène absolu. Une fenêtre ne décale aucun horodatage.
        """
        info = self.probe(video_path)
        stride = max(1, spec.frame_stride)
        first_index = _first_analysed_index(spec.start_ms, info.fps, stride)

        with self._registry.lease(spec.model_id) as model:
            reset_trackers(model)
            if first_index > 0:
                yield from self._iter_seeked(model, video_path, info, spec, stride, first_index)
                return
            results = model.track(
                source=str(video_path),
                stream=True,
                tracker=str(self._tracker_for(spec)),
                # **Le plancher du détecteur, pas le seuil de l'utilisateur.** Ce
                # dernier est passé au tracker comme `track_high_thresh` /
                # `new_track_thresh` : la création de pistes reste à son niveau,
                # mais les détections faibles atteignent enfin la seconde
                # association, qui prolonge une piste dont la confiance plonge.
                # Voir `detector_floor` pour la panne que cela corrige.
                conf=detector_floor(),
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
                imgsz=self._imgsz,
                # **Le lot ne change rien au suivi, et c'est vérifié dans la roue
                # installée.** `LoadImagesAndVideos` remplit un lot d'images
                # **consécutives** de la même vidéo, et `on_predict_postprocess_end`
                # leur applique `trackers[0]` une par une, dans l'ordre. Avec
                # `stream=True`, les résultats restent rendus un par un : la
                # correspondance `frame_index = position × stride` ci-dessous reste
                # donc vraie, et c'est elle qui porte tout le temps de scène.
                batch=self._batch,
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

    def _iter_seeked(
        self,
        model: Any,  # noqa: ANN401 — un `YOLO` n'est pas typé
        video_path: Path,
        info: VideoInfo,
        spec: EngineSpec,
        stride: int,
        first_index: int,
    ) -> Iterator[EngineFrame]:
        """Décode à partir de `first_index` et suit image par image.

        Le déplacement se fait en deux temps, et le second n'est pas une précaution
        de style : `CAP_PROP_POS_FRAMES` est **approximatif** sur plusieurs
        conteneurs — FFmpeg se pose sur l'image-clé précédente, et certains
        démultiplexeurs dépassent la cible. On lit donc la position réellement
        atteinte, on repart de zéro si elle a dépassé, puis on avance par `grab()`,
        qui démultiplexe sans convertir en tableau : quelques dizaines d'images de
        rattrapage coûtent bien moins qu'une seule inférence.

        Ce module a déjà payé une panne silencieuse de cette famille (le
        `parents[5]` de `CONFIG_DIR`) : un déplacement approximatif accepté sans
        vérification donnerait des `frame_index` faux, donc des horodatages faux,
        donc des vitesses et des franchissements datés à côté — sans qu'aucune
        exception ne le signale.
        """
        import cv2

        capture = cv2.VideoCapture(str(video_path))
        try:
            if not capture.isOpened():
                raise UnsupportedMediaError("Ce fichier n'a pas pu être ouvert comme une vidéo.")

            capture.set(cv2.CAP_PROP_POS_FRAMES, first_index)
            position = int(capture.get(cv2.CAP_PROP_POS_FRAMES))
            if position > first_index:
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                position = 0
            while position < first_index and capture.grab():
                position += 1
            if position != first_index:
                # La vidéo est plus courte que la borne demandée. Rendre un flux
                # vide plutôt que lever : c'est `AnalysisService` qui décide du
                # message, il connaît la durée **et** les deux bornes, là où
                # l'adaptateur ne verrait qu'une lecture qui s'arrête.
                logger.warning(
                    "déplacement impossible : la vidéo s'arrête avant la borne demandée",
                    wanted_index=first_index,
                    reached_index=position,
                )
                return

            logger.info(
                "analyse démarrée après déplacement",
                start_ms=round(spec.start_ms),
                first_index=first_index,
                frame_stride=stride,
            )

            index = first_index
            while True:
                ok, decoded = capture.read()
                if not ok:
                    return
                # `read()` est typé « n'importe quel dtype » par les stubs d'OpenCV.
                # Il rend en pratique du `uint8` BGR, exactement comme `orig_img` de
                # l'autre chemin — d'où le recadrage de type, et pas une conversion :
                # copier chaque image coûterait plus que toute la lecture.
                image = cast("npt.NDArray[np.uint8]", decoded)
                results = model.track(
                    source=image,
                    # Les **mêmes** arguments que le chemin sans déplacement, à
                    # l'unique exception de la source. Toute divergence ici ferait
                    # qu'un même tracé compterait différemment selon qu'on analyse
                    # depuis le début ou depuis une borne — précisément le genre
                    # d'écart que le partage des schémas de requête existe pour
                    # empêcher entre le différé et le direct.
                    persist=True,
                    tracker=str(self._tracker_for(spec)),
                    conf=detector_floor(),
                    iou=spec.iou,
                    classes=list(spec.class_ids),
                    agnostic_nms=True,
                    device=self._registry.device(),
                    half=self._registry.half(),
                    imgsz=self._imgsz,
                    verbose=False,
                )
                yield EngineFrame(
                    frame_index=index,
                    # Absolu, depuis le début du **fichier** : c'est ce qui fait
                    # qu'une fenêtre ne décale aucun horodatage.
                    timestamp_ms=index / info.fps * 1000.0,
                    image=image,
                    tracks=_to_observations(results[0]),
                )
                # `grab()` et non `read()` : les images sautées par le pas d'analyse
                # n'ont pas à être converties en tableau.
                for _ in range(stride - 1):
                    if not capture.grab():
                        return
                index += stride
        finally:
            capture.release()

    def open_stream(self, spec: EngineSpec) -> UltralyticsStream:
        """Ouvre un flux persistant pour le temps réel.

        Le bail reste ouvert jusqu'à `close()` : c'est ce qui fait d'une suite
        d'images un **flux** plutôt que des frames indépendantes.
        """
        # Pas de lot ici, et il n'y en aura jamais : en direct les images arrivent
        # une par une, et attendre d'en avoir plusieurs échangerait exactement ce
        # que ce mode vend — la latence — contre du débit dont il n'a que faire.
        return UltralyticsStream(self._registry, spec, self._tracker_for(spec), self._imgsz)


class UltralyticsStream:
    """Suivi image par image, avec état persistant entre les appels."""

    __slots__ = ("_imgsz", "_lease", "_model", "_registry", "_spec", "_tracker_config")

    def __init__(
        self,
        registry: ModelRegistry,
        spec: EngineSpec,
        tracker_config: Path,
        imgsz: int = DEFAULT_IMGSZ,
    ) -> None:
        self._registry = registry
        self._spec = spec
        self._imgsz = imgsz
        # Le même fichier qu'en différé, et c'est le point : les deux modes doivent
        # suivre avec la même configuration, sinon un même tracé ne donne pas les
        # mêmes chiffres selon qu'on rejoue un fichier ou qu'on filme.
        self._tracker_config = tracker_config
        # Le gestionnaire de contexte est conservé et fermé à la main : le bail
        # doit survivre à l'appel qui l'ouvre, contrairement à `iter_video`.
        self._lease = registry.lease(spec.model_id)
        self._model = self._lease.__enter__()
        # Une nouvelle session temps réel est une nouvelle scène : sans cette
        # remise à zéro, elle hériterait des pistes du job ou de la session
        # précédente sur la même instance de modèle. Voir `reset_trackers`.
        reset_trackers(self._model)

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
            tracker=str(self._tracker_config),
            # Le même plancher qu'en différé, et pour la même raison : les deux
            # modes doivent suivre à l'identique, sinon un même tracé ne donne pas
            # les mêmes chiffres selon qu'on rejoue un fichier ou qu'on filme.
            conf=detector_floor(),
            iou=self._spec.iou,
            classes=list(self._spec.class_ids),
            # Voir le mode différé : NMS inter-classes, sinon une camionnette
            # survit en `car` **et** en `truck` et compte deux fois.
            agnostic_nms=True,
            device=self._registry.device(),
            half=self._registry.half(),
            # La même taille d'entrée qu'en différé, et c'est un invariant du
            # projet : les deux modes partagent le code de comptage pour qu'un même
            # tracé donne les mêmes chiffres. Les faire détecter à deux résolutions
            # différentes romprait cette promesse là où personne ne la vérifie.
            imgsz=self._imgsz,
            verbose=False,
        )
        return _to_observations(results[0]) if results else ()

    def close(self) -> None:
        """Ferme le flux et **rend le bail**. Idempotent."""
        if self._lease is not None:
            self._lease.__exit__(None, None, None)
            self._lease = None  # type: ignore[assignment]


def reset_trackers(model: Any) -> None:  # noqa: ANN401 — un `YOLO` n'est pas typé
    """Repart d'un suivi vierge. **Obligatoire au début de chaque analyse.**

    Le bug que cette fonction supprime ne lève rien et ne se voit qu'en comptant.
    `persist=True` fait d'une suite d'images un flux — c'est ce qu'on veut *à
    l'intérieur* d'une vidéo — mais Ultralytics l'interprète aussi entre deux
    appels : `register_tracker` **sort immédiatement** quand des trackers existent
    déjà (`trackers/track.py`). Or le registre garde l'instance de modèle d'un job
    à l'autre (invariant 9 : un bail par usage, mais la même instance résidente).

    La deuxième analyse héritait donc des pistes, du filtre de Kalman et du
    compteur d'images de la première. Mesuré sur un même fichier **octet pour
    octet**, analysé trois fois de suite dans le même processus : **19, puis 26,
    puis 33 véhicules uniques**. Rien n'échoue, rien n'est journalisé, et les
    chiffres restent plausibles — ils dérivent simplement vers le haut à mesure
    que des pistes fantômes de la vidéo précédente s'associent aux détections de
    la suivante.

    `reset()` d'Ultralytics vide les pistes suivies, perdues et retirées, remet le
    compteur d'images à zéro, reconstruit le filtre de Kalman et **réinitialise le
    compteur d'identifiants** — c'est-à-dire tout ce qui doit repartir de zéro
    quand la scène change.

    Tolère un modèle sans prédicteur : au tout premier appel du processus, il n'y
    a pas encore de tracker à remettre à zéro, et ce n'est pas une anomalie.
    """
    predictor = getattr(model, "predictor", None)
    for tracker in getattr(predictor, "trackers", None) or ():
        tracker.reset()


def _to_observations(result: Any) -> tuple[TrackObservation, ...]:  # noqa: ANN401
    """Traduit un `Results` d'Ultralytics en vocabulaire du domaine.

    `boxes.id is None` est **normal** sur les premières frames : le tracker n'a
    encore rien confirmé. Ce n'est pas une erreur, et lever ici ferait échouer
    toute analyse dès sa première image (piège 33 de prompt/13).

    **Un seul rapatriement depuis le GPU.** La version précédente lisait `xyxy`,
    `id`, `cls` et `conf` séparément : quatre `.cpu()`, donc quatre
    synchronisations CUDA par image, là où le tenseur `data` les porte toutes
    ensemble. C'est le même contenu — `[x1, y1, x2, y2, id, conf, cls]` — en un
    transfert.
    """
    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.id is None:
        return ()

    names: dict[int, str] = getattr(result, "names", {}) or {}
    data = boxes.data.cpu().numpy()
    # Lever plutôt que découper à l'aveugle : les colonnes sont un contrat
    # d'Ultralytics, et une version qui en ajouterait une décalerait `conf` et
    # `cls` d'un cran. Le résultat ne serait pas une erreur mais des scores et des
    # classes faux — donc des véhicules comptés dans la mauvaise catégorie, sans
    # que rien ne le signale. Même raisonnement que le `strict=True` ci-dessous.
    if data.shape[-1] != TRACKED_BOX_COLUMNS:
        msg = (
            f"`boxes.data` porte {data.shape[-1]} colonnes au lieu de "
            f"{TRACKED_BOX_COLUMNS} : la disposition "
            "[x1, y1, x2, y2, id, conf, cls] d'Ultralytics a changé."
        )
        raise RuntimeError(msg)

    observations: list[TrackObservation] = []
    for x1, y1, x2, y2, track_id, score, class_id in data:
        label_id = int(class_id)
        observations.append(
            TrackObservation(
                track_id=int(track_id),
                class_id=label_id,
                label=names.get(label_id, str(label_id)),
                score=float(score),
                box=BoundingBox(
                    x=float(x1), y=float(y1), width=float(x2 - x1), height=float(y2 - y1)
                ),
            )
        )
    return tuple(observations)
