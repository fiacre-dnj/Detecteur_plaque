"""Banc de mesure du pipeline de comptage — où passent les millisecondes.

    # Référence, avant toute optimisation.
    uv run python scripts/pipeline_bench.py --videos data/jobs --frames 300 --json out/avant.json

    # Après un levier, avec l'écart chiffré.
    uv run python scripts/pipeline_bench.py --videos data/jobs --frames 300 \
        --imgsz 512 --batch 4 --json out/apres.json --compare out/avant.json

**Pourquoi ce banc existe.** Le total « 47 ms par image » ne dit pas *où* elles
passent, et sans ce partage toute optimisation est un pari. `scripts/anpr_bench.py`
mesure la chaîne ANPR ; celui-ci mesure ce qui tourne à **chaque** image du
comptage : décodage, prétraitement, inférence, NMS, suivi, domaine, sérialisation.

**Ce qu'il mesure vraiment, et ce qu'il ne mesure pas.** Il fait tourner le
**vrai** `UltralyticsEngine` et la **vraie** `AnalysisSession`, dans l'ordre où
`AnalysisService.run_video` les enchaîne, avec la même sérialisation par
`snapshot()`. Il n'exécute ni la passe ANPR (c'est le sujet de l'autre banc), ni
la publication SSE de progression et d'aperçu. Ce n'est donc pas une copie du
service : c'est son chemin chaud, isolé.

**Comment le partage est obtenu.** Trois sources, et elles ne se recouvrent pas :

- `result.speed` d'Ultralytics donne prétraitement / inférence / NMS. Ces
  chronomètres **synchronisent CUDA** (`ops.Profile(device=…)`), donc l'inférence
  est du vrai temps GPU et non un temps de lancement de noyau ;
- le suivi n'est **pas** dans `speed` : il tourne dans un callback exécuté après
  les chronomètres du prédicteur. Il est donc mesuré ici en enveloppant
  `BOTSORT.update`, et la compensation de mouvement en enveloppant `GMC.apply` —
  celle-ci est **incluse** dans le suivi, elle n'est pas un poste de plus ;
- le décodage n'est mesuré nulle part par Ultralytics : il a lieu pendant
  l'itération du chargeur. Il est donc obtenu **par différence** et porte ce nom
  (`decodeAndOther`), parce qu'il contient aussi la copie de `orig_img` et le
  transport du générateur. Un poste obtenu par soustraction ne doit jamais
  prétendre au même statut qu'un poste chronométré.

**Le chiffre qu'on vient chercher** est `framesPerSecond`, et le partage explique
pourquoi il vaut ce qu'il vaut. Le second chiffre, tout aussi important, est le
bloc `counts` : une optimisation qui change `trackedVehicles` ou `crossings` n'est
pas une optimisation, c'est une régression déguisée en gain.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings
from traffic_analysis.features.counting.application.dto import AnalysisJobConfig
from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import CountingLineDef
from traffic_analysis.features.counting.domain.tracking_session import AnalysisSession
from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    UltralyticsEngine,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

#: Extensions considérées comme des vidéos quand `--videos` désigne un dossier.
VIDEO_SUFFIXES = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})


@dataclass
class Stage:
    """Un poste de dépense, en millisecondes par image analysée."""

    name: str
    samples: list[float] = field(default_factory=list)

    def add(self, milliseconds: float) -> None:
        self.samples.append(milliseconds)

    @property
    def mean_ms(self) -> float:
        return statistics.fmean(self.samples) if self.samples else 0.0

    @property
    def total_ms(self) -> float:
        return sum(self.samples)


@dataclass
class Timings:
    """Les postes d'une course, plus le total mesuré au poignet.

    `wall_ms` est chronométré autour de la boucle entière : c'est lui qui fait
    foi, et la somme des postes ne peut que lui être inférieure ou égale. La
    différence est le décodage et le transport, qu'aucun chronomètre interne ne
    couvre.
    """

    preprocess: Stage = field(default_factory=lambda: Stage("preprocess"))
    inference: Stage = field(default_factory=lambda: Stage("inference"))
    postprocess: Stage = field(default_factory=lambda: Stage("postprocess"))
    tracker: Stage = field(default_factory=lambda: Stage("tracker"))
    gmc: Stage = field(default_factory=lambda: Stage("gmc"))
    domain: Stage = field(default_factory=lambda: Stage("domain"))
    serialise: Stage = field(default_factory=lambda: Stage("serialise"))
    wall_ms: float = 0.0
    frames: int = 0

    def measured_ms(self) -> float:
        """Somme des postes réellement chronométrés.

        `gmc` en est **exclu** : il est déjà compté dans `tracker`, et l'ajouter
        ferait dépasser le total mesuré au poignet — un partage dont la somme
        excède le tout se lit comme une erreur de mesure, et c'en serait une.
        """
        return (
            self.preprocess.total_ms
            + self.inference.total_ms
            + self.postprocess.total_ms
            + self.tracker.total_ms
            + self.domain.total_ms
            + self.serialise.total_ms
        )

    def as_json(self) -> dict[str, Any]:
        per_frame = max(1, self.frames)
        rest = max(0.0, self.wall_ms - self.measured_ms())
        return {
            "frames": self.frames,
            "framesPerSecond": round(self.frames / (self.wall_ms / 1000.0), 2)
            if self.wall_ms > 0
            else 0.0,
            "msPerFrame": round(self.wall_ms / per_frame, 2),
            "stages": {
                "preprocess": round(self.preprocess.mean_ms, 2),
                "inference": round(self.inference.mean_ms, 2),
                "postprocess": round(self.postprocess.mean_ms, 2),
                "tracker": round(self.tracker.mean_ms, 2),
                "gmc": round(self.gmc.mean_ms, 2),
                "domain": round(self.domain.mean_ms, 2),
                "serialise": round(self.serialise.mean_ms, 2),
                "decodeAndOther": round(rest / per_frame, 2),
            },
        }


@contextmanager
def _instrumented(timings: Timings) -> Iterator[None]:
    """Enveloppe les trois points que le chrono d'Ultralytics n'atteint pas.

    Le suivi et la compensation de mouvement vivent dans la roue `ultralytics`, le
    domaine dans le nôtre. Les trois sont restaurés à la sortie : un banc qui
    laisserait des enveloppes en place fausserait la mesure suivante.

    `_to_observations` est enveloppée pour une autre raison : c'est le seul
    endroit où le `Results` d'Ultralytics — donc son `speed` — traverse notre
    adaptateur. Le moteur ne le publie pas, et il n'a pas à le faire pour un banc.
    """
    from ultralytics.trackers.basetrack import BaseTrack
    from ultralytics.trackers.bot_sort import BOTSORT
    from ultralytics.trackers.utils.gmc import GMC

    from traffic_analysis.features.models_registry.infrastructure import ultralytics_engine

    original_update = BOTSORT.update
    original_gmc = GMC.apply
    original_feed = AnalysisSession.feed
    original_to_observations = ultralytics_engine._to_observations

    def timed_update(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        started = perf_counter()
        try:
            return original_update(self, *args, **kwargs)
        finally:
            timings.tracker.add((perf_counter() - started) * 1000.0)

    def timed_gmc(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        started = perf_counter()
        try:
            return original_gmc(self, *args, **kwargs)
        finally:
            timings.gmc.add((perf_counter() - started) * 1000.0)

    def timed_feed(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        started = perf_counter()
        try:
            return original_feed(self, *args, **kwargs)
        finally:
            timings.domain.add((perf_counter() - started) * 1000.0)

    def observing(result: Any) -> Any:  # noqa: ANN401
        speed = getattr(result, "speed", None)
        if isinstance(speed, dict):
            timings.preprocess.add(float(speed.get("preprocess", 0.0)))
            timings.inference.add(float(speed.get("inference", 0.0)))
            timings.postprocess.add(float(speed.get("postprocess", 0.0)))
        return original_to_observations(result)

    BOTSORT.update = timed_update  # type: ignore[method-assign]
    GMC.apply = timed_gmc  # type: ignore[method-assign]
    AnalysisSession.feed = timed_feed  # type: ignore[method-assign]
    ultralytics_engine._to_observations = observing
    try:
        yield
    finally:
        BOTSORT.update = original_update  # type: ignore[method-assign]
        GMC.apply = original_gmc  # type: ignore[method-assign]
        AnalysisSession.feed = original_feed  # type: ignore[method-assign]
        ultralytics_engine._to_observations = original_to_observations
        # Les identifiants de piste sont un compteur de **classe**. Sans cette
        # remise à zéro, la deuxième vidéo d'une même course démarre à l'identifiant
        # où la première s'est arrêtée : les chiffres restent justes, mais deux
        # courses du banc ne sont plus comparables piste à piste.
        BaseTrack.reset_id()


def run_video(
    engine: UltralyticsEngine,
    video: Path,
    config: AnalysisJobConfig,
    *,
    frames: int,
    warmup_frames: int,
) -> tuple[Timings, dict[str, Any]]:
    """Analyse `frames` images et rend le partage du temps et les compteurs.

    Les `warmup_frames` premières images sont **analysées mais non comptées dans
    la mesure** : la première inférence d'un modèle inclut sa fusion de couches et
    l'autotune de cudnn, ce qui se paie une fois et fausserait une moyenne sur
    quelques centaines d'images (piège 31 de prompt/13).
    """
    info = engine.probe(video)
    session = AnalysisSession(config.session_config(), info.width, info.height)
    timings = Timings()

    with _instrumented(timings):
        started: float | None = None
        analysed = 0
        for frame in engine.iter_video(video, config.engine_spec()):
            # Trois arguments et non quatre : depuis ADR 0016, le comptage ne
            # reçoit plus l'image — il ne touche plus un seul pixel.
            outcome = session.feed(frame.frame_index, frame.timestamp_ms, frame.tracks)
            serialise_started = perf_counter()
            # La sérialisation du service : `run_video` prend un `snapshot()` par
            # piste et par image pour la timeline. C'est un coût par image, donc
            # il appartient à ce partage.
            snapshots = tuple(track.snapshot() for track in outcome.tracks)
            timings.serialise.add((perf_counter() - serialise_started) * 1000.0)
            del snapshots

            analysed += 1
            if analysed == warmup_frames:
                # Le rodage est terminé : on jette ce qui a été mesuré et on
                # démarre le chronomètre de référence au même instant.
                _discard(timings)
                started = perf_counter()
            if started is not None and analysed - warmup_frames >= frames:
                break

    if started is None:  # vidéo plus courte que le rodage demandé
        timings.wall_ms = 0.0
        timings.frames = 0
    else:
        timings.wall_ms = (perf_counter() - started) * 1000.0
        timings.frames = analysed - warmup_frames

    stats = session.stats()
    counts = {
        # `trackedVehicles` remplace `uniqueVehicles`, et `reidHits` a disparu avec
        # la ré-identification (ADR 0016). Les noms comptent ici : ce bloc sert à
        # repérer qu'une optimisation a changé un compteur, donc il doit porter les
        # noms du contrat publié et pas leurs ancêtres.
        "trackedVehicles": stats.tracked_vehicles,
        "crossings": stats.crossings,
        "crossedUnique": stats.crossed_unique,
        "byClass": dict(sorted(stats.by_class.items())),
        "byLine": {name: tally.total for name, tally in sorted(stats.by_line.items())},
        # Les quasi-franchissements sont **un indicateur de qualité de suivi**, pas
        # un compteur : ils montent quand les pistes s'éteignent avant la ligne. Un
        # levier qui gagne des images par seconde en les faisant monter a dégradé le
        # comptage sans toucher aux totaux, ce qu'aucun autre chiffre ne dirait.
        "nearMisses": dict(sorted(stats.diagnostics.near_misses.items())),
    }
    return timings, counts


def _discard(timings: Timings) -> None:
    """Vide les échantillons de rodage, en gardant les postes en place."""
    for stage in (
        timings.preprocess,
        timings.inference,
        timings.postprocess,
        timings.tracker,
        timings.gmc,
        timings.domain,
        timings.serialise,
    ):
        stage.samples.clear()


def _mid_cross(width: int, height: int) -> tuple[CountingLineDef, ...]:
    """Une croix au milieu de l'image : une ligne horizontale **et** une verticale.

    Le banc a besoin d'une géométrie pour que le comptage travaille réellement —
    sans ligne, `LineCounter` ne fait rien et le poste `domain` mesurerait un
    pipeline qui ne compte pas.

    **Deux lignes et non une**, parce que la première version n'en posait qu'une,
    horizontale, et rendait `crossings = 0` sur les trois vidéos : la circulation y
    est transversale, donc rien ne la franchissait jamais. Le garde-fou de justesse
    ne vérifiait alors que le nombre de véhicules, en laissant tout le chemin de
    comptage hors de la comparaison — c'est-à-dire précisément ce qu'une optimisation
    risque de casser. Une croix est franchie quel que soit le sens de la circulation.

    Un véhicule qui franchit les deux lignes compte **deux fois** : il n'y a plus de
    déduplication depuis ADR 0016, et c'est voulu. Le banc mesure donc le comptage
    réellement servi, y compris cette propriété.
    """
    x = width / 2.0
    y = height / 2.0
    return (
        CountingLineDef(
            id="bench-h", name="banc horizontale", a=Point(0.0, y), b=Point(float(width), y)
        ),
        CountingLineDef(
            id="bench-v", name="banc verticale", a=Point(x, 0.0), b=Point(x, float(height))
        ),
    )


def _videos_in(target: Path) -> list[Path]:
    """Vidéos d'un fichier ou d'un dossier, triées pour être reproductibles."""
    if target.is_file():
        return [target]
    return sorted(
        path
        for path in target.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    )


def print_run(report: dict[str, Any]) -> None:
    """Le partage, une ligne par poste, la plus chère en premier."""
    context = report["context"]
    print(
        f"\n  device={context['device']}  half={context['half']}  "
        f"imgsz={context['settings']['imgsz']}  batch={context['settings']['batch']}  "
        f"gmc={context['settings']['gmc']}  reid={context['settings']['withReid']}"
    )

    for source in report["sources"]:
        timing = source["timings"]
        stages = timing["stages"]
        print(f"\n  {source['name']}  {source['width']}x{source['height']}")
        print(
            f"    {timing['framesPerSecond']:>7.2f} img/s   {timing['msPerFrame']:>6.2f} ms/image"
        )
        for name, value in sorted(stages.items(), key=lambda item: -item[1]):
            share = 100.0 * value / timing["msPerFrame"] if timing["msPerFrame"] else 0.0
            marker = " (par différence)" if name == "decodeAndOther" else ""
            print(f"      {name:<16} {value:>6.2f} ms  {share:>5.1f} %{marker}")
        counts = source["counts"]
        near = sum(counts.get("nearMisses", {}).values())
        print(
            f"    comptage : {counts['trackedVehicles']} véhicules suivis, "
            f"{counts['crossings']} franchissements, {near} quasi-franchissements"
        )


def print_comparison(current: dict[str, Any], previous: dict[str, Any]) -> None:
    """Écart au rapport antérieur, débit **et** justesse.

    Les deux sont affichés côte à côte délibérément : un gain de débit payé par un
    comptage différent n'est pas un gain, et les lire dans deux tableaux séparés
    laisserait croire le contraire.
    """
    print("\n  ── Comparaison ──────────────────────────────────────────────")
    before = {source["name"]: source for source in previous.get("sources", [])}
    for source in current["sources"]:
        older = before.get(source["name"])
        if older is None:
            print(f"  {source['name']} : absente du rapport antérieur.")
            continue
        was = older["timings"]["framesPerSecond"]
        now = source["timings"]["framesPerSecond"]
        ratio = now / was if was else 0.0
        print(f"\n  {source['name']} : {was:.2f} → {now:.2f} img/s  ({ratio:.2f}×)")

        for name, value in sorted(source["timings"]["stages"].items()):
            old_value = older["timings"]["stages"].get(name)
            if old_value is None or (abs(value - old_value) < 0.05):
                continue
            print(f"      {name:<16} {old_value:>6.2f} → {value:>6.2f} ms")

        if source["counts"] != older["counts"]:
            print("    ⚠ LE COMPTAGE A CHANGÉ — ce n'est pas une optimisation neutre :")
            for key in ("trackedVehicles", "crossings", "crossedUnique"):
                if source["counts"].get(key) != older["counts"].get(key):
                    print(f"      {key} : {older['counts'].get(key)} → {source['counts'].get(key)}")
            # Les quasi-franchissements ne sont pas un total, mais leur variation
            # est le signal le plus précoce d'un suivi qui s'est dégradé : les
            # pistes s'éteignent plus tôt avant que le moindre total ne bouge.
            was_near = sum(older["counts"].get("nearMisses", {}).values())
            now_near = sum(source["counts"].get("nearMisses", {}).values())
            if was_near != now_near:
                print(f"      quasi-franchissements : {was_near} → {now_near}")
        else:
            print("    comptage identique.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--videos", type=Path, required=True, help="Fichier ou dossier de vidéos.")
    parser.add_argument("--frames", type=int, default=300, help="Images mesurées par vidéo.")
    parser.add_argument(
        "--warmup",
        type=int,
        default=20,
        help="Images analysées avant de démarrer la mesure (fusion de couches, autotune cudnn).",
    )
    parser.add_argument("--stride", type=int, default=1, help="Une image sur N.")
    parser.add_argument("--model", default=None, help="Identifiant de modèle du catalogue.")
    parser.add_argument("--imgsz", type=int, default=None, help="Côté de l'entrée du réseau.")
    parser.add_argument(
        "--gmc",
        default=None,
        choices=["none", "sparseOptFlow", "orb", "sift", "ecc"],
        help="Compensation de mouvement. Par défaut : le réglage TRAFFIC_TRACKER_GMC.",
    )
    parser.add_argument("--batch", type=int, default=None, help="Images par inférence.")
    parser.add_argument(
        "--no-cudnn",
        action="store_true",
        help="Mesure sans l'autotune cuDNN, pour chiffrer ce qu'il apporte.",
    )
    parser.add_argument("--json", type=Path, help="Écrit le rapport complet à ce chemin.")
    parser.add_argument("--compare", type=Path, help="Rapport JSON antérieur à comparer.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()

    videos = _videos_in(args.videos)
    if not videos:
        print(f"Aucune vidéo trouvée dans {args.videos}.", file=sys.stderr)
        return 1

    registry = ModelRegistry(
        settings.weights_dir,
        max_loaded=settings.max_loaded_models,
        device=settings.device,
        half=settings.half,
    )
    # Le service pose ce budget dans son `lifespan`, avant toute inférence : un
    # banc qui ne le poserait pas mesurerait une autre machine que la sienne.
    if settings.inference_threads > 0:
        registry.apply_thread_budget(settings.inference_threads)

    # Le `gmc_method` vient du réglage, exactement comme dans `container.py`. Le
    # passer par la ligne de commande servirait à comparer deux valeurs sans toucher
    # à l'environnement ; à `None` près, c'est le service qu'on mesure.
    gmc = args.gmc if args.gmc is not None else settings.tracker_gmc
    imgsz = args.imgsz if args.imgsz is not None else settings.inference_imgsz
    batch = args.batch if args.batch is not None else settings.inference_batch
    # Le service pose aussi l'autotune cuDNN dans son `lifespan`, avant toute
    # inférence : sans lui, le banc mesurerait des algorithmes de convolution que
    # le service n'utilise pas. `--no-cudnn` existe pour **chiffrer** ce que
    # l'autotune apporte, pas pour proposer un mode dégradé.
    if not args.no_cudnn:
        registry.enable_cudnn_autotune()
    engine = UltralyticsEngine(registry, gmc_method=gmc, imgsz=imgsz, batch=batch)
    model_id = args.model or settings.default_model_id

    report: dict[str, Any] = {
        "context": {
            "device": registry.device(),
            "deviceReason": registry.device_reason(),
            "gpuName": registry.gpu_name(),
            "half": registry.half(),
            "modelId": model_id,
            "ultralyticsVersion": registry.ultralytics_version(),
            "settings": {
                "imgsz": imgsz,
                "batch": batch,
                "stride": args.stride,
                "frames": args.frames,
                "warmup": args.warmup,
                # Relus depuis le fichier **réellement utilisé** plutôt que
                # supposés : c'est lui qui décide, et un rapport qui annoncerait
                # autre chose que ce qui a tourné serait pire qu'un rapport sans
                # cette ligne.
                **_tracker_settings(gmc),
            },
        },
        "sources": [],
    }

    for video in videos:
        info = engine.probe(video)
        config = AnalysisJobConfig(
            model_id=model_id,
            frame_stride=args.stride,
            lines=_mid_cross(info.width, info.height),
        )
        timings, counts = run_video(
            engine, video, config, frames=args.frames, warmup_frames=args.warmup
        )
        report["sources"].append(
            {
                "name": video.parent.name if video.name == "input.mp4" else video.name,
                "width": info.width,
                "height": info.height,
                "fps": info.fps,
                "timings": timings.as_json(),
                "counts": counts,
            }
        )

    print_run(report)

    if args.compare is not None and args.compare.is_file():
        print_comparison(report, json.loads(args.compare.read_text(encoding="utf-8")))

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\n  Rapport écrit : {args.json}")
    return 0


def _tracker_settings(gmc_method: str) -> dict[str, Any]:
    """Ce que dit le fichier de tracker **effectivement chargé** par cette course.

    Le fichier de base et le fichier dérivé ne disent pas la même chose : lire le
    premier alors que le second tourne écrirait dans le rapport une valeur que
    l'analyse n'a pas utilisée, et c'est précisément ce qu'un `--compare` ne
    pardonne pas.
    """
    import yaml

    from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
        resolved_tracker_config,
    )

    loaded = yaml.safe_load(resolved_tracker_config(gmc_method).read_text(encoding="utf-8"))
    return {
        "gmc": loaded.get("gmc_method"),
        "withReid": loaded.get("with_reid"),
        "trackBuffer": loaded.get("track_buffer"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
