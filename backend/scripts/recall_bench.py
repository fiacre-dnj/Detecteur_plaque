"""Banc de rappel par classe — combien de motos et de piétons la chaîne laisse tomber ?

    cd backend
    # Ce que le domaine reçoit réellement, contre un gros modèle pris pour vérité.
    uv run python scripts/recall_bench.py --videos data/bench/motards.mp4 \
        --frames 400 --start 5 --classes 0,2,3,5,7 --json out/rappel.json
    # La même chose sans le tracker : sépare « jamais détecté » de « détecté puis jeté ».
    uv run python scripts/recall_bench.py --videos … --stage detector --json out/det.json
    # Inventaire : y a-t-il seulement des motos dans ce clip ?
    uv run python scripts/recall_bench.py --videos … --inventory

Ce banc existe parce qu'aucun des trois autres ne peut répondre à « on a du mal à
détecter les motos ». `pipeline_bench.py` ne rend que des **franchissements** par
classe — donc après le détecteur *et* le tracker *et* le compteur, et il n'a même pas
de `--classes`, si bien qu'il tourne toujours sur les quatre véhicules.
`anpr_bench.py` mesure la lecture de plaque. `audit_lignes.py` rejoue la géométrie sur
la timeline persistée, donc il est aveugle par construction à une non-détection : il ne
voit que ce que le détecteur a déjà rendu.

**Les deux étages, et c'est tout l'intérêt du banc.** Une moto absente de l'écran peut
l'être pour deux raisons qui appellent des gestes opposés :

- `--stage tracked` (défaut) fait tourner le **vrai** chemin de production,
  `engine.iter_video`, donc `detector_floor` + `agnostic_nms=True` + `imgsz` de
  déploiement + BoT-SORT. C'est ce que le domaine reçoit, et le seul chiffre qui
  décrive l'application ;
- `--stage detector` appelle `model.predict` avec **exactement les mêmes** arguments de
  détection, sans tracker. L'écart entre les deux étages **est** la perte du tracker.

Sans cette séparation, un rappel bas envoie régler le seuil de confiance alors que la
cause est l'association, ou l'inverse.

**La vérité n'est pas une vérité terrain, et il faut le dire.** C'est un gros modèle
(`yolo11x` à imgsz 1280, seuil bas) pris comme référence : il rate ce que tout YOLO
entraîné sur COCO rate — une moto de nuit, un piéton très occulté. Le chiffre rendu est
donc un rappel **relatif**, borne haute optimiste, exactement la précaution que
`reid_bench.py` pose pour son `rank1` et ADR 0029 pour son échelle synthétique. C'est
parfaitement valide pour la question posée : « que perd-on entre le gros modèle et le
nôtre, et où ». Ce n'est pas valide pour annoncer un rappel absolu.

**Trois chiffres, et le troisième est celui qu'on vient chercher :**

- `recall` — parmi les objets que la vérité voit, la proportion que le candidat rend
  **sous la même classe** ;
- `spatialRecall` — la proportion qu'il rend **à la bonne place, sous n'importe quelle
  classe**. L'écart avec `recall` est une erreur de classification, pas de détection,
  et `classConfusion` dit sous quelle étiquette l'objet est parti. Une moto rendue
  « person » est un appariement spatial réussi : la fondre dans `recall` ferait chercher
  la panne au détecteur alors qu'elle est au NMS ;
- `missedByWidth` — les manqués rangés par largeur **en pixels de la source**. C'est le
  chiffre qui sépare « le modèle est mauvais » de « l'objet fait 20 px dans le tenseur »
  (ADR 0037), et les deux appellent le contraire l'un de l'autre : un modèle plus gros
  d'un côté, `TRAFFIC_INFERENCE_IMGSZ` ou un plan plus serré de l'autre.

**Le rappel est déterministe, contrairement au débit.** Une course par branche suffit et
les 11 % de bruit de cette machine ne s'y appliquent pas — c'est la propriété sur
laquelle `pipeline_bench.py` s'appuie déjà en traitant tout écart de `counts` entre deux
courses comme une régression. Ce qu'il faut à la place, c'est de la **taille
d'échantillon** : sous ~200 instances de vérité, un rappel ne veut rien dire, et le banc
le dit en toutes lettres plutôt que d'imprimer un nombre plausible.

**Ce que ce banc ne peut pas faire, et pourquoi il refuse au lieu de tricher.** En
`--stage tracked`, le modèle de vérité doit être **différent** du modèle candidat :
`iter_video` tient un bail sur le candidat pendant toute la course, et `lease` fait
*attendre* un second bail sur le même identifiant plutôt que de le refuser (invariant 9).
Demander la même chose des deux côtés ne rendrait pas un mauvais chiffre : cela
bloquerait indéfiniment. Le banc s'arrête donc avec un message.

**Sur la VRAM.** Deux modèles résidents, dont un `yolo11x` à 1280 en fp32 — `half` est
interdit sur cette carte Pascal (ADR 0012). Sur 4 Gio c'est juste. Si l'inférence de
vérité échoue en OOM CUDA, `--truth-device cpu` la déporte : elle n'a aucune contrainte
de cadence, contrairement au candidat.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings
from traffic_analysis.features.counting.application.ports import EngineSpec
from traffic_analysis.features.counting.domain.models import (
    DETECTABLE_CLASSES,
    BoundingBox,
)
from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    UltralyticsEngine,
    detector_floor,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

#: Recouvrement minimal pour qu'une boîte candidate « soit » une boîte de vérité.
#: 0,5 est la convention COCO pour AP50, et c'est aussi le seuil au-dessus duquel un
#: humain regardant les deux rectangles dit « c'est le même objet ».
DEFAULT_MATCH_IOU = 0.5

#: Le modèle pris pour vérité. `yolo11x` est au catalogue et déjà présent dans
#: `.weights/` sur la machine de développement, donc la mesure ne demande aucun
#: téléchargement.
DEFAULT_TRUTH_MODEL = "yolo11x"

#: Définition d'entrée de la passe de vérité. 1280 et non 640 : tout l'objet du banc
#: est de voir ce qu'une entrée plus grande rendrait, donc la référence doit être
#: au-dessus du candidat, jamais à égalité.
DEFAULT_TRUTH_IMGSZ = 1280

#: Seuil de la passe de vérité, volontairement bas. Une référence qui filtre autant que
#: le candidat ne peut pas montrer ce que le candidat manque.
DEFAULT_TRUTH_CONF = 0.15

#: Sous ce nombre d'instances de vérité, le rappel d'une classe est du bruit présenté
#: comme une mesure. Le banc l'imprime quand même, marqué.
MIN_INSTANCES = 200

#: Bornes de largeur, en pixels **de la source**. Elles encadrent le plancher où
#: ADR 0037 situe la panne : à imgsz 640 sur du 1080p, la largeur dans le tenseur vaut
#: le tiers de celle-ci, donc un objet de 96 px n'en fait plus que 32 — la borne
#: « small » de COCO.
WIDTH_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<32", 0.0, 32.0),
    ("32-64", 32.0, 64.0),
    ("64-128", 64.0, 128.0),
    (">=128", 128.0, float("inf")),
)

#: `coco_name` des classes que l'application sait compter, par identifiant.
LABEL_OF_ID: dict[int, str] = {entry.id: entry.coco_name for entry in DETECTABLE_CLASSES}


@dataclass(frozen=True, slots=True)
class Detection:
    """Une boîte rendue par un étage, quel qu'il soit."""

    class_id: int
    label: str
    score: float
    box: BoundingBox


def iou(first: BoundingBox, second: BoundingBox) -> float:
    """Recouvrement des deux boîtes sur leur union.

    L'IoU et **pas** `BoundingBox.containment` : celle-ci divise par la plus petite
    aire, ce qui la rend insensible à la différence de taille — exactement ce qu'on
    veut pour attraper une cabine dans un semi, et exactement ce qu'on ne veut pas
    pour dire « ces deux rectangles désignent le même objet ». Une boîte de vérité de
    200 px et une boîte candidate de 20 px posée dedans donneraient une containment de
    1,0 et un appariement parfaitement faux.
    """
    intersection = first.intersection_area(second)
    if intersection <= 0.0:
        return 0.0
    union = first.area + second.area - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def match(
    truth: Sequence[Detection],
    candidate: Sequence[Detection],
    *,
    match_iou: float = DEFAULT_MATCH_IOU,
) -> dict[int, int]:
    """Apparie les candidats à la vérité, **sans regarder la classe**.

    Rend `index de vérité -> index de candidat`. Les indices de vérité absents sont les
    manqués ; le label du candidat apparié dit si la classe est juste ou si l'objet est
    parti sous une autre étiquette.

    L'appariement est **glouton par score décroissant**, la convention d'évaluation de
    la détection : le candidat le plus sûr choisit sa boîte de vérité en premier. Un
    appariement optimal (hongrois) donnerait un rappel légèrement supérieur ; ce n'est
    pas ce que fait un consommateur de détections, et le banc doit mesurer la chaîne
    telle qu'elle est plutôt que dans son meilleur jour.

    **Class-agnostique délibérément.** C'est ce qui permet de distinguer une moto
    manquée d'une moto rendue sous « person » — la panne exacte que documente
    `nms.py:126 conf, j = cls.max(1, keepdim=True)`. Deux appariements séparés, un par
    classe, fondraient les deux cas en un seul chiffre et enverraient chercher la cause
    au mauvais endroit.
    """
    order = sorted(range(len(candidate)), key=lambda i: candidate[i].score, reverse=True)
    taken: set[int] = set()
    pairs: dict[int, int] = {}
    for cand_index in order:
        best_truth = -1
        best_iou = match_iou
        for truth_index, reference in enumerate(truth):
            if truth_index in taken:
                continue
            overlap = iou(reference.box, candidate[cand_index].box)
            # `>` strict et non `>=` : à égalité, le premier trouvé garde la boîte,
            # ce qui rend l'appariement indépendant de l'ordre de la vérité.
            if overlap > best_iou:
                best_iou = overlap
                best_truth = truth_index
        if best_truth >= 0:
            taken.add(best_truth)
            pairs[best_truth] = cand_index
    return pairs


def bucket_of(width: float) -> str:
    """Le seau de largeur d'une boîte, en pixels source."""
    for name, low, high in WIDTH_BUCKETS:
        if low <= width < high:
            return name
    return WIDTH_BUCKETS[-1][0]


class Tally:
    """Le décompte d'une classe, accumulé image après image."""

    __slots__ = ("_confusion", "_matched", "_missed_by_width", "_spatial", "_truth_by_width")

    def __init__(self) -> None:
        self._matched = 0
        self._spatial = 0
        self._confusion: dict[str, int] = {}
        self._missed_by_width: dict[str, int] = {name: 0 for name, _, _ in WIDTH_BUCKETS}
        self._truth_by_width: dict[str, int] = {name: 0 for name, _, _ in WIDTH_BUCKETS}

    def record(self, reference: Detection, matched: Detection | None) -> None:
        """Range une instance de vérité et ce que le candidat en a fait."""
        seau = bucket_of(reference.box.width)
        self._truth_by_width[seau] += 1
        if matched is None:
            self._missed_by_width[seau] += 1
            self._confusion["none"] = self._confusion.get("none", 0) + 1
            return
        self._spatial += 1
        if matched.label == reference.label:
            self._matched += 1
            return
        # Trouvé à la bonne place sous une autre étiquette : ce n'est pas un manqué de
        # détection, et le compter comme tel enverrait régler le mauvais réglage.
        self._missed_by_width[seau] += 1
        self._confusion[matched.label] = self._confusion.get(matched.label, 0) + 1

    def report(self) -> dict[str, Any]:
        total = sum(self._truth_by_width.values())
        return {
            "truth": total,
            "matched": self._matched,
            "recall": round(self._matched / total, 4) if total else None,
            "spatialMatched": self._spatial,
            "spatialRecall": round(self._spatial / total, 4) if total else None,
            "enoughInstances": total >= MIN_INSTANCES,
            "truthByWidth": dict(self._truth_by_width),
            "missedByWidth": dict(self._missed_by_width),
            "classConfusion": dict(sorted(self._confusion.items(), key=lambda kv: -kv[1])),
        }


def _to_detections(result: Any, wanted: frozenset[int]) -> list[Detection]:  # noqa: ANN401
    """Les boîtes d'un `Results` d'Ultralytics, restreintes aux classes demandées.

    Le filtre par classe est refait ici plutôt que laissé à `classes=` du modèle : la
    passe de vérité tourne **sans** filtre, pour que `classConfusion` puisse nommer une
    classe hors sélection (un deux-roues rendu « bicycle » alors que seul « motorcycle »
    est coché est une information, pas un silence).
    """
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    names = getattr(result, "names", {}) or {}
    out: list[Detection] = []
    for xyxy, cls, conf in zip(
        boxes.xyxy.tolist(), boxes.cls.tolist(), boxes.conf.tolist(), strict=True
    ):
        class_id = int(cls)
        if wanted and class_id not in wanted:
            continue
        left, top, right, bottom = xyxy
        out.append(
            Detection(
                class_id=class_id,
                label=str(names.get(class_id, LABEL_OF_ID.get(class_id, str(class_id)))),
                score=float(conf),
                box=BoundingBox(
                    x=float(left),
                    y=float(top),
                    width=float(right - left),
                    height=float(bottom - top),
                ),
            )
        )
    return out


def _truth_boxes(
    model: Any,  # noqa: ANN401
    image: Any,  # noqa: ANN401
    *,
    imgsz: int,
    conf: float,
    device: str,
    wanted: frozenset[int],
) -> list[Detection]:
    """La passe de référence sur **exactement** l'image que le candidat vient de voir.

    Un seul décodage pour les deux passes : l'image est celle que le moteur rend, donc
    l'identité des pixels est vraie par construction. Rapprocher deux décodages par
    numéro d'image marcherait presque toujours — et « presque » est exactement ce que
    ce dépôt refuse de laisser dans un instrument de mesure.

    `agnostic_nms=False` : la référence ne doit surtout pas subir la suppression
    inter-classes qu'on cherche à mesurer. `iou=0.7`, la valeur d'évaluation d'Ultralytics,
    plus permissive que le 0,45 du candidat pour la même raison.
    """
    results = model.predict(
        source=image,
        conf=conf,
        iou=0.7,
        classes=None,
        agnostic_nms=False,
        imgsz=imgsz,
        device=device,
        half=False,
        verbose=False,
    )
    return _to_detections(results[0], wanted)


def _candidate_boxes(
    model: Any,  # noqa: ANN401
    image: Any,  # noqa: ANN401
    *,
    spec: EngineSpec,
    imgsz: int,
    device: str,
    half: bool,
) -> list[Detection]:
    """L'étage détecteur seul, avec **exactement** les arguments de la production.

    Les valeurs viennent de `ultralytics_engine._track_batches` : `detector_floor` et
    non le seuil de l'utilisateur, `agnostic_nms=True`, la même `imgsz`. Recopier ces
    arguments est un doublon assumé — le vrai chemin passe par `model.track()`, qui
    porte un tracker dont c'est précisément l'effet qu'on veut retirer ici. Si l'un des
    deux change, ce banc mesure autre chose que la production : un test le verrouille.
    """
    results = model.predict(
        source=image,
        conf=detector_floor(spec.confidence),
        iou=spec.iou,
        classes=list(spec.class_ids),
        agnostic_nms=True,
        imgsz=imgsz,
        device=device,
        half=half,
        verbose=False,
    )
    return _to_detections(results[0], frozenset(spec.class_ids))


def _decode(video: Path, *, start_ms: float, frames: int) -> Iterator[Any]:
    """Décodage nu pour l'étage `detector`, qui ne peut pas passer par `iter_video`.

    `iter_video` appelle `model.track()` : l'utiliser pour ne lire que ses images
    coûterait le tracker qu'on cherche justement à mettre hors circuit, et tiendrait un
    bail sur le modèle candidat dont cet étage a besoin.
    """
    import cv2

    capture = cv2.VideoCapture(str(video))
    try:
        if start_ms > 0:
            capture.set(cv2.CAP_PROP_POS_MSEC, start_ms)
        seen = 0
        while seen < frames:
            ok, image = capture.read()
            if not ok:
                return
            seen += 1
            yield image
    finally:
        capture.release()


def _run_tracked(
    engine: UltralyticsEngine,
    truth_model: Any,  # noqa: ANN401
    video: Path,
    spec: EngineSpec,
    *,
    frames: int,
    truth_imgsz: int,
    truth_conf: float,
    truth_device: str,
    match_iou: float,
    wanted: frozenset[int],
) -> tuple[dict[str, Tally], int]:
    """Le chemin de production : ce que le domaine reçoit réellement."""
    tallies: dict[str, Tally] = {}
    processed = 0
    for frame in engine.iter_video(video, spec):
        if processed >= frames:
            break
        processed += 1
        reference = _truth_boxes(
            truth_model,
            frame.image,
            imgsz=truth_imgsz,
            conf=truth_conf,
            device=truth_device,
            wanted=wanted,
        )
        observed = [
            Detection(class_id=track.class_id, label=track.label, score=track.score, box=track.box)
            for track in frame.tracks
        ]
        _accumulate(tallies, reference, observed, match_iou=match_iou)
    return tallies, processed


def _run_detector(
    registry: ModelRegistry,
    truth_model: Any,  # noqa: ANN401
    video: Path,
    spec: EngineSpec,
    *,
    frames: int,
    imgsz: int,
    truth_imgsz: int,
    truth_conf: float,
    truth_device: str,
    match_iou: float,
    wanted: frozenset[int],
) -> tuple[dict[str, Tally], int]:
    """Le détecteur seul, sans tracker. L'écart avec `tracked` est la perte du tracker."""
    tallies: dict[str, Tally] = {}
    processed = 0
    with registry.lease(spec.model_id) as model:
        for image in _decode(video, start_ms=spec.start_ms, frames=frames):
            processed += 1
            reference = _truth_boxes(
                truth_model,
                image,
                imgsz=truth_imgsz,
                conf=truth_conf,
                device=truth_device,
                wanted=wanted,
            )
            observed = _candidate_boxes(
                model,
                image,
                spec=spec,
                imgsz=imgsz,
                device=registry.device(),
                half=registry.half(),
            )
            _accumulate(tallies, reference, observed, match_iou=match_iou)
    return tallies, processed


def _accumulate(
    tallies: dict[str, Tally],
    reference: Sequence[Detection],
    observed: Sequence[Detection],
    *,
    match_iou: float,
) -> None:
    """Range une image : un appariement, puis une écriture par instance de vérité."""
    pairs = match(reference, observed, match_iou=match_iou)
    for index, truth_box in enumerate(reference):
        tally = tallies.setdefault(truth_box.label, Tally())
        cand_index = pairs.get(index)
        tally.record(truth_box, observed[cand_index] if cand_index is not None else None)


def _print_class(label: str, result: dict[str, Any]) -> None:
    total = result["truth"]
    if not total:
        return
    recall = result["recall"]
    spatial = result["spatialRecall"]
    flag = "" if result["enoughInstances"] else f"  ⚠ {total} < {MIN_INSTANCES}, non concluant"
    print(f"      {label:<12} {result['matched']:>5} / {total:<5} rappel {recall:.3f}", end="")
    print(f"   spatial {spatial:.3f}{flag}")
    missed = {k: v for k, v in result["missedByWidth"].items() if v}
    if missed:
        detail = "  ".join(f"{k} {v}" for k, v in missed.items())
        print(f"                   manqués par largeur : {detail}")
    confusion = {k: v for k, v in result["classConfusion"].items() if k != "none" and v}
    if confusion:
        detail = "  ".join(f"{k} {v}" for k, v in confusion.items())
        print(f"                   rendus sous une autre classe : {detail}")


def _print_inventory(label: str, result: dict[str, Any]) -> None:
    """L'inventaire ne rend qu'un décompte : aucun candidat n'a tourné."""
    total = result["truth"]
    flag = "" if result["enoughInstances"] else f"  ⚠ < {MIN_INSTANCES}, mesure non concluante"
    widths = "  ".join(f"{k} {v}" for k, v in result["truthByWidth"].items() if v)
    print(f"      {label:<12} {total:>5} instances{flag}")
    print(f"                   par largeur : {widths}")


def _print_compare(current: dict[str, Any], previous: dict[str, Any]) -> None:
    """Le rappel étant déterministe, tout écart non nul est un vrai écart."""
    print("\n  Comparaison")
    before = {source["name"]: source["byClass"] for source in previous.get("sources", []) if source}
    for source in current.get("sources", []):
        old = before.get(source["name"])
        if not old:
            continue
        print(f"    {source['name']}")
        for label, result in source["byClass"].items():
            was = old.get(label)
            if not was or result["recall"] is None or was.get("recall") is None:
                continue
            delta = result["recall"] - was["recall"]
            sign = "+" if delta >= 0 else ""
            print(
                f"      {label:<12} {was['recall']:.3f} → {result['recall']:.3f}"
                f"   ({sign}{delta:.3f})"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--videos", type=Path, required=True, help="Fichier ou dossier.")
    parser.add_argument("--frames", type=int, default=400, help="Images analysées par vidéo.")
    parser.add_argument("--start", type=float, default=0.0, help="Départ, en secondes.")
    parser.add_argument("--model", help="Modèle candidat. Défaut : celui du déploiement.")
    parser.add_argument("--imgsz", type=int, help="Entrée du candidat. Défaut : le déploiement.")
    parser.add_argument("--confidence", type=float, default=0.35, help="« Confiance véhicules ».")
    parser.add_argument("--iou", type=float, default=0.45, help="« Seuil IoU » de la requête.")
    parser.add_argument(
        "--classes",
        default="0,1,2,3,5,7",
        help="Identifiants COCO cochés, séparés par des virgules.",
    )
    parser.add_argument(
        "--stage",
        choices=("tracked", "detector"),
        default="tracked",
        help="tracked = le vrai chemin (défaut) ; detector = sans tracker.",
    )
    parser.add_argument("--truth-model", default=DEFAULT_TRUTH_MODEL)
    parser.add_argument("--truth-imgsz", type=int, default=DEFAULT_TRUTH_IMGSZ)
    parser.add_argument("--truth-conf", type=float, default=DEFAULT_TRUTH_CONF)
    parser.add_argument(
        "--truth-device", default=None, help="cpu pour déporter la référence si la VRAM manque."
    )
    parser.add_argument("--match-iou", type=float, default=DEFAULT_MATCH_IOU)
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="N'exécute que la passe de vérité : combien d'instances par classe ?",
    )
    parser.add_argument("--json", type=Path, help="Écrit le rapport complet à ce chemin.")
    parser.add_argument("--compare", type=Path, help="Rapport antérieur à comparer.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings()

    wanted = frozenset(int(part) for part in args.classes.split(",") if part.strip())
    if not wanted:
        sys.stdout.write("--classes vide : rien à mesurer.\n")
        return 1

    videos = (
        sorted(p for p in args.videos.glob("**/*") if p.suffix.lower() in {".mp4", ".mov", ".avi"})
        if args.videos.is_dir()
        else [args.videos]
    )
    if not videos:
        sys.stdout.write(f"Aucune vidéo sous {args.videos}\n")
        return 1

    model_id = args.model or settings.default_model_id
    imgsz = args.imgsz or settings.inference_imgsz

    # `lease` **attend** un bail concurrent sur le même identifiant plutôt que de le
    # refuser (invariant 9). En `tracked`, `iter_video` tient le candidat pendant toute
    # la course : demander la vérité au même modèle bloquerait indéfiniment, sans
    # message. On s'arrête ici plutôt que de laisser le banc paraître lent.
    if args.stage == "tracked" and args.truth_model == model_id and not args.inventory:
        sys.stdout.write(
            f"--truth-model et --model valent tous deux « {model_id} ».\n"
            "En --stage tracked, iter_video tient un bail sur le candidat pendant toute la\n"
            "course et un second bail sur le même modèle attendrait sans fin (invariant 9).\n"
            "Prenez un modèle de vérité différent, ou --stage detector.\n"
        )
        return 1

    # Deux modèles résidents : le candidat et la référence.
    registry = ModelRegistry(
        settings.weights_dir, max_loaded=2, device=settings.device, half=settings.half
    )
    engine = UltralyticsEngine(registry, imgsz=imgsz)
    truth_device = args.truth_device or registry.device()

    report: dict[str, Any] = {
        "run": {
            "stage": args.stage,
            "model": model_id,
            "imgsz": imgsz,
            "confidence": args.confidence,
            "detectorFloor": round(detector_floor(args.confidence), 4),
            "iou": args.iou,
            "classIds": sorted(wanted),
            "truthModel": args.truth_model,
            "truthImgsz": args.truth_imgsz,
            "truthConf": args.truth_conf,
            "truthDevice": truth_device,
            "matchIou": args.match_iou,
            "frames": args.frames,
            "start": args.start,
            "device": registry.device(),
            "half": registry.half(),
        },
        "sources": [],
    }

    print(
        f"\n  {args.stage} — candidat {model_id}@{imgsz}, "
        f"vérité {args.truth_model}@{args.truth_imgsz}"
    )

    for video in videos:
        name = video.parent.name if video.name.startswith("input.") else video.name
        print(f"\n    {name}")
        spec = EngineSpec(
            model_id=model_id,
            confidence=args.confidence,
            iou=args.iou,
            class_ids=tuple(sorted(wanted)),
            start_ms=args.start * 1000.0,
        )
        with registry.lease(args.truth_model) as truth_model:
            if args.inventory:
                tallies, processed = _inventory(
                    truth_model,
                    video,
                    spec,
                    frames=args.frames,
                    truth_imgsz=args.truth_imgsz,
                    truth_conf=args.truth_conf,
                    truth_device=truth_device,
                    wanted=wanted,
                )
            elif args.stage == "tracked":
                tallies, processed = _run_tracked(
                    engine,
                    truth_model,
                    video,
                    spec,
                    frames=args.frames,
                    truth_imgsz=args.truth_imgsz,
                    truth_conf=args.truth_conf,
                    truth_device=truth_device,
                    match_iou=args.match_iou,
                    wanted=wanted,
                )
            else:
                tallies, processed = _run_detector(
                    registry,
                    truth_model,
                    video,
                    spec,
                    frames=args.frames,
                    imgsz=imgsz,
                    truth_imgsz=args.truth_imgsz,
                    truth_conf=args.truth_conf,
                    truth_device=truth_device,
                    match_iou=args.match_iou,
                    wanted=wanted,
                )

        by_class = {label: tally.report() for label, tally in sorted(tallies.items())}
        print(f"      {processed} images analysées")
        for label, result in by_class.items():
            # En inventaire, aucun candidat n'a tourné : imprimer un rappel de 0,000
            # se lirait comme un échec de détection, l'inverse de ce que la course dit.
            if args.inventory:
                _print_inventory(label, result)
            else:
                _print_class(label, result)
        if not by_class:
            print("      la référence n'a trouvé aucune instance des classes demandées")
        report["sources"].append({"name": name, "frames": processed, "byClass": by_class})

    if args.compare and args.compare.is_file():
        _print_compare(report, json.loads(args.compare.read_text(encoding="utf-8")))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n  Rapport écrit : {args.json}")
    return 0


def _inventory(
    truth_model: Any,  # noqa: ANN401
    video: Path,
    spec: EngineSpec,
    *,
    frames: int,
    truth_imgsz: int,
    truth_conf: float,
    truth_device: str,
    wanted: frozenset[int],
) -> tuple[dict[str, Tally], int]:
    """« Y a-t-il seulement des motos dans ce clip ? », en une passe et sans candidat.

    C'est le contrôle à passer **avant** toute mesure de rappel : si la référence ne
    trouve ni moto ni piéton, la conclusion est « il n'y en a pas dans ce clip » et non
    « le détecteur échoue ». Les deux se ressemblent beaucoup dans un rapport.
    """
    tallies: dict[str, Tally] = {}
    processed = 0
    for image in _decode(video, start_ms=spec.start_ms, frames=frames):
        processed += 1
        for reference in _truth_boxes(
            truth_model,
            image,
            imgsz=truth_imgsz,
            conf=truth_conf,
            device=truth_device,
            wanted=wanted,
        ):
            tallies.setdefault(reference.label, Tally()).record(reference, None)
    return tallies, processed


if __name__ == "__main__":
    raise SystemExit(main())
