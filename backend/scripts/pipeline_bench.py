"""Banc de mesure du pipeline de comptage — où passent les millisecondes.

    # Référence, avant toute optimisation.
    uv run python scripts/pipeline_bench.py --videos data/jobs --frames 300 --json out/avant.json

    # Après un levier, avec l'écart chiffré.
    uv run python scripts/pipeline_bench.py --videos data/jobs --frames 300 \
        --imgsz 512 --batch 4 --json out/apres.json --compare out/avant.json

    # Ce que la résolution coûte, à contenu identique.
    uv run python scripts/pipeline_bench.py --videos data/jobs/<id> \
        --ladder 720,1080,1440,2160 --frames 200 --json out/echelle.json

    # Avec l'ANPR et l'OCR, c'est-à-dire les deux tiers du budget réel.
    uv run python scripts/pipeline_bench.py --videos data/jobs/<id> --anpr --ocr \
        --frames 120 --json out/anpr.json --compare out/anpr-avant.json

**Pourquoi ce banc existe.** Le total « 47 ms par image » ne dit pas *où* elles
passent, et sans ce partage toute optimisation est un pari. `scripts/anpr_bench.py`
mesure la **justesse** de la chaîne ANPR ; celui-ci mesure ce qui tourne à
**chaque** image du comptage : décodage, prétraitement, inférence, NMS, suivi,
détection de plaques, OCR, domaine, sérialisation.

**Ce qu'il mesure vraiment, et ce qu'il ne mesure pas.** Sans `--anpr`, il fait
tourner le **vrai** `UltralyticsEngine` et la **vraie** `AnalysisSession`, dans
l'ordre où `AnalysisService.run_video` les enchaîne, avec la même sérialisation par
`snapshot()` — c'est le chemin chaud du comptage, isolé. Avec `--anpr`, il fait
tourner la **vraie** `AnalysisService`, assemblée par le **même** code que le
service (`build_counting_stack`) : c'est la seule façon de mesurer les deux étages
de plaques sans réécrire l'orchestration, donc sans mesurer un pipeline qui
n'existe pas. Dans les deux cas, la publication SSE de progression et d'aperçu
reste dehors.

**Le banc ne bride jamais.** `analysis_speed` et `max_analysis_fps` restent à
`None` : une analyse bridée mesure son bridage, pas la machine
(`AnalysisService.run_video`).

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

Les deux étages de plaques, eux, sont chronométrés en enveloppant `detect_many` et
`read` — les deux frontières que le service traverse, donc les deux seuls endroits
où le coût est attribuable sans supposer quoi que ce soit du contenu des
adaptateurs.

**Le chiffre qu'on vient chercher** est `framesPerSecond`, et le partage explique
pourquoi il vaut ce qu'il vaut. Le second chiffre, tout aussi important, est le
bloc `counts` : une optimisation qui change `trackedVehicles`, `crossings` ou les
plaques publiées n'est pas une optimisation, c'est une régression déguisée en gain.

**Le troisième bloc est `work`, et sans lui l'échelle de résolution ne s'explique
pas.** Il compte les recadrages soumis au détecteur de plaques et les vignettes
soumises à l'OCR, **par image analysée**. Les deux seuils qui les gouvernent sont en
pixels absolus (`plate_detect_min_vehicle_width_px`, `plate_ocr_min_width_px`) : en
720p presque aucun véhicule ne les franchit, en 2160p presque tous. Sans ces deux
compteurs, on lit « l'OCR coûte trois fois plus cher en 4K » sans savoir si c'est
par lecture ou par nombre de lectures — deux causes, deux gestes opposés.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.container import build_counting_stack
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

    from traffic_analysis.features.counting.application.analysis_service import AnalysisService

#: Extensions considérées comme des vidéos quand `--videos` désigne un dossier.
VIDEO_SUFFIXES = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})

#: Seuil de confiance par défaut, **lu sur le contrat** et non recopié.
#:
#: Il décide du fichier de tracker dérivé (`track_high_thresh` / `new_track_thresh`,
#: ADR 0024) : le banc doit donc l'annoncer, et l'annoncer juste. Le figer ici à
#: « 0,35 » se serait désynchronisé du service au premier changement de défaut, et le
#: rapport aurait affirmé une valeur que la course n'avait pas utilisée.
DEFAULT_CONFIDENCE = AnalysisJobConfig(model_id="").confidence_threshold

#: Postes **contenus** dans un autre, et qui ne s'additionnent donc pas au total.
#:
#: Sans cette mention, un lecteur additionne `plateDetect` (46,6 %) et
#: `plateInference` (35,1 %) et obtient 82 % pour un seul étage. Le rapport le disait
#: déjà pour `decodeAndOther` (« par différence ») et se taisait sur `gmc`, contenu
#: dans `tracker` depuis toujours.
_CONTAINED_IN = {
    "gmc": " (inclus dans tracker)",
    "plateInference": " (inclus dans plateDetect)",
}

#: Plancher sous lequel une queue de distribution ne dit plus rien.
#:
#: Le rapport `max > 2 × p50` est le bon signal sur un poste qui coûte des dizaines
#: de millisecondes (ADR 0033 : p50 27 ms, max 1 238). Sur un poste sub-milliseconde
#: il ne décrit que la gigue de l'ordonnanceur, et un ⚠ à chaque course est un ⚠
#: qu'on apprend à ignorer.
TAIL_MIN_MS = 1.0


@dataclass
class Stage:
    """Un poste de dépense, en millisecondes par image analysée."""

    name: str
    samples: list[float] = field(default_factory=list)

    def add(self, milliseconds: float) -> None:
        self.samples.append(milliseconds)

    @property
    def total_ms(self) -> float:
        return sum(self.samples)

    def per_frame_ms(self, frames: int) -> float:
        """Coût **par image analysée**, et non par appel.

        La distinction n'existait pas quand tous les postes recevaient exactement un
        échantillon par image ; elle est devenue nécessaire avec l'OCR, que le service
        appelle **une fois par piste** (ADR 0030 : c'est la bonne forme, un lot commun
        est 1,6× plus lent). Moyenner ses échantillons donnerait le coût d'une lecture
        et le rangerait dans une colonne qui annonce des millisecondes par image —
        deux ou trois fois trop bas sur une scène chargée, et la somme des postes ne
        vaudrait plus le total mesuré au poignet.
        """
        return self.total_ms / frames if frames > 0 else 0.0

    @property
    def calls(self) -> int:
        return len(self.samples)

    def spread(self) -> dict[str, float]:
        """Médiane, p90 et maximum d'un poste — **par appel**, pas par image.

        **Une moyenne a caché six pauses d'une seconde pendant toute une session.**
        L'étage de plaques affichait 99 ms par image ; sa médiane valait 27 ms et six
        appels sur 90 dépassaient la seconde, pesant à eux seuls 73 % du poste. Les deux
        lectures appellent des gestes opposés — un coût se réduit en travaillant moins,
        une pause se supprime en trouvant ce qui bloque (ADR 0033 : l'autotune cuDNN qui
        réétalonne à chaque nouvelle forme d'entrée).

        Un écart franc entre `mean` et `p50` est donc le signal à lire en premier.
        """
        if not self.samples:
            return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0}
        ordered = sorted(self.samples)
        return {
            "mean": statistics.fmean(ordered),
            "p50": statistics.median(ordered),
            "p90": ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))],
            "max": ordered[-1],
        }


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
    plate_detect: Stage = field(default_factory=lambda: Stage("plateDetect"))
    #: Temps **GPU** du détecteur de plaques, extrait de son propre `result.speed`.
    #:
    #: **Le poste qui manquait pour trancher.** `plateDetect` pèse 45 à 73 % du budget
    #: selon la scène, mais mélange recadrage numpy, letterbox, inférence CUDA, NMS et
    #: `_select` : impossible de dire si le levier est « moins de pixels » ou « moins
    #: de Python ». Ultralytics produit un `speed` synchronisé (`ops.Profile(device=…)`)
    #: pour ce modèle comme pour l'autre ; il suffisait de le lire.
    #:
    #: **Contenu dans `plateDetect`**, donc exclu de `measured_ms()` exactement comme
    #: `gmc` l'est de `tracker` : une somme de postes qui excède le total mesuré au
    #: poignet se lit comme une erreur de mesure, et c'en serait une.
    plate_inference: Stage = field(default_factory=lambda: Stage("plateInference"))
    ocr: Stage = field(default_factory=lambda: Stage("ocr"))
    domain: Stage = field(default_factory=lambda: Stage("domain"))
    serialise: Stage = field(default_factory=lambda: Stage("serialise"))
    wall_ms: float = 0.0
    frames: int = 0
    #: Recadrages de véhicules soumis au détecteur de plaques, tous appels confondus.
    plate_crops: int = 0
    #: Vignettes de plaques soumises à l'OCR, tous appels confondus.
    ocr_plates: int = 0
    #: Crête d'allocation torch sur la carte, en mébioctets. `None` hors GPU.
    #:
    #: **Le seul chiffre qui attribue la VRAM à NOTRE processus** : `memory.used` de
    #: NVML est celle de toute la carte, compositeur de bureau compris. Sur 4 Gio
    #: partagés, c'est lui qui dit à quelle distance du mur on est — et donc si un
    #: `--batch` plus grand ou un palier plus lourd tient.
    vram_peak_mib: float | None = None
    vram_reserved_mib: float | None = None
    #: Utilisation GPU échantillonnée pendant la course. `None` sans `--gpu-probe`.
    gpu: dict[str, float] | None = None

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
            + self.plate_detect.total_ms
            + self.ocr.total_ms
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
                "preprocess": round(self.preprocess.per_frame_ms(self.frames), 2),
                "inference": round(self.inference.per_frame_ms(self.frames), 2),
                "postprocess": round(self.postprocess.per_frame_ms(self.frames), 2),
                "tracker": round(self.tracker.per_frame_ms(self.frames), 2),
                "gmc": round(self.gmc.per_frame_ms(self.frames), 2),
                "plateDetect": round(self.plate_detect.per_frame_ms(self.frames), 2),
                "plateInference": round(self.plate_inference.per_frame_ms(self.frames), 2),
                "ocr": round(self.ocr.per_frame_ms(self.frames), 2),
                "domain": round(self.domain.per_frame_ms(self.frames), 2),
                "serialise": round(self.serialise.per_frame_ms(self.frames), 2),
                "decodeAndOther": round(rest / per_frame, 2),
            },
            # **Par appel**, et non par image : c'est la seule lecture qui distingue
            # un poste cher d'un poste qui *stalle*. Voir `Stage.spread`.
            "perCall": {
                name: {key: round(value, 2) for key, value in stage.spread().items()}
                for name, stage in (
                    ("preprocess", self.preprocess),
                    ("inference", self.inference),
                    ("postprocess", self.postprocess),
                    ("tracker", self.tracker),
                    ("plateDetect", self.plate_detect),
                    ("plateInference", self.plate_inference),
                    ("ocr", self.ocr),
                    # `domain` et `serialise` n'en avaient pas, alors que ce sont deux
                    # étages CPU du chemin critique : on n'en connaissait que la
                    # moyenne, c'est-à-dire la lecture qui a caché six pauses d'une
                    # seconde pendant toute une session (voir `Stage.spread`).
                    ("domain", self.domain),
                    ("serialise", self.serialise),
                    ("gmc", self.gmc),
                )
            },
            # `decodeAndOther` n'a **pas** de `perCall`, et c'est délibéré : il est
            # obtenu par différence, donc il n'a pas d'appels, donc pas de
            # distribution. Lui en fabriquer une serait la seule vraie malhonnêteté
            # possible dans ce rapport.
            "vram": {
                "peakMib": self.vram_peak_mib,
                "reservedMib": self.vram_reserved_mib,
            },
            "gpu": self.gpu,
            # Le **volume de travail**, sans lequel une variation de coût ne
            # s'interprète pas : 3 ms de plus par image peuvent venir d'un étage
            # devenu plus lent ou de deux fois plus de plaques soumises, et les deux
            # appellent le contraire l'un de l'autre.
            "work": {
                "plateCropsPerFrame": round(self.plate_crops / per_frame, 2),
                "plateDetectCallsPerFrame": round(self.plate_detect.calls / per_frame, 2),
                "ocrPlatesPerFrame": round(self.ocr_plates / per_frame, 2),
                "ocrCallsPerFrame": round(self.ocr.calls / per_frame, 2),
            },
        }


def summarise_samples(samples: Sequence[float]) -> dict[str, float]:
    """p50 / p90 / max d'une série. Fonction **pure**, donc testable sans GPU.

    Séparée du fil d'échantillonnage exprès : c'est l'agrégation qu'on veut
    vérifier, pas la capacité de la CI à parler à un pilote NVIDIA.
    """
    if not samples:
        return {"p50": 0.0, "p90": 0.0, "max": 0.0, "samples": 0}
    ordered = sorted(samples)
    return {
        "p50": round(statistics.median(ordered), 1),
        "p90": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 1),
        "max": round(ordered[-1], 1),
        "samples": len(ordered),
    }


class _GpuSampler:
    """Relève l'utilisation GPU pendant une course, dans un fil démon.

    **Pourquoi ça vaut un fil.** Aucun poste du rapport ne dit si la carte est
    saturée : `inference` est un plancher de temps GPU, `plateDetect` mélange GPU et
    CPU, et la fourchette qui en résulte est trop large pour décider. Un relevé
    externe (`nvidia-smi --loop-ms`) répond, mais il faut le recoller à la main et il
    ne vit pas dans le rapport — donc `--compare` ne le voit pas et un rapport
    archivé perd son contexte.

    **5 Hz et pas plus.** `utilization.gpu` de NVML est un *rapport cyclique* sur la
    dernière période d'échantillonnage du pilote, laquelle est fixée entre 1 s et
    1/6 s selon le produit : interroger plus vite rend deux fois la même valeur,
    c'est-à-dire de la fausse précision.

    **Ce que le chiffre dit, et ce qu'il ne dit pas.** C'est le pourcentage de temps
    pendant lequel *au moins un* noyau tournait — pas un taux d'occupation des unités
    de calcul. 100 % peut vouloir dire un seul petit noyau en permanence.
    """

    def __init__(self, period_s: float = 0.2) -> None:
        self._period_s = period_s
        self._samples: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handle: Any = None

    def start(self) -> bool:
        """Rend `False` si la sonde est indisponible — jamais une exception.

        Un banc qui tomberait en marche parce que sa sonde manque serait pire qu'un
        banc sans sonde.
        """
        try:
            import pynvml

            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            return False

        def loop() -> None:
            import pynvml

            while not self._stop.wait(self._period_s):
                # Une lecture ratée n'arrête pas le relevé : un pilote occupé rend
                # parfois une erreur transitoire, et perdre un échantillon sur deux
                # cents vaut mieux que perdre la course.
                with suppress(Exception):
                    rates = pynvml.nvmlDeviceGetUtilizationRates(self._handle)
                    self._samples.append(float(rates.gpu))

        self._thread = threading.Thread(target=loop, name="bench-gpu-probe", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> dict[str, float]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        return summarise_samples(self._samples)


class _GpuProbe:
    """Relevé GPU **et** crête VRAM, encadrant exactement la fenêtre mesurée.

    Deux instruments complémentaires, et ils ne concluent qu'ensemble : NVML donne
    le rapport cyclique sans attribution, le partage par étage donne l'attribution
    sans savoir ce qui est GPU. La crête torch, elle, est le seul chiffre qui
    attribue la VRAM à **notre** processus — `memory.used` de NVML est celle de toute
    la carte, compositeur de bureau compris.

    `start()` est appelée à la **fin du rodage** : un relevé qui le couvrirait
    décrirait une passe qu'on vient justement de jeter. Même raison pour
    `reset_peak_memory_stats`.
    """

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled
        self._sampler: _GpuSampler | None = None
        self._torch: Any = None

    def start(self) -> None:
        if not self._enabled:
            return
        sampler = _GpuSampler()
        if sampler.start():
            self._sampler = sampler
        else:
            print("  ⚠ sonde GPU indisponible (pynvml) — course sans relevé")
        try:
            import torch

            if torch.cuda.is_available():
                self._torch = torch
                torch.cuda.reset_peak_memory_stats()
        except Exception:
            self._torch = None

    def stop(self, timings: Timings) -> None:
        if self._sampler is not None:
            timings.gpu = self._sampler.stop()
        if self._torch is not None:
            timings.vram_peak_mib = round(self._torch.cuda.max_memory_allocated() / 2**20, 1)
            timings.vram_reserved_mib = round(self._torch.cuda.max_memory_reserved() / 2**20, 1)


@contextmanager
def _gpu_probe(timings: Timings, *, enabled: bool) -> Iterator[None]:
    """`_GpuProbe` pour les chemins dont la fenêtre mesurée est déjà isolée."""
    probe = _GpuProbe(enabled=enabled)
    probe.start()
    try:
        yield
    finally:
        probe.stop(timings)


@contextmanager
def _instrumented(timings: Timings, *, plates: bool = False) -> Iterator[None]:
    """Enveloppe les points que le chrono d'Ultralytics n'atteint pas.

    Le suivi et la compensation de mouvement vivent dans la roue `ultralytics`, le
    domaine et les deux étages de plaques dans le nôtre. Tous sont restaurés à la
    sortie : un banc qui laisserait des enveloppes en place fausserait la mesure
    suivante.

    `_to_observations` est enveloppée pour une autre raison : c'est le seul
    endroit où le `Results` d'Ultralytics — donc son `speed` — traverse notre
    adaptateur. Le moteur ne le publie pas, et il n'a pas à le faire pour un banc.

    `plates` enveloppe en plus `detect_many`, `read` et `snapshot()`. Les trois sont
    posés sur les **classes** et non sur les instances, parce que le banc mesure ce
    que le service assemble : il ne construit pas lui-même les adaptateurs, il
    demande à `build_analysis_service` de le faire.
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
        if plates:
            with _instrumented_plates(timings):
                yield
        else:
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


@contextmanager
def _instrumented_plates(timings: Timings) -> Iterator[None]:
    """Chronomètre les deux étages de plaques **et le volume qu'ils reçoivent**.

    Les deux frontières que le service traverse sont `detect_many` et `read` : c'est
    là que le coût est attribuable sans rien supposer du contenu des adaptateurs, et
    c'est là que se compte le travail soumis — recadrages de véhicules d'un côté,
    vignettes de plaques de l'autre.

    `snapshot()` est enveloppée ici et non plus dans la boucle du banc : sur le
    chemin de la vraie `AnalysisService`, la sérialisation a lieu **dedans**
    (invariant 8 — après la passe ANPR *et* après l'OCR), donc le seul point de
    mesure possible est la méthode elle-même.
    """
    from traffic_analysis.features.counting.domain.models import SessionTrack
    from traffic_analysis.features.models_registry.infrastructure.plate_detector import (
        UltralyticsPlateDetector,
    )
    from traffic_analysis.features.models_registry.infrastructure.plate_reader import (
        OnnxPlateReader,
    )

    original_detect = UltralyticsPlateDetector.detect_many
    original_read = OnnxPlateReader.read
    original_snapshot = SessionTrack.snapshot
    original_ensure = UltralyticsPlateDetector._ensure_loaded

    def timed_ensure(self: Any) -> Any:  # noqa: ANN401
        """Enveloppe le `predict` de l'instance **au premier chargement**.

        C'est le seul crochet possible : le modèle de plaques est un objet
        d'Ultralytics que nous ne possédons pas, et son chargement est paresseux.
        L'envelopper à la classe toucherait aussi le détecteur de véhicules.
        """
        model = original_ensure(self)
        if model is None or getattr(model, "_bench_wrapped", False):
            return model

        inner = model.predict

        def timed_predict(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            results = inner(*args, **kwargs)
            # **Sommer, jamais prendre le premier.** Ultralytics divise `speed` par la
            # taille du lot, donc `results[0].speed["inference"]` est le coût par
            # RECADRAGE, pas par appel. La somme rend le total de l'appel — et c'est
            # ce qui rend le poste comparable à `plateDetect`, qui est mesuré par appel.
            total = 0.0
            for result in results or ():
                speed = getattr(result, "speed", None) or {}
                total += float(speed.get("inference") or 0.0)
            if total > 0.0:
                timings.plate_inference.add(total)
            return results

        model.predict = timed_predict
        model._bench_wrapped = True
        return model

    def timed_detect(self: Any, image: Any, boxes: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        # Matérialisé avant l'appel : le port accepte une `Sequence`, et un
        # générateur consommé par l'adaptateur ne se compterait plus après.
        submitted = tuple(boxes)
        started = perf_counter()
        try:
            return original_detect(self, image, submitted, *args, **kwargs)
        finally:
            timings.plate_detect.add((perf_counter() - started) * 1000.0)
            timings.plate_crops += len(submitted)

    def timed_read(self: Any, image: Any, boxes: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        submitted = tuple(boxes)
        started = perf_counter()
        try:
            return original_read(self, image, submitted, *args, **kwargs)
        finally:
            timings.ocr.add((perf_counter() - started) * 1000.0)
            timings.ocr_plates += len(submitted)

    def timed_snapshot(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        started = perf_counter()
        try:
            return original_snapshot(self, *args, **kwargs)
        finally:
            timings.serialise.add((perf_counter() - started) * 1000.0)

    UltralyticsPlateDetector.detect_many = timed_detect  # type: ignore[method-assign]
    UltralyticsPlateDetector._ensure_loaded = timed_ensure  # type: ignore[method-assign]
    OnnxPlateReader.read = timed_read  # type: ignore[method-assign]
    SessionTrack.snapshot = timed_snapshot  # type: ignore[method-assign]
    try:
        yield
    finally:
        UltralyticsPlateDetector.detect_many = original_detect  # type: ignore[method-assign]
        UltralyticsPlateDetector._ensure_loaded = original_ensure  # type: ignore[method-assign]
        OnnxPlateReader.read = original_read  # type: ignore[method-assign]
        SessionTrack.snapshot = original_snapshot  # type: ignore[method-assign]


def run_video(
    engine: UltralyticsEngine,
    video: Path,
    config: AnalysisJobConfig,
    *,
    frames: int,
    warmup_frames: int,
    gpu_probe: bool = False,
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
    # Démarrée **à la fin du rodage** et non ici : un relevé qui couvrirait le rodage
    # décrirait une passe qu'on vient justement de jeter.
    probe = _GpuProbe(enabled=gpu_probe)

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
                probe.start()
                started = perf_counter()
            if started is not None and analysed - warmup_frames >= frames:
                break

    probe.stop(timings)
    if started is None:  # vidéo plus courte que le rodage demandé
        timings.wall_ms = 0.0
        timings.frames = 0
    else:
        timings.wall_ms = (perf_counter() - started) * 1000.0
        timings.frames = analysed - warmup_frames

    return timings, _counts(session.stats())


def run_video_with_plates(
    service: AnalysisService,
    video: Path,
    config: AnalysisJobConfig,
    *,
    frames: int,
    warmup_frames: int,
    gpu_probe: bool = False,
) -> tuple[Timings, dict[str, Any]]:
    """Même mesure, mais par la **vraie** `AnalysisService`, ANPR et OCR comprises.

    **Deux courses et non une boucle interrompue.** Le chemin sans plaques peut jeter
    ses échantillons de rodage au vol, parce qu'il tient lui-même la boucle ; ici
    c'est `run_video` qui la tient, et il n'existe aucun crochet pour lui dire
    « recommence à mesurer maintenant ». Le rodage est donc une course jetée, bornée
    par `end_ms` — et c'est aussi bien : chaque course repart d'un suivi vierge et de
    politiques d'étranglement neuves (une instance par `run_video`), donc la course
    mesurée ne traîne rien de celle qui l'a précédée.

    La fenêtre est convertie en temps de scène, seule unité que `AnalysisJobConfig`
    accepte (invariant 1) : `frames × stride / fps`, borne de fin **exclue**.
    """
    info = service.probe(video)
    if info.fps <= 0.0:
        # Sans cadence, aucune borne ne se calcule et le banc analyserait le fichier
        # entier en croyant mesurer 120 images. Le dire plutôt que de mesurer faux.
        msg = f"{video.name} ne déclare pas de cadence : impossible de borner la mesure."
        raise SystemExit(msg)

    stride = max(1, config.frame_stride)
    per_frame_ms = stride / info.fps * 1000.0

    if warmup_frames > 0:
        # Jetée : ni chronomètre ni compteurs. La première inférence d'un modèle
        # paie sa fusion de couches et l'autotune cuDNN, et le premier chargement du
        # détecteur de plaques et de l'OCR s'y ajoute (les deux sont paresseux).
        service.run_video(
            "bench-warmup",
            video,
            replace(config, end_ms=config.start_ms + warmup_frames * per_frame_ms),
        )

    timings = Timings()
    # La fenêtre est comptée **depuis le début demandé**, pas depuis celui du fichier :
    # `--start` sans échelle vise une fenêtre du fichier réel, et la borne de fin doit
    # la suivre. La borne est exclue, comme partout (ADR 0028).
    measured = replace(config, end_ms=config.start_ms + frames * per_frame_ms)
    with _instrumented(timings, plates=True), _gpu_probe(timings, enabled=gpu_probe):
        started = perf_counter()
        result = service.run_video("bench", video, measured)
        timings.wall_ms = (perf_counter() - started) * 1000.0
    timings.frames = len(result.timeline)
    return timings, _counts(result.stats, result.vehicles)


def _counts(stats: Any, vehicles: Sequence[Any] = ()) -> dict[str, Any]:  # noqa: ANN401
    """Le garde-fou de justesse : ce qu'une optimisation ne doit pas changer.

    Il est rendu à côté du débit et jamais dans un second tableau : un gain payé par
    un comptage différent n'est pas un gain, et le lire ailleurs laisserait croire le
    contraire.
    """
    counts: dict[str, Any] = {
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
    if vehicles:
        # **Les textes et pas seulement leur nombre.** Un levier qui publie autant de
        # plaques mais deux d'entre elles différentes n'est pas neutre, et un compte
        # égal le cacherait. Triés : l'ordre du registre suit les identités, qui
        # bougent au moindre changement de suivi.
        counts["platesPublished"] = sorted(
            record.plate_text for record in vehicles if record.plate_text
        )
    return counts


def _discard(timings: Timings) -> None:
    """Vide les échantillons de rodage, en gardant les postes en place."""
    for stage in (
        timings.preprocess,
        timings.inference,
        timings.postprocess,
        timings.tracker,
        timings.gmc,
        timings.plate_detect,
        timings.plate_inference,
        timings.ocr,
        timings.domain,
        timings.serialise,
    ):
        stage.samples.clear()
    timings.plate_crops = 0
    timings.ocr_plates = 0


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


def _source_name(video: Path) -> str:
    """Nom porté par le rapport, et clé d'appariement de `--compare`.

    Les vidéos déposées vivent toutes sous `data/jobs/<id>/input.mp4` : garder le
    nom de fichier donnerait « input.mp4 » pour toutes, et `--compare` apparierait
    n'importe quelle course avec n'importe quelle autre.
    """
    return video.parent.name if video.name == "input.mp4" else video.name


def _ladder(
    engine: UltralyticsEngine,
    video: Path,
    heights: Sequence[int],
    *,
    frames_needed: int,
    cache: Path,
    start_s: float = 0.0,
) -> list[tuple[Path, str]]:
    """Réencode `video` à chaque palier de hauteur et rend les fichiers obtenus.

    **Pourquoi réencoder, et pourquoi réencoder *aussi* à la hauteur d'origine.**
    Ce que l'on veut isoler est le coût du **pixel**, pas celui du codec : comparer
    le fichier source (le H.264 d'une caméra) à des paliers réencodés mesurerait les
    deux à la fois, et attribuerait au 4K un surcoût qui vient du conteneur. Chaque
    palier passe donc par le même encodeur, y compris celui qui ne change pas la
    taille.

    **Le contenu est identique d'un palier à l'autre**, à l'échantillonnage près :
    c'est ce qui rend les **comptages** comparables, donc ce qui permet de dire qu'un
    écart de cadence est un écart de coût et non un écart de scène. Un palier plus
    haut que la source suréchantillonne — il n'ajoute aucun détail, ce qui est
    exactement la propriété qu'on cherche pour mesurer le surcoût par pixel seul.

    Seules les `frames_needed` premières images sont écrites : réencoder six minutes
    de 4K pour en mesurer deux cents coûterait des gigaoctets et un quart d'heure.
    Le fichier est gardé en cache et n'est réécrit que s'il manque.
    """
    info = engine.probe(video)
    if info.height <= 0 or info.width <= 0:
        msg = f"{video.name} : dimensions illisibles, échelle impossible."
        raise SystemExit(msg)

    cache.mkdir(parents=True, exist_ok=True)
    produced: list[tuple[Path, str]] = []
    for height in heights:
        # Largeur paire : plusieurs encodeurs refusent une dimension impaire en
        # 4:2:0, et l'échec est un fichier vide plutôt qu'une erreur.
        width = max(2, round(info.width * height / info.height / 2) * 2)
        # Le début fait partie du **nom** : deux fenêtres d'une même vidéo ne
        # contiennent pas la même circulation, donc pas les mêmes comptages, et les
        # ranger sous le même fichier de cache ferait comparer deux scènes.
        window = "" if start_s <= 0.0 else f"-t{start_s:g}"
        target = cache / f"{_source_name(video)}{window}-{height}p.mp4"
        codec = "cache"
        if not target.is_file():
            codec = _transcode(
                video, target, width, height, info.fps, frames_needed, start_s=start_s
            )
        produced.append((target, codec))
    return produced


def _transcode(
    source: Path,
    target: Path,
    width: int,
    height: int,
    fps: float,
    frames: int,
    *,
    start_s: float = 0.0,
) -> str:
    """Écrit `frames` images de `source` en `width`×`height`. Rend le codec retenu.

    `avc1` d'abord, `mp4v` en repli : le premier est le codec des vraies caméras,
    donc celui dont le coût de décodage nous intéresse — mais toutes les roues
    d'OpenCV ne l'embarquent pas en écriture, et un `VideoWriter` qui ne s'ouvre pas
    ne lève pas : il rend `isOpened() == False` puis écrit dans le vide. Le codec
    retenu part dans le rapport, parce qu'il change ce que la colonne
    `decodeAndOther` veut dire.

    `start_s` **ne sert qu'ici**, et c'est délibéré : le palier produit commence à
    l'instant demandé, donc la mesure part toujours de l'image 0 de son fichier. Le
    faire porter par `start_ms` de la requête aurait fait basculer la course sur le
    chemin de déplacement du moteur — un autre chemin, sans lot d'images — et deux
    paliers mesurés sur deux chemins différents ne se comparent pas. Le déplacement
    est ici **approximatif** et cela ne coûte rien : on fabrique un asset de test, on
    ne date aucun franchissement.
    """
    import cv2

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        msg = f"{source} n'a pas pu être ouverte pour le réencodage."
        raise SystemExit(msg)
    if start_s > 0.0:
        capture.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)

    writer = None
    codec = ""
    try:
        for candidate in ("avc1", "mp4v"):
            writer = cv2.VideoWriter(
                str(target), cv2.VideoWriter_fourcc(*candidate), fps, (width, height)
            )
            if writer.isOpened():
                codec = candidate
                break
            writer.release()
        if writer is None or not codec:
            msg = "Aucun codec d'écriture disponible (ni avc1 ni mp4v)."
            raise SystemExit(msg)

        written = 0
        while written < frames:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA))
            written += 1
        print(f"  échelle : {target.name} — {written} images, codec {codec}")
        if written == 0:
            # Un fichier vide ferait échouer la mesure bien plus loin, sur un message
            # parlant de cadence ou de fenêtre vide, très loin de la cause.
            target.unlink(missing_ok=True)
            msg = f"{source} n'a rendu aucune image : échelle impossible."
            raise SystemExit(msg)
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    return codec


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
        per_call = timing.get("perCall", {})
        for name, value in sorted(stages.items(), key=lambda item: -item[1]):
            share = 100.0 * value / timing["msPerFrame"] if timing["msPerFrame"] else 0.0
            marker = _CONTAINED_IN.get(name, "")
            if name == "decodeAndOther":
                marker = " (par différence)"
            spread = per_call.get(name)
            # La queue de distribution n'est affichée que si elle dit quelque chose :
            # un maximum au double de la médiane est une pause, pas un coût.
            #
            # **Plus un plancher absolu**, et il n'est pas cosmétique : sur un poste
            # sub-milliseconde comme `domain`, un maximum à 0,36 ms pour une médiane à
            # 0,14 franchit le rapport de 2 sans rien signaler d'autre que la gigue de
            # l'ordonnanceur. Sans plancher, chaque course afficherait un ⚠ « p50 0 /
            # p90 0 / max 0 » — un avertissement qu'on apprend à ignorer, ce qui est
            # pire que pas d'avertissement.
            tail = ""
            if (
                spread
                and spread["p50"]
                and spread["max"] > 2.0 * spread["p50"]
                and spread["max"] >= TAIL_MIN_MS
            ):
                digits = 2 if spread["p50"] < 1.0 else 0
                tail = (
                    f"   ⚠ par appel : p50 {spread['p50']:.{digits}f} / "
                    f"p90 {spread['p90']:.{digits}f} / max {spread['max']:.{digits}f} ms"
                )
            print(f"      {name:<16} {value:>6.2f} ms  {share:>5.1f} %{marker}{tail}")
        counts = source["counts"]
        near = sum(counts.get("nearMisses", {}).values())
        print(
            f"    comptage : {counts['trackedVehicles']} véhicules suivis, "
            f"{counts['crossings']} franchissements, {near} quasi-franchissements"
        )
        work = timing.get("work", {})
        if work.get("plateCropsPerFrame") or work.get("ocrPlatesPerFrame"):
            # Le volume soumis, **par image analysée** : c'est lui qui explique
            # pourquoi le même étage coûte trois fois plus cher en 4K.
            print(
                f"    travail  : {work['plateCropsPerFrame']:.2f} recadrages/image "
                f"({work['plateDetectCallsPerFrame']:.2f} appels), "
                f"{work['ocrPlatesPerFrame']:.2f} vignettes OCR/image "
                f"({work['ocrCallsPerFrame']:.2f} appels)"
            )
        plates = counts.get("platesPublished")
        if plates is not None:
            listed = " — " + ", ".join(plates) if plates else ""
            print(f"    plaques  : {len(plates)} publiées{listed}")


#: Réglages du contexte qui décident **de ce qui est compté**.
#:
#: Comparer les comptages de deux courses qui n'ont pas analysé la même chose produit
#: une alerte qui n'apprend rien — et qu'on apprend donc à ignorer, ce qui est le pire
#: sort possible pour un garde-fou. `batch` et `cudnnAutotune` en sont **absents**
#: exprès : ils changent le débit, jamais les boîtes.
COMPARABLE_SETTINGS = (
    "modelId",
    "imgsz",
    "confidence",
    "stride",
    "frames",
    "start",
    "anpr",
    "ocr",
    "plateNetSize",
    "gmc",
    "withReid",
    "trackHighThresh",
    "newTrackThresh",
)


def incomparable_settings(current: dict[str, Any], previous: dict[str, Any]) -> list[str]:
    """Les réglages qui diffèrent et qui interdisent de comparer les comptages."""
    now = current.get("context", {}).get("settings", {})
    was = previous.get("context", {}).get("settings", {})
    return [key for key in COMPARABLE_SETTINGS if now.get(key) != was.get(key)]


def print_comparison(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    """Écart au rapport antérieur, débit **et** justesse. Rend « un comptage a changé ».

    Les deux sont affichés côte à côte délibérément : un gain de débit payé par un
    comptage différent n'est pas un gain, et les lire dans deux tableaux séparés
    laisserait croire le contraire.

    Le booléen rendu est ce qui permet à `main` de sortir en erreur : jusqu'ici la
    comparaison **affichait** « LE COMPTAGE A CHANGÉ » puis rendait `0` dans tous les
    cas, donc aucun script ni aucun crochet ne pouvait échouer sur une régression de
    justesse.
    """
    changed = False
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
            changed = True
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
            # Les plaques publiées sont au garde-fou de l'ANPR ce que les totaux sont
            # à celui du comptage : un levier qui en publie autant mais deux
            # différentes n'est pas neutre, et un compte égal le cacherait.
            was_plates = older["counts"].get("platesPublished")
            now_plates = source["counts"].get("platesPublished")
            if was_plates != now_plates:
                print(f"      plaques : {was_plates} → {now_plates}")
        else:
            print("    comptage identique.")

    return changed


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
        "--plate-net-size",
        type=int,
        default=None,
        help=(
            "Côté de l'entrée du détecteur de plaques. Sans effet sans --anpr. "
            "Par défaut : le réglage TRAFFIC_PLATE_NET_SIZE."
        ),
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=DEFAULT_CONFIDENCE,
        help=(
            "Seuil de confiance de la requête. Il ne filtre plus le détecteur (ADR 0024) "
            "mais décide ce qui devient une piste, et part dans le fichier de tracker."
        ),
    )
    parser.add_argument(
        "--anpr",
        action="store_true",
        help=(
            "Mesure avec la détection de plaques, par la vraie AnalysisService. "
            "Sans ce drapeau, le banc ne mesure que le comptage."
        ),
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help=(
            "Mesure aussi la lecture du texte. Implique --anpr : "
            "lire sans détecter n'a pas de sens."
        ),
    )
    parser.add_argument(
        "--ladder",
        default=None,
        help=(
            "Hauteurs à mesurer, séparées par des virgules (ex. 720,1080,1440,2160). "
            "Chaque vidéo est réencodée à chaque palier, y compris à sa hauteur d'origine."
        ),
    )
    parser.add_argument(
        "--ladder-dir",
        type=Path,
        default=Path("out/ladder"),
        help="Où garder les paliers réencodés. Ils sont réutilisés d'une course à l'autre.",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=0.0,
        help=(
            "Seconde de la vidéo où la mesure commence. Les premières secondes d'un clip "
            "sont souvent vides, et une course sans véhicule ne mesure ni l'ANPR ni l'OCR. "
            "Avec --ladder, le palier réencodé commence à cet instant ; sans, la fenêtre "
            "est portée par la requête, sur le fichier réel."
        ),
    )
    parser.add_argument(
        "--gpu-probe",
        dest="gpu_probe",
        action="store_true",
        help=(
            "Relève l'utilisation GPU (pynvml, 5 Hz) et la crête VRAM torch pendant "
            "la fenêtre mesurée. Aucun poste du rapport ne dit si la carte est "
            "saturée : « inference » est un plancher de temps GPU et « plateDetect » "
            "mélange GPU et CPU. Opt-in, jamais par défaut — la sonde est un fil de "
            "plus, et son coût doit être mesuré avant d'être cru."
        ),
    )
    parser.add_argument(
        "--cudnn",
        dest="cudnn",
        default=None,
        action="store_true",
        help=(
            "Force l'autotune cuDNN, désactivé par défaut depuis ADR 0033 — il "
            "réétalonne à chaque nouvelle forme d'entrée, et le détecteur de plaques "
            "lui en présente une par recadrage. Par défaut : le réglage "
            "TRAFFIC_INFERENCE_CUDNN_AUTOTUNE."
        ),
    )
    parser.add_argument(
        "--no-cudnn",
        dest="cudnn",
        action="store_false",
        help="Force l'autotune cuDNN à l'arrêt, pour chiffrer ce qu'il coûte.",
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
    # Le service pose ces budgets dans son `lifespan`, avant toute inférence : un
    # banc qui ne les poserait pas mesurerait une autre machine que la sienne.
    #
    # **Les deux**, et la garde porte sur les deux. Ne passer que le premier laissait
    # `TRAFFIC_OPENCV_THREADS` sans effet *dans le banc* : on aurait comparé deux
    # courses identiques en croyant mesurer un réglage — le pire état d'un outil de
    # mesure, et la version en miroir du défaut que la garde d'`app_factory` évite.
    if settings.inference_threads > 0 or settings.opencv_threads > 0:
        registry.apply_thread_budget(settings.inference_threads, settings.opencv_threads)

    # Le `gmc_method` vient du réglage, exactement comme dans `container.py`. Le
    # passer par la ligne de commande servirait à comparer deux valeurs sans toucher
    # à l'environnement ; à `None` près, c'est le service qu'on mesure.
    gmc = args.gmc if args.gmc is not None else settings.tracker_gmc
    imgsz = args.imgsz if args.imgsz is not None else settings.inference_imgsz
    batch = args.batch if args.batch is not None else settings.inference_batch
    # Le service pose aussi l'autotune cuDNN dans son `lifespan`, avant toute
    # inférence : sans lui, le banc mesurerait des algorithmes de convolution que le
    # service n'utilise pas. Il suit donc le **réglage**, et les deux drapeaux servent à
    # chiffrer l'échange sans toucher à l'environnement (ADR 0033).
    cudnn = args.cudnn if args.cudnn is not None else settings.inference_cudnn_autotune
    if cudnn:
        registry.enable_cudnn_autotune()
    engine = UltralyticsEngine(registry, gmc_method=gmc, imgsz=imgsz, batch=batch)
    model_id = args.model or settings.default_model_id

    # `--ocr` implique `--anpr`, comme dans le service : lire sans détecter n'a pas
    # de sens, il n'y aurait aucune boîte à lire. Sans cette ligne, `--ocr` seul
    # produirait une course parfaitement silencieuse qui ne mesure rien.
    anpr = args.anpr or args.ocr
    # Le côté de l'entrée des plaques voyage par **réglage** et non par argument
    # d'appel : le remplacer ici demande donc de reconstruire les réglages. Une
    # reconstruction et non un `model_copy`, qui ne revalide rien : la valeur doit
    # passer par le même contrôle que le service, où un côté qui n'est pas multiple de
    # 32 est refusé plutôt qu'arrondi en silence par Ultralytics.
    if args.plate_net_size is not None:
        settings = Settings(**{**settings.model_dump(), "plate_net_size": args.plate_net_size})
    stack = build_counting_stack(settings, registry, engine=engine) if anpr else None
    if stack is not None:
        # Annoncé, jamais subi : `AnalysisService` se contente d'un avertissement
        # quand les poids manquent et rend un comptage sans plaques. Un banc qui
        # afficherait « --anpr » au-dessus de zéro recadrage serait exactement la
        # panne silencieuse que ce dépôt a déjà payée quatre fois.
        if not stack.plate_detector.available:
            print(
                "  ⚠ modèle de plaques absent : la course ne mesurera aucune détection.",
                file=sys.stderr,
            )
        if args.ocr and not stack.plate_reader.available:
            print(
                "  ⚠ modèle d'OCR ou dictionnaire absent : aucune lecture ne sera mesurée.",
                file=sys.stderr,
            )

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
                # **Il manquait, et son absence rendait `--compare` menteur** : deux
                # rapports mesurant deux fenêtres différentes de la même vidéo portent
                # le même nom de source, donc l'appariement se faisait en silence et
                # annonçait un écart de comptage qui n'était qu'un changement de scène.
                "start": args.start,
                "confidence": args.confidence,
                "gpuProbe": bool(args.gpu_probe),
                # Annoncé, jamais supposé : c'est ce réglage qui décide si un poste
                # coûte ou s'il stalle, donc un rapport qui ne le porte pas n'est pas
                # comparable à un autre (ADR 0033).
                "cudnnAutotune": cudnn,
                "anpr": anpr,
                "ocr": args.ocr,
                "plateNetSize": settings.plate_net_size if anpr else None,
                # Relus depuis le fichier **réellement utilisé** plutôt que
                # supposés : c'est lui qui décide, et un rapport qui annoncerait
                # autre chose que ce qui a tourné serait pire qu'un rapport sans
                # cette ligne.
                **_tracker_settings(gmc, args.confidence, registry, model_id),
            },
        },
        "sources": [],
    }

    for video, codec in _sources(engine, videos, args):
        info = engine.probe(video)
        config = AnalysisJobConfig(
            model_id=model_id,
            confidence_threshold=args.confidence,
            frame_stride=args.stride,
            lines=_mid_cross(info.width, info.height),
            detect_plates=anpr,
            read_plate_text=args.ocr,
            # **`--start` est consommé une seule fois.** Avec une échelle, il l'est par
            # le réencodage : le palier *commence* à l'instant demandé, et remettre la
            # borne ici sauterait deux fois la même durée. Sans échelle, c'est la
            # requête qui porte la fenêtre, sur le fichier réel et son vrai codec.
            start_ms=0.0 if args.ladder is not None else args.start * 1000.0,
        )
        if stack is not None:
            timings, counts = run_video_with_plates(
                stack.analysis,
                video,
                config,
                frames=args.frames,
                warmup_frames=args.warmup,
                gpu_probe=args.gpu_probe,
            )
        else:
            timings, counts = run_video(
                engine,
                video,
                config,
                frames=args.frames,
                warmup_frames=args.warmup,
                gpu_probe=args.gpu_probe,
            )
        report["sources"].append(
            {
                "name": _source_name(video),
                "width": info.width,
                "height": info.height,
                "fps": info.fps,
                # `""` hors échelle : le codec du fichier d'origine n'est pas
                # connu d'ici, et l'inventer serait pire que de se taire.
                "encodedAs": codec,
                "timings": timings.as_json(),
                "counts": counts,
            }
        )

    print_run(report)

    status = 0
    if args.compare is not None and args.compare.is_file():
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        differing = incomparable_settings(report, previous)
        if differing:
            # **Refusé AVANT d'être comparé**, et avec un code distinct. Deux courses
            # qui n'ont pas analysé la même chose produiraient un écart de comptage
            # qui n'est qu'un changement de scène — exactement le genre d'alerte
            # qu'on apprend à ignorer, donc le pire sort d'un garde-fou.
            print(
                "\n  ⚠ COMPARAISON REFUSÉE — les deux courses ne mesurent pas la "
                f"même chose : {', '.join(differing)}"
            )
            status = 3
        elif print_comparison(report, previous):
            status = 2

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\n  Rapport écrit : {args.json}")
    # `2` = régression de justesse, `3` = contexte incomparable, `1` = aucune vidéo.
    # Trois codes distincts parce qu'ils appellent trois gestes différents, et parce
    # qu'un `0` universel rendait tout crochet de non-régression impossible.
    return status


def _sources(
    engine: UltralyticsEngine, videos: Sequence[Path], args: argparse.Namespace
) -> list[tuple[Path, str]]:
    """Les vidéos à mesurer, avec le codec de chacune. Développe `--ladder`.

    Sans `--ladder`, les fichiers passent tels quels et le codec est inconnu — le
    champ reste vide plutôt que d'affirmer quoi que ce soit.
    """
    if args.ladder is None:
        return [(video, "") for video in videos]

    heights = [int(part) for part in str(args.ladder).split(",") if part.strip()]
    if not heights:
        msg = "--ladder attend au moins une hauteur (ex. 720,1080)."
        raise SystemExit(msg)

    # Les deux chemins ne lisent pas le même nombre d'images : sans plaques, rodage
    # et mesure se suivent dans la même passe ; avec plaques, ce sont deux passes qui
    # repartent du début. On écrit donc de quoi satisfaire le plus gourmand des deux.
    frames_needed = (args.warmup + args.frames) * max(1, args.stride) + max(1, args.stride)
    produced: list[tuple[Path, str]] = []
    for video in videos:
        produced.extend(
            _ladder(
                engine,
                video,
                heights,
                frames_needed=frames_needed,
                cache=args.ladder_dir,
                start_s=args.start,
            )
        )
    return produced


def _tracker_settings(
    gmc_method: str, high_thresh: float, registry: ModelRegistry, model_id: str
) -> dict[str, Any]:
    """Ce que dit le fichier de tracker **effectivement chargé** par cette course.

    Le fichier de base et le fichier dérivé ne disent pas la même chose : lire le
    premier alors que le second tourne écrirait dans le rapport une valeur que
    l'analyse n'a pas utilisée, et c'est précisément ce qu'un `--compare` ne
    pardonne pas.

    `high_thresh` est le seuil de la requête, devenu obligatoire quand ADR 0024 l'a
    fait descendre jusqu'au tracker (`track_high_thresh` **et** `new_track_thresh`).
    L'oublier ne rendait pas un chiffre faux mais un `TypeError` au démarrage : le
    banc n'a pas pu tourner entre ADR 0024 et aujourd'hui.
    """
    import yaml

    from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
        head_is_end2end,
        resolved_tracker_config,
    )

    # **Le modèle décide, donc il faut le charger pour savoir.** Le fichier de suivi
    # d'une tête `end2end` n'est pas celui d'une tête classique (ADR 0047) : demander
    # sans le modèle rendrait un `withReid: true` que la course ne respecte pas, et
    # c'est exactement le genre de rapport qui envoie chercher une régression de
    # cadence du mauvais côté. Le bail est court et l'instance est de toute façon
    # celle que la course va utiliser.
    with registry.lease(model_id) as model:
        appearance_reid = not head_is_end2end(model)
    path = resolved_tracker_config(gmc_method, high_thresh, appearance_reid)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "gmc": loaded.get("gmc_method"),
        "withReid": loaded.get("with_reid"),
        "trackBuffer": loaded.get("track_buffer"),
        "trackHighThresh": loaded.get("track_high_thresh"),
        "newTrackThresh": loaded.get("new_track_thresh"),
        # Le chemin, parce que « le fichier du dépôt » et « un dérivé dans le dossier
        # temporaire » ne se distinguent pas autrement dans un rapport archivé.
        "trackerFile": path.name,
    }


if __name__ == "__main__":
    raise SystemExit(main())
