"""Adaptateur Ultralytics — **le seul importateur d'`ultralytics` du projet**.

C'est ici, et nulle part ailleurs, que `Results`/`Boxes`/`xyxy` deviennent des
`TrackObservation` du domaine. Un test d'architecture le vérifie.

Le temps de scène est vrai **par construction** : `timestamp_ms` vient de
`frame_index / fps`, jamais d'une horloge. Introduire `time.time()` ici casserait
d'un coup les débits, les vitesses et les gates de ré-identification.
"""

from __future__ import annotations

import os
import queue
import tempfile
import threading
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

#: Mémoire d'images décodées **en vol** au plus, en octets.
#:
#: Bornée en octets et non en images, et c'est tout l'objet du réglage : une image
#: 4K pèse 24,9 Mo contre 2,8 en 720p, donc « quatre images en avance » veut dire
#: neuf fois plus de mémoire d'un cas à l'autre. Une file profonde n'apporte
#: d'ailleurs rien de plus qu'un lot d'avance — c'est le lot d'avance qui recouvre
#: le décodage avec l'inférence ; le reste ne sert qu'à absorber la gigue.
#:
#: 128 Mo laissent une douzaine de lots d'avance en 720p et **un seul** en 4K, ce
#: qui suffit au recouvrement dans les deux cas.
DECODE_BUDGET_BYTES = 128 * 1024 * 1024

#: Attente maximale d'un dépôt dans la file, en secondes.
#:
#: Le producteur ne bloque **jamais** indéfiniment : il redemande la permission de
#: continuer à chaque expiration. C'est ce qui garantit qu'un consommateur qui
#: s'arrête au milieu — une fenêtre d'analyse qui atteint sa borne, une annulation —
#: ne laisse pas un fil de décodage vivant sur un fichier ouvert.
DECODE_PUT_TIMEOUT_S = 0.05

#: Sentinelle de fin de flux. Un objet privé, jamais `None` : `None` est une valeur
#: qu'un jour quelqu'un mettra légitimement dans la file.
_DECODE_DONE = object()

type _DecodedFrame = tuple[int, npt.NDArray[np.uint8]]
type _DecodedBatch = list[_DecodedFrame]

# `parents[5]` mène à `backend/` : infrastructure → models_registry → features →
# traffic_analysis → src → backend. Compté à la main, ce décalage a été **faux**
# (`parents[4]`, donc `backend/src/config/`) et l'erreur ne se voyait qu'à
# l'exécution d'une vraie analyse : les tests injectent un `FakeEngine` et ne
# passent jamais ici. D'où le test d'existence ci-dessous, qui échoue au
# chargement du module plutôt qu'au milieu d'un job.
CONFIG_DIR = Path(__file__).resolve().parents[5] / "config"
TRACKER_CONFIG = CONFIG_DIR / "botsort_reid.yaml"


def _base_tracker() -> dict[str, Any]:
    """Le fichier de suivi versionné, lu une fois par processus."""
    return _tracker_file(TRACKER_CONFIG)


def detector_floor(confidence: float) -> float:
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

    **Le plancher suit le curseur quand celui-ci descend, et c'est un correctif.**
    Il était figé à la valeur du fichier de base (0,10), ce qui défaisait le
    mécanisme ci-dessus à l'autre bout de la plage :

    - **sous 0,10, le curseur était mort.** Le détecteur ne rendait jamais une
      boîte à 0,07, donc rien ne pouvait ni créer ni prolonger une piste en dessous
      du plancher figé. L'utilisateur qui descend le curseur pour récupérer des
      petits objets — une moto, le plus petit gabarit COCO — ne voyait strictement
      rien changer ;
    - **pire, la bande basse devenait vide.** À confiance 0,05, le fichier dérivé
      portait `track_high_thresh = 0,05` sous un `track_low_thresh = 0,10` resté
      au niveau du fichier de base : l'ensemble `low < s < high` est alors vide, la
      seconde association redevenait du code mort, et toute cette docstring cessait
      d'être vraie sans qu'aucun message ne le dise.

    **Le rapport de bande vient du fichier versionné lui-même** (`0,10 / 0,25`), et
    non d'un nombre inventé ici : c'est l'écart que le déploiement a déjà choisi
    entre « prolonger » et « créer ». Conséquence à connaître — `min` avec le
    plancher de base signifie que **rien ne change au-dessus de `track_high_thresh`
    du fichier**, donc rien ne change au défaut de 0,35 ni nulle part au-dessus de
    0,25. Seul le bas de la plage descend, là où le curseur ne servait à rien.

    `low < confidence` reste vrai sur toute la plage du contrat, quel que soit le
    rapport, et un test le vérifie valeur par valeur.
    """
    base = _base_tracker()
    base_low = float(base["track_low_thresh"])
    base_high = float(base["track_high_thresh"])
    band_ratio = base_low / base_high if base_high > 0 else 1.0
    return min(base_low, confidence * band_ratio)


#: Les clés de requête qui portent le seuil **de l'utilisateur**, tel quel.
REQUEST_HIGH_KEYS = frozenset({"track_high_thresh", "new_track_thresh"})

#: Les clés du fichier de suivi qui viennent de la **requête**, donc qui changent
#: d'une analyse à l'autre dans un même processus.
#:
#: Nommées ici plutôt qu'écrites deux fois : `resolved_tracker_config` les écrit
#: dans le fichier dérivé, et `reset_trackers` doit les reposer sur un tracker déjà
#: construit — Ultralytics ne relisant jamais le fichier une fois ses trackers en
#: place. Deux listes divergeraient sur un réglage annoncé et sans effet.
#:
#: `track_low_thresh` en fait partie **depuis que le plancher suit le curseur** : il
#: est calculé à partir du seuil de la requête, donc il change avec elle, donc il
#: doit être reposé comme les deux autres. L'oublier redonnerait la panne exacte
#: qu'il corrige, à la deuxième analyse d'un processus.
REQUEST_TRACKER_KEYS = REQUEST_HIGH_KEYS | frozenset({"track_low_thresh"})

#: Les clés que le tracker relit **à chaque image**, sur `self.args`.
#:
#: Vérifié dans la roue installée (`trackers/byte_tracker.py`, `bot_sort.py`) : ce
#: sont les seules qu'on puisse changer sur un tracker déjà construit. Toutes les
#: autres — `track_buffer`, `gmc_method`, `with_reid`, `proximity_thresh`… — sont
#: consommées dans `__init__` et gravées dans l'objet.
#:
#: `REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` est **la** condition qui rend
#: `reset_trackers` suffisante, et un test la verrouille : le jour où un réglage de
#: requête toucherait une clé consommée à la construction, il faudrait reconstruire
#: le tracker et pas seulement reposer ses arguments.
LIVE_TRACKER_KEYS = frozenset(
    {
        "track_high_thresh",
        "track_low_thresh",
        "new_track_thresh",
        "match_thresh",
        "fuse_score",
    }
)


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
    overrides: dict[str, Any] = {"gmc_method": gmc_method}
    overrides.update(dict.fromkeys(REQUEST_HIGH_KEYS, high_thresh))
    # **Le plancher est écrit ici aussi, et il n'a pas la même valeur.** Il vaut le
    # plancher du fichier de base tant que le seuil reste haut, et descend avec lui
    # en dessous — sans quoi le fichier dérivé porterait un `track_low_thresh`
    # supérieur à son `track_high_thresh` et la bande basse serait vide. Voir
    # `detector_floor`, qui est le seul juge de cette valeur.
    overrides["track_low_thresh"] = detector_floor(high_thresh)
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
            # **Le plancher DE BASE**, nommé pour ce qu'il est : celui d'une course
            # dépend de son seuil de confiance, donc il n'est pas connu ici. Écrire
            # « detector_floor » tout court annoncerait un plancher que la plupart
            # des courses n'utilisent pas — exactement le genre de journal qui fait
            # chercher la panne au mauvais endroit.
            detector_floor_base=_base_tracker()["track_low_thresh"],
            imgsz=self._imgsz,
            batch=self._batch,
        )

    def _tracker_for(self, spec: EngineSpec) -> Path:
        """Le fichier de suivi de cette course : mouvement de déploiement, seuil de requête."""
        tracker_config = resolved_tracker_config(self._gmc, spec.confidence)
        # Journalisé **par course** parce que ces trois valeurs sont exactement ce
        # qu'on vient regarder quand un seuil semble sans effet : le curseur, ce que
        # le détecteur laisse passer, et le fichier qui les porte.
        logger.info(
            "suivi résolu",
            confidence=spec.confidence,
            detector_floor=detector_floor(spec.confidence),
            tracker=str(tracker_config),
        )
        return tracker_config

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

        **Un seul chemin, et le décodage vit dans un fil séparé.** Il y en avait deux
        — le chargeur d'Ultralytics sans borne de début, un décodage maison image par
        image avec borne — et ils partageaient le même défaut : le décodage attendait
        l'inférence de l'image précédente. Or c'est **tout** ce que la résolution
        coûte. Mesuré au banc (`scripts/pipeline_bench.py --ladder`), même scène
        réencodée à quatre paliers, yolov8n, GPU :

        | palier | img/s | décodage | inférence |
        |---|---|---|---|
        | 720p  | 58,5 | 3,2 ms | 8,0 ms |
        | 1080p | 47,0 | 6,9 ms | 8,0 ms |
        | 1440p | 35,4 | 12,6 ms | 8,0 ms |
        | 2160p | 27,0 | 21,7 ms | 8,0 ms |

        L'inférence ne bouge pas d'un dixième — l'entrée du réseau vaut 640 quelle que
        soit la source — et le décodage suit le nombre de pixels. Le décodage nu,
        chronométré séparément sur le même fichier, donne 20,9 ms : la colonne
        obtenue par différence **est** le décodage, ce n'est pas une supposition.

        Le décodage étant du travail CPU pendant que la carte attend, un fil et un lot
        d'avance suffisent à le faire disparaître du chemin critique. Le plafond
        devient `max(décodage, GPU)` au lieu de leur somme.

        Ce que le fil ne change pas, et qu'il ne faut pas casser : `frame_index` est
        l'index **dans le fichier**, donc `timestamp_ms` reste du temps de scène
        absolu. Une fenêtre ne décale aucun horodatage.

        **Les images partent en lot, comme avant.** `LoadImagesAndVideos` remplissait
        un lot d'images consécutives ; nous le remplissons nous-mêmes et le passons en
        liste. Vérifié dans la roue installée (`trackers/track.py`) : hors mode
        `stream`, Ultralytics ne crée **qu'un** tracker et l'applique aux résultats
        dans l'ordre d'entrée. Le lot reste donc neutre pour le suivi — et le chemin
        avec borne de début, qui n'en avait aucun, en gagne un.
        """
        info = self.probe(video_path)
        stride = max(1, spec.frame_stride)
        first_index = _first_analysed_index(spec.start_ms, info.fps, stride)
        if first_index > 0:
            logger.info(
                "analyse démarrée après déplacement",
                start_ms=round(spec.start_ms),
                first_index=first_index,
                frame_stride=stride,
            )

        tracker_config = self._tracker_for(spec)
        with self._registry.lease(spec.model_id) as model:
            # Le fichier **et** le nettoyage : Ultralytics ne relit pas le premier
            # une fois ses trackers en place, donc le seuil de cette requête-ci
            # n'arriverait jamais jusqu'au tracker. Voir `reset_trackers`.
            reset_trackers(model, tracker_config)
            batches = decode_ahead(
                video_path,
                stride=stride,
                first_index=first_index,
                batch=self._batch,
                frame_bytes=max(1, info.width * info.height * 3),
            )
            for chunk in batches:
                results = model.track(
                    source=[image for _, image in chunk],
                    tracker=str(tracker_config),
                    # **Le plancher du détecteur, pas le seuil de l'utilisateur.** Ce
                    # dernier est passé au tracker comme `track_high_thresh` /
                    # `new_track_thresh` : la création de pistes reste à son niveau,
                    # mais les détections faibles atteignent enfin la seconde
                    # association, qui prolonge une piste dont la confiance plonge.
                    # Voir `detector_floor` pour la panne que cela corrige.
                    conf=detector_floor(spec.confidence),
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
                    persist=True,
                    verbose=False,
                )
                # `strict=True` : Ultralytics promet un résultat par image d'entrée,
                # dans l'ordre. S'il en rendait un de moins, tout le reste du lot
                # serait décalé d'un cran — donc des boîtes rattachées à la mauvaise
                # image, avec des horodatages plausibles et faux.
                for (index, image), result in zip(chunk, results, strict=True):
                    yield EngineFrame(
                        frame_index=index,
                        # Temps de scène, vrai par construction.
                        timestamp_ms=index / info.fps * 1000.0,
                        image=image,
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
        # précédente sur la même instance de modèle. Et sans le fichier en second
        # argument, elle hériterait aussi de son **seuil** — le direct partage
        # l'instance résidente avec le différé. Voir `reset_trackers`.
        reset_trackers(self._model, tracker_config)

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
            conf=detector_floor(self._spec.confidence),
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


def decode_ahead(
    video_path: Path,
    *,
    stride: int,
    first_index: int,
    batch: int,
    frame_bytes: int,
    budget_bytes: int = DECODE_BUDGET_BYTES,
) -> Iterator[_DecodedBatch]:
    """Décode dans un fil séparé et rend des lots d'images consécutives.

    **Le seul gain que ce fil apporte est un recouvrement**, pas une accélération du
    décodage : celui-ci coûte exactement la même chose, il ne coûte plus *en plus* de
    l'inférence. C'est ce qui rend la cadence indépendante de la résolution jusqu'au
    point où le décodage devient lui-même le plus lent des deux — voir la docstring
    d'`iter_video` pour le tableau des mesures.

    Trois propriétés à ne pas casser, chacune payée par un mode de panne :

    - **le fil meurt avec le générateur.** `AnalysisService` sort de sa boucle sur la
      borne de fin d'une fenêtre et sur une annulation ; le générateur est alors
      fermé. Sans le `finally` ci-dessous, chaque job borné ou annulé laisserait un
      fil vivant sur un décodeur ouvert — invisible, jusqu'à épuiser les descripteurs
      ou la mémoire du serveur ;
    - **le producteur ne bloque jamais indéfiniment.** Il redemande la permission de
      continuer à chaque expiration de `put`, donc il voit l'arrêt même quand la file
      est pleine et que plus personne ne lit ;
    - **une exception du décodage traverse.** Elle est déposée dans la file et relevée
      dans le fil appelant, à l'endroit où l'appelant l'attend. Un fil qui meurt en
      silence rendrait un flux vide, c'est-à-dire une analyse « réussie » et vide.

    La file est bornée en **octets** (`budget_bytes`) : une image 4K pèse neuf fois
    une image 720p, donc un nombre de lots fixe donnerait deux empreintes mémoire
    incomparables. Un lot d'avance suffit au recouvrement ; le reste absorbe la gigue.
    """
    per_batch = max(1, frame_bytes * max(1, batch))
    pending: queue.Queue[object] = queue.Queue(maxsize=max(1, budget_bytes // per_batch))
    stop = threading.Event()

    def offer(item: object) -> bool:
        """Dépose `item`, ou renonce si l'appelant a cessé de lire."""
        while not stop.is_set():
            try:
                pending.put(item, timeout=DECODE_PUT_TIMEOUT_S)
            except queue.Full:
                continue
            return True
        return False

    def produce() -> None:
        try:
            for chunk in _batched(
                _iter_decoded(video_path, stride=stride, first_index=first_index), batch
            ):
                if not offer(chunk):
                    return
            offer(_DECODE_DONE)
        except BaseException as exc:
            # Toutes, sans distinction : une exception perdue dans un fil rendrait un
            # flux vide, c'est-à-dire une analyse « réussie » sans un seul véhicule.
            offer(exc)

    thread = threading.Thread(target=produce, name="traffic-decode", daemon=True)
    thread.start()
    try:
        while True:
            item = pending.get()
            if item is _DECODE_DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield cast("_DecodedBatch", item)
    finally:
        stop.set()
        # Vidée pour débloquer un producteur en attente : il verrait l'arrêt au bout
        # d'une expiration de toute façon, mais rendre la place immédiatement raccourcit
        # la fermeture d'autant, et une annulation doit être ressentie tout de suite.
        while True:
            try:
                pending.get_nowait()
            except queue.Empty:
                break
        thread.join(timeout=1.0)


def _iter_decoded(video_path: Path, *, stride: int, first_index: int) -> Iterator[_DecodedFrame]:
    """Décode la vidéo image par image, à partir de `first_index`, un sur `stride`.

    **Pur et sans fil**, pour être testable : c'est ici que vivent l'index et le
    déplacement, c'est-à-dire tout ce qui peut se tromper sans lever.

    Le déplacement se fait en deux temps, et le second n'est pas une précaution de
    style : `CAP_PROP_POS_FRAMES` est **approximatif** sur plusieurs conteneurs —
    FFmpeg se pose sur l'image-clé précédente, et certains démultiplexeurs dépassent
    la cible. On lit donc la position réellement atteinte, on repart de zéro si elle
    a dépassé, puis on avance par `grab()`, qui démultiplexe sans convertir en
    tableau : quelques dizaines d'images de rattrapage coûtent bien moins qu'une
    seule inférence.

    Ce module a déjà payé une panne silencieuse de cette famille (le `parents[5]` de
    `CONFIG_DIR`) : un déplacement approximatif accepté sans vérification donnerait
    des `frame_index` faux, donc des horodatages faux, donc des vitesses et des
    franchissements datés à côté — sans qu'aucune exception ne le signale.
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
            # La vidéo est plus courte que la borne demandée. Rendre un flux vide
            # plutôt que lever : c'est `AnalysisService` qui décide du message, il
            # connaît la durée **et** les deux bornes, là où l'adaptateur ne verrait
            # qu'une lecture qui s'arrête.
            logger.warning(
                "déplacement impossible : la vidéo s'arrête avant la borne demandée",
                wanted_index=first_index,
                reached_index=position,
            )
            return

        index = first_index
        while True:
            ok, decoded = capture.read()
            if not ok:
                return
            # `read()` est typé « n'importe quel dtype » par les stubs d'OpenCV. Il
            # rend en pratique du `uint8` BGR, exactement ce qu'attend le modèle —
            # d'où le recadrage de type, et pas une conversion : copier chaque image
            # coûterait plus que toute la lecture.
            yield index, cast("npt.NDArray[np.uint8]", decoded)
            # `grab()` et non `read()` : les images sautées par le pas d'analyse
            # n'ont pas à être converties en tableau.
            for _ in range(stride - 1):
                if not capture.grab():
                    return
            index += stride
    finally:
        capture.release()


def _batched(frames: Iterator[_DecodedFrame], size: int) -> Iterator[_DecodedBatch]:
    """Regroupe les images par `size`, le dernier lot pouvant être plus court.

    `itertools.batched` ferait exactement cela — mais il rend des tuples, là où
    l'appelant construit une liste pour Ultralytics ; l'écrire ici évite une
    conversion par lot et laisse le type du lot explicite.
    """
    chunk: _DecodedBatch = []
    for frame in frames:
        chunk.append(frame)
        if len(chunk) >= max(1, size):
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def reset_trackers(model: Any, tracker_config: Path | None = None) -> None:  # noqa: ANN401
    """Repart d'un suivi vierge, **avec les réglages de cette analyse-ci**.

    Obligatoire au début de chaque analyse, et pour **deux** pannes distinctes qui
    ne lèvent ni l'une ni l'autre.

    **1. L'état hérité.** `persist=True` fait d'une suite d'images un flux — c'est
    ce qu'on veut *à l'intérieur* d'une vidéo — mais Ultralytics l'interprète aussi
    entre deux appels : `register_tracker` **sort immédiatement** quand des
    trackers existent déjà (`trackers/track.py`). Or le registre garde l'instance
    de modèle d'un job à l'autre (invariant 9 : un bail par usage, mais la même
    instance résidente).

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

    **2. Le réglage sans effet, et c'est « Confiance véhicules » qui le payait.**
    La même sortie anticipée de `register_tracker` fait que le fichier de suivi
    n'est **relu à aucun moment** une fois les trackers en place : le
    `tracker=…` passé à `track()` est ignoré. Or c'est là que voyage le seuil de
    l'utilisateur (`track_high_thresh` / `new_track_thresh`, ADR 0024). Toutes les
    analyses d'un processus tournaient donc au seuil de la **première** — le curseur
    bougeait, le fichier dérivé était bien écrit, le chemin bien journalisé, et rien
    ne changeait dans les chiffres. La cinquième panne silencieuse de ce module.

    On repose donc les clés de la requête sur les trackers vivants. C'est suffisant
    **parce que** `REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` : ces clés-là sont
    relues à chaque image sur `self.args`, jamais gravées à la construction. Les
    reposer plutôt que reconstruire les trackers évite d'avoir à désinscrire les
    rappels d'Ultralytics — l'appel de suivi suivant les ré-enregistrerait, et un
    `on_predict_postprocess_end` en double appellerait `tracker.update()` deux fois
    par image, ce qui serait bien pire que le bug corrigé.

    `tracker_config` à `None` = « ne rien reposer », pour un appelant qui n'a que
    l'état à nettoyer. Tolère un modèle sans prédicteur : au tout premier appel du
    processus, il n'y a pas encore de tracker, et ce n'est pas une anomalie — c'est
    même le seul cas où Ultralytics lira le fichier tout seul.
    """
    predictor = getattr(model, "predictor", None)
    trackers = getattr(predictor, "trackers", None) or ()
    for tracker in trackers:
        tracker.reset()
    if tracker_config is not None:
        _reapply_request_keys(trackers, tracker_config)


def _reapply_request_keys(trackers: Any, tracker_config: Path) -> None:  # noqa: ANN401
    """Repose les clés de requête du fichier sur des trackers déjà construits.

    Silencieuse sur un tracker sans `args` — une doublure de test, une version
    d'Ultralytics qui aurait changé de forme : ce serait alors le comportement
    d'avant ce correctif, jamais une analyse qui échoue. Le désaccord est en
    revanche **journalisé**, parce qu'un seuil qui ne descend pas est exactement ce
    qu'on vient de corriger et qu'il ne doit pas redevenir invisible.
    """
    if not trackers:
        return
    wanted = {
        key: value
        for key, value in _tracker_file(tracker_config).items()
        if key in REQUEST_TRACKER_KEYS
    }
    for tracker in trackers:
        args = getattr(tracker, "args", None)
        if args is None:
            logger.warning("tracker sans arguments : seuil de requête non reposé")
            continue
        for key, value in wanted.items():
            setattr(args, key, value)


@lru_cache(maxsize=32)
def _tracker_file(path: Path) -> dict[str, Any]:
    """Contenu d'un fichier de suivi, lu une fois par chemin et par processus."""
    import yaml

    loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


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
