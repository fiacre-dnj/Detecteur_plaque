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
from traffic_analysis.features.counting.application.ports import nms_class_groups

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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

#: Lots d'inférence d'avance, par défaut.
#:
#: `1` suffit : c'est le lot d'avance qui recouvre le moteur avec l'aval, pas la
#: profondeur de la file. Au-delà, on ne gagne plus rien et l'on retient des images
#: décodées **et** leurs résultats de suivi en mémoire.
DEFAULT_INFERENCE_PREFETCH = 1

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


def track_buffer_frames(max_lost_ms: float, fps: float, stride: int) -> int:
    """« Survie d'une piste perdue » (ms de scène) → `track_buffer` (images analysées).

    **Le seul juge de cette conversion, et il doit le rester.** Écrite deux fois elle
    divergerait, et la panne serait un tampon deux fois trop court sans qu'aucun
    message ne le dise — la piste repart alors sous un numéro neuf et le véhicule est
    compté deux fois.

    **Deux horloges qui ne se parlaient pas.** Le domaine abandonne une piste après
    `max_lost_ms` de temps de **scène** (`_release_lost`) ; le tracker après
    `track_buffer` images **analysées** (`byte_tracker.py`,
    `self.max_frames_lost = args.track_buffer`, sans aucune mise à l'échelle). Le
    fichier versionné annonçait un « miroir exact » qui n'était vrai qu'à 30 img/s et
    au pas 1 :

    - **à pas 3**, le domaine oublie à 2,5 s pendant que le tracker tient 7,5 s : il
      rend un `track_id` que le domaine ne reconnaît plus, `_advance_tracks` crée une
      piste neuve et `_number_tracks` émet un `global_id` neuf. Un véhicule compté
      deux fois, en silence ;
    - **à 60 img/s**, l'inverse : le tracker renonce à 1,25 s sous un curseur qui
      annonce 2,5.

    Le défaut retombe **exactement** sur la valeur du fichier de base — 2 500 ms à
    30 img/s au pas 1 donnent 75 — donc `resolved_tracker_config` n'écrit aucun
    fichier dérivé et rien ne change pour qui ne touche pas au curseur.

    Un plancher à 1 : un tampon nul ferait abandonner une piste à l'image même où elle
    disparaît, ce qui retirerait au tracker toute la tolérance qui justifie son
    existence. Une cadence inconnue rend `0`, que l'appelant lit comme « ne rien
    imposer », faute de pouvoir convertir.
    """
    if fps <= 0.0 or max_lost_ms <= 0.0:
        return 0
    return max(1, round(max_lost_ms / 1000.0 * fps / max(1, stride)))


@lru_cache(maxsize=1)
def _group_aware_predictor() -> type:
    """Le prédicteur qui découpe le NMS par famille de classes.

    Construit à l'appel et mis en cache : `ultralytics` n'est jamais importé au
    chargement de ce module, et la classe doit pourtant hériter du sien.

    **Ce qu'il change, et rien d'autre.** `postprocess` appelle
    `non_max_suppression` **une fois par famille** (`nms_class_groups`) au lieu
    d'une fois pour tout, en gardant le régime agnostique **à l'intérieur** de
    chaque appel. La suppression reste donc inter-classes là où deux classes
    décrivent le même objet physique — le piège 5 est intégralement préservé — et
    devient impossible entre un piéton et la moto qu'il conduit.

    Quatre points qui ne se devinent pas :

    - **une seule famille ⇒ on délègue au parent**, donc zéro différence, pas même
      un `clone`. C'est le cas du jeu de classes par défaut, et c'est ce qui rend le
      changement livrable sans réanalyser quoi que ce soit ;
    - **le tenseur brut DOIT être cloné à chaque appel.** `non_max_suppression` fait
      `prediction = prediction.transpose(-1, -2)` — une **vue** — puis
      `prediction[..., :4] = xywh2xyxy(...)`, donc elle convertit les boîtes **en
      place** dans le tenseur de l'appelant. Un second appel sur le même tenseur
      reconvertirait des xyxy en xyxy : des boîtes plausibles et fausses, sans la
      moindre erreur ;
    - **les résultats fusionnés sont retriés par score décroissant.** Concaténer
      trois familles rend un ordre par blocs, là où `torchvision.ops.nms` rend
      toujours un ordre décroissant. Le tracker n'a pas à connaître la différence, et
      c'est aussi ce qui rend la troncature à `max_det` honnête : elle doit couper
      les scores les plus bas, pas la dernière famille de la liste ;
    - **`end2end` et l'extraction de caractéristiques délèguent au parent.** Une tête
      `end2end` ne passe pas par le NMS du tout (`nms.py` sort en tête de fonction),
      donc il n'y a rien à découper ; `_feats` fait rendre des indices que la fusion
      ne saurait pas recoller.
    """
    from ultralytics.models.yolo.detect import DetectionPredictor
    from ultralytics.utils import nms

    class GroupAwareDetectionPredictor(DetectionPredictor):
        """NMS agnostique **dans** une famille de classes, jamais **entre** deux."""

        def postprocess(
            self,
            preds: Any,  # noqa: ANN401 — la signature du parent n'est pas typée
            img: Any,  # noqa: ANN401
            orig_imgs: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            groups = nms_class_groups(self.args.classes or ())
            if (
                len(groups) < 2
                or getattr(self, "_feats", None) is not None
                or getattr(self.model, "end2end", False)
            ):
                return super().postprocess(preds, img, orig_imgs, **kwargs)

            import torch

            # `pop` et non `get` : le parent le retire aussi, et `construct_results`
            # reçoit ensuite le reste des arguments.
            iou = kwargs.pop("iou", self.args.iou)
            raw = preds[0] if isinstance(preds, (list, tuple)) else preds
            per_group = [
                nms.non_max_suppression(
                    raw.clone(),
                    self.args.conf,
                    iou,
                    list(group),
                    self.args.agnostic_nms,
                    max_det=self.args.max_det,
                    nc=0 if self.args.task == "detect" else len(getattr(self.model, "names", ())),
                    end2end=False,
                    rotated=self.args.task == "obb",
                )
                for group in groups
            ]

            merged = []
            for index in range(len(per_group[0])):
                rows = torch.cat([group[index] for group in per_group], dim=0)
                order = rows[:, 4].argsort(descending=True)[: self.args.max_det]
                merged.append(rows[order])

            if not isinstance(orig_imgs, list):
                from ultralytics.utils import ops

                orig_imgs = ops.convert_torch2numpy_batch(orig_imgs)[..., ::-1]
            return self.construct_results(merged, img, orig_imgs, **kwargs)

    return GroupAwareDetectionPredictor


def install_group_aware_nms(model: Any) -> None:  # noqa: ANN401 — YOLO n'est pas typé
    """Fait porter le NMS par famille au prédicteur **déjà construit** du modèle.

    **Sans cela, le correctif serait entièrement inerte, en silence.** `predict()`
    ne construit son prédicteur qu'une fois par instance de modèle
    (`engine/model.py`, `if not self.predictor or …`), et `ModelRegistry` garde ses
    instances chargées d'un job à l'autre. Or le **préchauffage** appelle
    `model.predict()` au démarrage : le prédicteur par défaut est donc en place
    avant le premier `track()`, et l'argument `predictor=` de `predict()` est ignoré
    pour toute la vie du processus. C'est le mode de panne exact d'ADR 0035, et il
    est ici pire — la première analyse après un démarrage n'obéirait pas non plus.

    On échange donc la **classe de l'instance**, ce qui est légal entre deux classes
    de même disposition et n'ajoute aucun attribut : la famille se relit à chaque
    image sur `self.args.classes`.

    **Ne pas « simplifier » en posant `model.predictor = None`.** `track()` ferait
    `hasattr(self.predictor, "trackers")` → faux → `register_tracker` une seconde
    fois, et `model.callbacks` **empile** : un `on_predict_postprocess_end` en double
    appelle `tracker.update()` deux fois par image, soit des chiffres plausibles et
    complètement faux. Même raison que la note de `reset_trackers`.

    Le test de type est **exact** (`type(...) is`) : un prédicteur de segmentation ou
    de pose n'a rien à faire ici, et un prédicteur déjà échangé n'a rien à refaire.
    """
    from ultralytics.models.yolo.detect import DetectionPredictor

    predictor = getattr(model, "predictor", None)
    if predictor is not None and type(predictor) is DetectionPredictor:
        predictor.__class__ = _group_aware_predictor()


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

#: Clés du fichier **gravées à la construction**, et l'attribut d'instance qu'elles
#: alimentent. Une catégorie à part, et la première de son genre.
#:
#: `LIVE_TRACKER_KEYS` ne peut pas les couvrir : `reset()` ne les relit pas (vérifié à
#: l'exécution — `args.track_buffer = 450` puis `reset()` laisse `max_frames_lost` à
#: 75). Écrire la valeur dans le fichier dérivé ne suffit donc pas non plus, puisque
#: le fichier n'est relu à aucun moment une fois les trackers en place.
#:
#: Elles rompent la garantie que `REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` rendait
#: suffisante, et c'est pourquoi elles sont nommées ici plutôt que traitées au vol :
#: la prochaine lecture de ce module doit voir qu'il existe **deux** façons de
#: reposer un réglage, pas une.
ENGRAVED_TRACKER_ATTRS: dict[str, str] = {"track_buffer": "max_frames_lost"}


def head_is_end2end(model: Any) -> bool:  # noqa: ANN401
    """La tête de détection de ce modèle se passe-t-elle de NMS (`end2end`) ?

    **Demandé au graphe, jamais déduit du nom du fichier** — c'est l'invariant 10, et
    ici il n'est pas décoratif : `end2end` est une clé du *yaml de modèle*
    (`cfg/models/26/yolo26.yaml`), donc un poids réentraîné ou réexporté peut la
    porter sans s'appeler « yolo26 », et un fichier renommé peut s'appeler yolo26
    sans la porter. `Detect.end2end` est une propriété qui répond
    `hasattr(self, "one2one")` : elle est vraie si et seulement si le graphe a
    réellement la branche un-pour-un.

    Rend `False` quand la question n'a pas de réponse — une doublure de test, une
    version d'Ultralytics qui changerait de forme. C'est le repli **conservateur** :
    `False` laisse la ré-identification d'apparence active, c'est-à-dire le
    comportement d'avant ce correctif. Se tromper dans ce sens ne coûte que de la
    cadence sur un modèle exotique ; se tromper dans l'autre changerait des
    comptages sur toute la famille v8/11/12.
    """
    try:
        head = model.model.model[-1]
    except (AttributeError, IndexError, TypeError):
        return False
    return bool(getattr(head, "end2end", False))


@lru_cache(maxsize=32)
def resolved_tracker_config(
    gmc_method: str, high_thresh: float, appearance_reid: bool = True, track_buffer: int = 0
) -> Path:
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

    `appearance_reid=False` pose `with_reid: False`, et **c'est un réglage de
    matériel logiciel, pas de requête** : il ne dépend que de la forme de la tête du
    modèle choisi (voir `head_is_end2end` et ADR 0047). Sur une tête `end2end`,
    Ultralytics remplace `model: auto` par un `yolo26n-cls.pt` qu'il **télécharge**,
    puis exécute ce réseau de classification sur chaque recadrage de chaque image.
    Mesuré sur 1080p, `yolo26n` : le poste `tracker` passe de 1,33 à **45,19 ms** et
    l'analyse de 61,81 à **15,09 img/s**, soit 4,10× — pour des franchissements
    **identiques**. Le même réglage sur `yolov8n`, où l'encodeur reste la passe-plat
    du détecteur, coûte 0,91× (1,26 → 2,37 ms) : c'est le régime « quasi gratuit »
    qu'ADR 0013 avait mesuré et sur lequel il s'appuyait pour garder l'option.

    Le fichier de base reste à `with_reid: true` : la valeur par défaut ne change
    pour personne, seule la famille `end2end` est dérivée.

    `lru_cache` : un fichier par triplet (mouvement, seuil, apparence) et par
    processus. Le seuil vient de la requête, donc quelques valeurs distinctes au
    plus — d'où les 32 entrées, contre 8 quand seul le mouvement variait.
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
    # `0` veut dire « ne rien imposer » : le direct, qui n'a pas de cadence connue, et
    # tout appelant qui ne peut pas convertir. Le fichier de base garde alors sa valeur,
    # c'est-à-dire le comportement d'avant ADR 0058.
    if track_buffer > 0:
        overrides["track_buffer"] = track_buffer
    if not appearance_reid:
        # **Seul `with_reid` est posé, et pas `model`.** `build_encoder` sort sur le
        # premier argument : à `False`, la valeur de `model` n'est jamais lue, donc
        # la remettre à autre chose qu'`auto` serait un réglage sans effet — le pire
        # état d'un réglage (ADR 0016).
        overrides["with_reid"] = False
    if all(base.get(key) == value for key, value in overrides.items()):
        return TRACKER_CONFIG

    # L'apparence entre dans le nom : deux courses du même processus qui ne diffèrent
    # que par elle — un job `yolov8n` puis un job `yolo26n` — écriraient sinon dans le
    # même fichier, et la seconde emporterait la première pendant qu'elle tourne.
    # Le tampon entre dans le nom pour la même raison que l'apparence : deux courses
    # du même processus qui ne diffèrent que par lui écriraient sinon dans le même
    # fichier, et la seconde emporterait la première pendant qu'elle tourne.
    slug = (
        f"botsort-gmc-{gmc_method}-hi-{high_thresh:.2f}"
        f"-reid-{int(appearance_reid)}-buf-{track_buffer}.yaml"
    )
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

    __slots__ = ("_batch", "_gmc", "_imgsz", "_prefetch", "_registry")

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        gmc_method: str | None = None,
        imgsz: int = DEFAULT_IMGSZ,
        batch: int = 1,
        prefetch_batches: int = DEFAULT_INFERENCE_PREFETCH,
    ) -> None:
        """Les réglages de **déploiement** du moteur.

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
        self._prefetch = max(0, prefetch_batches)
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
            prefetch_batches=self._prefetch,
        )

    def _tracker_for(
        self,
        spec: EngineSpec,
        model: Any,  # noqa: ANN401
        track_buffer: int = 0,
    ) -> Path:
        """Le fichier de suivi de cette course : mouvement, seuil, apparence, tampon.

        **Le modèle est un argument parce que la réponse en dépend**, et il ne peut
        donc plus être résolu avant d'avoir pris le bail : c'est la tête du réseau
        chargé qui dit si la ré-identification d'apparence est gratuite ou si elle
        coûte une inférence par véhicule (`head_is_end2end`, ADR 0047).

        `track_buffer` vaut `0` par défaut — « ne rien imposer » — parce que le
        **direct** appelle ce résolveur sans pouvoir le calculer : un flux caméra n'a
        pas de cadence déclarée, et la conversion ms → images en demande une.
        """
        appearance_reid = not head_is_end2end(model)
        tracker_config = resolved_tracker_config(
            self._gmc, spec.confidence, appearance_reid, track_buffer
        )
        # Journalisé **par course** parce que ces valeurs sont exactement ce qu'on
        # vient regarder quand un seuil semble sans effet ou qu'une cadence s'écroule :
        # le curseur, ce que le détecteur laisse passer, l'apparence, et le fichier
        # qui les porte.
        logger.info(
            "suivi résolu",
            confidence=spec.confidence,
            detector_floor=detector_floor(spec.confidence),
            appearance_reid=appearance_reid,
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

        **Un second fil, un étage plus haut, depuis qu'il est mesuré.** Le décodage
        n'était pas le seul travail sérialisé avec le GPU : ce générateur est
        paresseux, donc le `track()` du modèle n'était appelé qu'une fois le *service*
        sorti de l'image précédente — détection de plaques, OCR, captures,
        apparence. `prefetch` fait avancer le suivi d'un lot pendant que l'aval
        travaille.

        **Le gain est petit et il fallait le mesurer pour le savoir** : 1,10× quand
        l'OCR tourne, 1,05× quand elle ne publie rien, **1,00× quand elle ne se
        déclenche jamais**. L'aval n'est pas du travail CPU à cacher derrière le
        GPU — il est *lui aussi* du GPU (détection de plaques : 22,0 ms par image
        dont 17,9 de passe avant), et deux flux CUDA sur une même carte se
        sérialisent. Seules les moitiés CPU se recouvrent. Voir
        `Settings.inference_prefetch_batches` pour le tableau complet.

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

        with self._registry.lease(spec.model_id) as model:
            # **Résolu à l'intérieur du bail**, et pas avant : le fichier de suivi
            # dépend de la forme de la tête du modèle chargé (`head_is_end2end`).
            #
            # Le tampon se calcule ici parce que c'est ici que la cadence est connue :
            # `max_lost_ms` est du temps de scène, `track_buffer` un nombre d'images
            # analysées, et seul cet endroit tient les deux bouts (ADR 0058).
            tracker_config = self._tracker_for(
                spec, model, track_buffer_frames(spec.max_lost_ms, info.fps, stride)
            )
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
            # `yield from` et non une boucle `for` : c'est lui qui **ferme** le flux
            # de préchargement quand l'appelant referme celui-ci — une annulation,
            # une borne de fin de fenêtre. Une boucle laisserait le fil d'inférence
            # au ramasse-miettes, donc vivant sur le modèle après la sortie du
            # `with` qui rend le bail (invariant 9).
            yield from prefetch(
                self._tracked_batches(model, batches, spec, tracker_config, info.fps),
                depth=self._prefetch,
                name="traffic-inference",
            )

    def _tracked_batches(
        self,
        model: Any,  # noqa: ANN401 — YOLO n'est pas typé
        batches: Iterator[_DecodedBatch],
        spec: EngineSpec,
        tracker_config: Path,
        fps: float,
    ) -> Iterator[EngineFrame]:
        """Suit lot par lot. **Extrait de `iter_video` pour être recouvrable.**

        Tant que ce code vivait dans le corps du générateur public, il était
        indissociable du `yield` que le consommateur pilote : chaque `track()` du modèle
        n'avait lieu qu'une fois l'aval du service terminé sur l'image précédente.
        Isolé, il devient un flux que `prefetch` peut faire avancer d'un lot pendant
        que le service travaille — sans qu'un seul appel change d'ordre ni
        d'argument.

        `batches` est fermée explicitement : elle tient le fil de décodage, et la
        fermeture en cascade d'une boucle `for` passe par le ramasse-miettes.
        """
        try:
            yield from self._track_batches(model, batches, spec, tracker_config, fps)
        finally:
            close = getattr(batches, "close", None)
            if close is not None:
                close()

    def _track_batches(
        self,
        model: Any,  # noqa: ANN401 — YOLO n'est pas typé
        batches: Iterator[_DecodedBatch],
        spec: EngineSpec,
        tracker_config: Path,
        fps: float,
    ) -> Iterator[EngineFrame]:
        """Le suivi proprement dit, sans la fermeture du décodage."""
        # Le préchauffage a déjà construit le prédicteur par défaut sur cette
        # instance résidente : `predictor=` ci-dessous serait donc ignoré, et le
        # découpage du NMS par famille n'aurait jamais lieu. Voir
        # `install_group_aware_nms`.
        install_group_aware_nms(model)
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
                # deux identités, et compte deux fois.
                #
                # **Mais il ne doit ignorer la classe qu'À L'INTÉRIEUR d'une famille
                # d'objets physiquement exclusifs**, et c'est ADR 0057. La prémisse
                # écrite ici — « nos quatre classes sont mutuellement exclusives sur
                # un objet physique » — a cessé d'être vraie le jour où `person` et
                # `bicycle` sont devenues cochables : un pilote et sa moto sont deux
                # objets réels, et l'agnostique effaçait le moins sûr des deux.
                # `predictor` découpe donc l'appel par famille (`nms_class_groups`),
                # et ce drapeau garde son sens **dans** chaque famille.
                agnostic_nms=True,
                # Le cas « aucun prédicteur encore construit » — préchauffage
                # désactivé. Quand il en existe déjà un, `predict()` ignore cet
                # argument et c'est `install_group_aware_nms` qui a fait le travail.
                # Les deux sont nécessaires ; aucun ne suffit.
                predictor=_group_aware_predictor(),
                device=self._registry.device(),
                half=self._registry.half(),
                # **La requête d'abord, le déploiement en repli.** C'est le seul
                # réglage de `EngineSpec` qui ne soit pas un simple indice : ce n'est
                # pas la taille d'un objet dans la vidéo qui décide qu'il est détecté,
                # c'est sa taille ici (ADR 0060).
                imgsz=spec.imgsz or self._imgsz,
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
                    timestamp_ms=index / fps * 1000.0,
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
        # Le *résolveur* et non le fichier : le flux doit prendre son bail avant de
        # pouvoir demander au modèle la forme de sa tête. Voir `_tracker_for`.
        return UltralyticsStream(self._registry, spec, self._tracker_for, self._imgsz)


class UltralyticsStream:
    """Suivi image par image, avec état persistant entre les appels."""

    __slots__ = ("_imgsz", "_lease", "_model", "_registry", "_spec", "_tracker_config")

    def __init__(
        self,
        registry: ModelRegistry,
        spec: EngineSpec,
        resolve_tracker: Callable[[EngineSpec, Any], Path],
        imgsz: int = DEFAULT_IMGSZ,
    ) -> None:
        self._registry = registry
        self._spec = spec
        self._imgsz = imgsz
        # Le gestionnaire de contexte est conservé et fermé à la main : le bail
        # doit survivre à l'appel qui l'ouvre, contrairement à `iter_video`.
        self._lease = registry.lease(spec.model_id)
        self._model = self._lease.__enter__()
        # **Après le bail**, parce que résoudre le fichier demande d'interroger la
        # tête du modèle chargé. Le résolveur est celui du moteur différé, donc les
        # deux modes suivent avec la même configuration — c'est le point : sinon un
        # même tracé ne donne pas les mêmes chiffres selon qu'on rejoue un fichier
        # ou qu'on filme.
        self._tracker_config = resolve_tracker(spec, self._model)
        # Une nouvelle session temps réel est une nouvelle scène : sans cette
        # remise à zéro, elle hériterait des pistes du job ou de la session
        # précédente sur la même instance de modèle. Et sans le fichier en second
        # argument, elle hériterait aussi de son **seuil** — le direct partage
        # l'instance résidente avec le différé. Voir `reset_trackers`.
        reset_trackers(self._model, self._tracker_config)
        # Le direct partage l'instance résidente avec le différé : sans cet appel,
        # il compterait un motard pour un seul objet là où le différé en compte deux.
        install_group_aware_nms(self._model)

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
            # Voir le mode différé : NMS inter-classes **dans une famille**, sinon
            # une camionnette survit en `car` et en `truck` et compte deux fois —
            # mais un pilote et sa moto ne se suppriment jamais (ADR 0057).
            agnostic_nms=True,
            predictor=_group_aware_predictor(),
            device=self._registry.device(),
            half=self._registry.half(),
            # La même taille d'entrée qu'en différé, et c'est un invariant du
            # projet : les deux modes partagent le code de comptage pour qu'un même
            # tracé donne les mêmes chiffres. Les faire détecter à deux résolutions
            # différentes romprait cette promesse là où personne ne la vérifie.
            #
            # « La même » veut donc dire celle de **la requête** depuis ADR 0060, avec
            # le déploiement en repli — et non la constante du moteur, qui ferait
            # justement détecter les deux modes à deux résolutions différentes.
            imgsz=self._spec.imgsz or self._imgsz,
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


def prefetch[T](source: Iterator[T], *, depth: int, name: str) -> Iterator[T]:
    """Fait tourner `source` dans un fil et rend `depth` éléments d'avance.

    **Le jumeau de `decode_ahead`, un étage plus haut.** Celui-là décharge le
    décodage du chemin critique ; celui-ci décharge le *consommateur*. Le générateur
    de `iter_video` est paresseux : tant que personne ne réclamait l'image suivante,
    le `track()` du modèle n'était appelé qu'*après* que l'aval en ait fini avec la
    précédente — plaques, OCR, captures, apparence. Moteur et aval se relayaient donc,
    chacun laissant l'autre attendre.

    **Ce que le recouvrement rend, mesuré, est bien plus modeste que ce qu'on en
    attendait** : 1,10× quand l'OCR tourne, 1,05× quand elle ne publie rien, **1,00×
    quand elle ne se déclenche jamais**. L'hypothèse — un aval de travail CPU à
    cacher derrière le GPU du moteur — est fausse : l'aval est *lui aussi* du GPU
    (détection de plaques 22,0 ms par image, dont 17,9 de passe avant), et deux flux
    CUDA sur une même carte se sérialisent quoi qu'on fasse. Seules les moitiés CPU
    se recouvrent — l'OCR d'onnxruntime, les recadrages, le domaine —, d'où un gain
    qui suit exactement la quantité d'OCR de la scène. Le tableau complet est dans
    `Settings.inference_prefetch_batches` ; à ne pas relire comme une accélération
    générale, ce qu'il n'est pas.

    **Aucun chiffre ne change.** L'ordre des appels au modèle, l'état du tracker et
    l'ordre des images rendues sont exactement ceux d'avant ; seul l'*instant* où le
    travail a lieu change. C'est la propriété qui rend ce changement livrable, et
    `depth=0` rend le chemin séquentiel à l'identique pour le prouver.

    Trois propriétés à ne pas casser, les mêmes que pour `decode_ahead` — plus une
    qui lui est propre :

    - **le fil meurt avec le générateur**, et `source` est fermée explicitement :
      c'est elle qui tient le fil de décodage, qui resterait sinon vivant sur un
      fichier ouvert jusqu'au ramasse-miettes ;
    - **le producteur ne bloque jamais indéfiniment** sur une file pleine ;
    - **une exception traverse**, relevée dans le fil appelant ;
    - **le `join` n'est PAS borné.** L'appelant est `iter_video`, sous un bail de
      modèle : rendre la main pendant qu'un `track()` tourne encore relâcherait le
      bail sous une inférence en vol, et deux jobs partageraient une instance —
      invariant 9, c'est-à-dire des chiffres plausibles et faux. Le producteur ne
      peut pas se bloquer durablement (il n'attend que `source`, elle-même bornée,
      ou un dépôt qu'il réessaie), donc l'attente est toujours celle d'un lot.
    """
    if depth <= 0:
        yield from source
        return

    pending: queue.Queue[object] = queue.Queue(maxsize=depth)
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
            for item in source:
                if not offer(item):
                    return
            offer(_DECODE_DONE)
        except BaseException as exc:
            offer(exc)
        finally:
            close = getattr(source, "close", None)
            if close is not None:
                close()

    thread = threading.Thread(target=produce, name=name, daemon=True)
    thread.start()
    try:
        while True:
            item = pending.get()
            if item is _DECODE_DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield cast("T", item)
    finally:
        stop.set()
        # Vidée pour débloquer un producteur en attente, comme dans `decode_ahead`.
        while True:
            try:
                pending.get_nowait()
            except queue.Empty:
                break
        thread.join()


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
        _reapply_engraved_keys(trackers, tracker_config)


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


def _reapply_engraved_keys(trackers: Any, tracker_config: Path) -> None:  # noqa: ANN401
    """Repose les clés **gravées à la construction**, sur l'attribut qu'elles ont
    alimenté.

    Une catégorie distincte de `_reapply_request_keys`, et il faut la garder distincte :
    celle-là écrit sur `tracker.args`, que le tracker relit à chaque image ; celle-ci
    écrit sur l'**instance**, parce que `args.track_buffer` n'est plus jamais lu après
    `__init__` — vérifié à l'exécution, `args.track_buffer = 450` puis `reset()` laisse
    `max_frames_lost` à 75.

    Sans elle, `track_buffer` serait correctement écrit dans le fichier dérivé,
    correctement journalisé, et sans le moindre effet à partir de la **deuxième**
    analyse d'un processus : le patron exact d'ADR 0035, sur le réglage que ce
    correctif existe pour brancher.

    Silencieuse sur une valeur absente du fichier — le cas normal du direct, qui
    n'impose aucun tampon — et journalisée sur un tracker sans l'attribut attendu,
    parce qu'un réglage qui redevient inerte ne doit pas le redevenir en silence.
    """
    if not trackers:
        return
    content = _tracker_file(tracker_config)
    for key, attribute in ENGRAVED_TRACKER_ATTRS.items():
        value = content.get(key)
        if value is None:
            continue
        for tracker in trackers:
            if not hasattr(tracker, attribute):
                logger.warning(
                    "tracker sans l'attribut attendu : réglage gravé non reposé",
                    key=key,
                    attribute=attribute,
                )
                continue
            setattr(tracker, attribute, value)


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
