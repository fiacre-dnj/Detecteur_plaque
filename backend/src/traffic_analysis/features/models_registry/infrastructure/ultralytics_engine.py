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
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


@lru_cache(maxsize=8)
def resolved_tracker_config(gmc_method: str) -> Path:
    """Chemin du tracker à utiliser, compensation de mouvement imposée.

    Ultralytics ne prend sa configuration de suivi **que** sous forme de chemin de
    fichier : il n'existe aucune façon de lui passer un réglage en mémoire. Rendre
    `gmc_method` réglable demande donc d'écrire un fichier dérivé — c'est ce que
    fait cette fonction, et c'est tout ce qu'elle fait.

    Quand le réglage et le fichier de base disent déjà la même chose, **le fichier
    de base est rendu tel quel** : pas de copie, pas de fichier temporaire, et le
    chemin journalisé reste celui que le dépôt versionne. C'est le cas courant.

    L'écriture est atomique (fichier temporaire puis `replace`) parce que deux
    processus peuvent démarrer en même temps — un rechargement `--reload` en
    développement suffit — et qu'un fichier YAML lu à moitié écrit ferait échouer
    une analyse avec un message parlant de syntaxe, très loin de la cause.

    `lru_cache` : le fichier est écrit une fois par valeur et par processus. La
    valeur ne change pas en cours d'exécution, `Settings` étant `frozen`.
    """
    import yaml

    base: dict[str, Any] = yaml.safe_load(TRACKER_CONFIG.read_text(encoding="utf-8"))
    if base.get("gmc_method") == gmc_method:
        return TRACKER_CONFIG

    target = Path(tempfile.gettempdir()) / "traffic-analysis" / f"botsort-gmc-{gmc_method}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    staging.write_text(
        yaml.safe_dump({**base, "gmc_method": gmc_method}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    staging.replace(target)
    return target


class UltralyticsEngine:
    """Détection et suivi par Ultralytics, derrière le port du domaine."""

    __slots__ = ("_batch", "_imgsz", "_registry", "_tracker_config")

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
        self._tracker_config = (
            TRACKER_CONFIG if gmc_method is None else resolved_tracker_config(gmc_method)
        )
        logger.info(
            "moteur configuré",
            gmc=gmc_method or "fichier de base",
            tracker=str(self._tracker_config),
            imgsz=self._imgsz,
            batch=self._batch,
        )

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
        """
        info = self.probe(video_path)
        stride = max(1, spec.frame_stride)

        with self._registry.lease(spec.model_id) as model:
            reset_trackers(model)
            results = model.track(
                source=str(video_path),
                stream=True,
                tracker=str(self._tracker_config),
                conf=spec.confidence,
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

    def open_stream(self, spec: EngineSpec) -> UltralyticsStream:
        """Ouvre un flux persistant pour le temps réel.

        Le bail reste ouvert jusqu'à `close()` : c'est ce qui fait d'une suite
        d'images un **flux** plutôt que des frames indépendantes.
        """
        # Pas de lot ici, et il n'y en aura jamais : en direct les images arrivent
        # une par une, et attendre d'en avoir plusieurs échangerait exactement ce
        # que ce mode vend — la latence — contre du débit dont il n'a que faire.
        return UltralyticsStream(self._registry, spec, self._tracker_config, self._imgsz)


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
            conf=self._spec.confidence,
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
