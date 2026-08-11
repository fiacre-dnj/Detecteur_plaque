"""Banc de mesure de la chaîne ANPR — détection, lecture, vote.

    # L'échelle de vérité terrain : rejouable **sans aucune vidéo**, donc en CI.
    uv run python scripts/anpr_bench.py --synthetic --truth-ladder --json out/ladder.json

    # Sur de vraies vidéos, avant et après une optimisation.
    uv run python scripts/anpr_bench.py --videos D:/TesteIA/Video --frames 60 \
        --detect-every 1 --min-width 32 --ocr --json out/avant.json
    uv run python scripts/anpr_bench.py --videos D:/TesteIA/Video --frames 40 \
        --detect-every 3 --min-width 64 --json out/apres.json --compare out/avant.json

**Pourquoi un script et non la feature `benchmark`.** Celle-ci est une capacité
HTTP persistée en base, limitée à deux exécutions par heure, et son port
`InferenceProbe` mesure « une inférence sur une image fixe, sans suivi » — le
contraire de ce qu'il faut ici. Le précédent est `fetch_*.py` : hors de `src/`,
donc hors de la règle de dépendance qu'outille `test_architecture.py`, et un
`print` y est légitime.

**Pourquoi ce banc existe.** Aucun chiffre des ADR 0007 et 0008 n'est rejouable :
tous ont été produits hors dépôt, à la main. C'est un problème parce que l'ADR
0008 a déjà démontré une fois que l'intuition se trompe ici — « agrandir le
recadrage n'apporte rien » était faux, et seule la mesure l'a dit. Optimiser sans
banc, c'est refaire cette erreur en espérant qu'elle ne se voie pas.

**Ce que le JSON doit porter pour être comparable.** Les paramètres de rendu de
l'échelle synthétique y sont écrits : sans eux, deux exécutions ne mesurent pas la
même chose et le `--compare` compare deux inconnues. C'est déjà la raison pour
laquelle `BenchmarkRun` persiste `imageHash`.

**Le chiffre qui explique tout** est le couple `textsDecoded` / `textsPublished`.
Un `118 / 0` signifie que la chaîne lit du bruit et le refuse — ce qui est le
comportement voulu, et non une panne. Il ressort en gras sur la sortie standard,
parce que c'est celui qu'on vient chercher sans le savoir.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings
from traffic_analysis.features.counting.application.dto import (
    BoundingBox,
    PlateGeometry,
)
from traffic_analysis.features.models_registry.infrastructure.plate_detector import (
    OnnxPlateDetector,
)
from traffic_analysis.features.models_registry.infrastructure.plate_reader import (
    OnnxPlateReader,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import numpy.typing as npt

# ── L'échelle de vérité terrain ─────────────────────────────────────────────

#: Les huit plaques de vérité terrain, telles qu'ADR 0007 les a mesurées.
#:
#: Huit et non trois : le vote a besoin d'assez d'échantillons pour qu'un palier
#: rende un score autre que 0, 1/3 ou 1. Le format est celui des plaques
#: françaises actuelles (`AB-123-CD`), qui est celui des vidéos disponibles.
TRUTH_PLATES: tuple[str, ...] = (
    "AB-123-CD",
    "EF-456-GH",
    "IJ-789-KL",
    "MN-012-OP",
    "QR-345-ST",
    "UV-678-WX",
    "YZ-901-AB",
    "CD-234-EF",
)

#: Les paliers de largeur, en pixels. 320 est une plaque de plan serré, 48 celle
#: d'une caméra de carrefour à trente mètres.
#:
#: Ils ne sont pas choisis : ce sont ceux d'ADR 0007, et le banc doit reproduire
#: son tableau 8/8 → 0/8 à l'identique avant qu'on puisse lui faire confiance pour
#: mesurer autre chose.
TRUTH_LADDER_WIDTHS: tuple[int, ...] = (320, 160, 128, 96, 80, 64, 48)


@dataclass(frozen=True, slots=True)
class RenderParams:
    """Comment une plaque de synthèse est dégradée. **Écrit dans le JSON.**

    Sans ces valeurs dans la sortie, deux exécutions du banc ne sont pas
    comparables et un `--compare` compare deux inconnues. Même discipline que
    l'`imageHash` que `BenchmarkRun` persiste déjà.
    """

    #: Rendu à cette largeur avant réduction : une plaque nette existe d'abord,
    #: puis on la dégrade. Rendre directement à 48 px produirait un texte
    #: crénelé qui n'a rien d'une photographie.
    source_width: int = 640
    #: Rayon du flou gaussien, en fraction de la largeur cible. Une plaque de 48 px
    #: n'est pas une plaque de 320 px réduite : elle est aussi plus floue.
    blur_ratio: float = 0.012
    #: Écart-type du bruit gaussien, en niveaux de gris.
    noise_sigma: float = 4.0
    #: Qualité JPEG du ré-encodage. 70 est celui d'un flux de caméra ordinaire.
    jpeg_quality: int = 70
    #: Inclinaison en degrés — une plaque n'est jamais parfaitement de face.
    skew_degrees: float = 3.0

    def as_json(self) -> dict[str, Any]:
        return {
            "sourceWidth": self.source_width,
            "blurRatio": self.blur_ratio,
            "noiseSigma": self.noise_sigma,
            "jpegQuality": self.jpeg_quality,
            "skewDegrees": self.skew_degrees,
        }


def render_plate(text: str, width: int, params: RenderParams, seed: int) -> npt.NDArray[np.uint8]:
    """Rend une plaque de synthèse dégradée, à la largeur demandée.

    **Déterministe pour un `seed` donné** : le bruit vient d'un générateur
    explicitement graine, jamais de `np.random` global. Sans cela, deux exécutions
    du même palier donneraient deux scores et le banc ne prouverait rien.

    L'ordre des dégradations suit celui d'une vraie chaîne d'acquisition : le
    rendu net, l'inclinaison optique, la réduction du capteur, le flou de
    l'objectif, le bruit du capteur, la compression du flux. Les appliquer dans un
    autre ordre — comprimer avant de réduire, par exemple — mesurerait une chaîne
    qui n'existe pas.
    """
    height = max(8, round(width / 4.6))  # 4,6:1, le rapport d'une plaque française
    source_width = params.source_width
    source_height = max(8, round(source_width / 4.6))

    plate = np.full((source_height, source_width, 3), 235, dtype=np.uint8)
    scale = cv2.getFontScaleFromHeight(
        cv2.FONT_HERSHEY_SIMPLEX, round(source_height * 0.55), thickness=2
    )
    size, _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.putText(
        plate,
        text,
        ((source_width - size[0]) // 2, (source_height + size[1]) // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )

    if params.skew_degrees != 0.0:
        matrix = cv2.getRotationMatrix2D(
            (source_width / 2.0, source_height / 2.0), params.skew_degrees, 1.0
        )
        plate = cv2.warpAffine(
            plate,
            matrix,
            (source_width, source_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

    plate = cv2.resize(plate, (width, height), interpolation=cv2.INTER_AREA)

    radius = max(1, int(width * params.blur_ratio) * 2 + 1)
    plate = cv2.GaussianBlur(plate, (radius, radius), 0)

    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, params.noise_sigma, plate.shape)
    plate = np.clip(plate.astype(np.float64) + noise, 0, 255).astype(np.uint8)

    ok, encoded = cv2.imencode(".jpg", plate, [cv2.IMWRITE_JPEG_QUALITY, params.jpeg_quality])
    if ok:
        decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if decoded is not None:
            plate = decoded
    return plate.astype(np.uint8)


# ── Accumulateurs de mesure ─────────────────────────────────────────────────


@dataclass(slots=True)
class DetectionStats:
    """Ce que la passe de **détection** a coûté et rendu."""

    inferences: int = 0
    boxes_raw: int = 0
    boxes_kept: int = 0
    #: Motifs de rejet ventilés. Un total de rejets sans ventilation ne dit pas
    #: quelle borne resserrer, donc ne sert à rien pour régler quoi que ce soit.
    rejections: dict[str, int] = field(default_factory=dict)
    #: Largeur de plaque relative à celle du véhicule — l'histogramme qui a montré
    #: la séparation nette entre 25 % et 98 %.
    relative_widths: list[float] = field(default_factory=list)
    frame_ms: list[float] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "inferences": self.inferences,
            "boxesRaw": self.boxes_raw,
            "boxesKept": self.boxes_kept,
            "rejections": dict(sorted(self.rejections.items())),
            "relativeWidthHistogram": _histogram(self.relative_widths, (0.05, 0.1, 0.25, 0.5, 0.9)),
            "msPerFrame": _percentiles(self.frame_ms),
        }


@dataclass(slots=True)
class OcrStats:
    """Ce que la passe de **lecture** a coûté et rendu."""

    attempts: int = 0
    #: Textes que le réseau a rendus, quel qu'en soit le score.
    texts_decoded: int = 0
    #: Textes réellement **publiés**, c'est-à-dire au-dessus du seuil de score.
    #: L'écart entre les deux est le chiffre qui explique un silence complet.
    texts_published: int = 0
    crop_ms: list[float] = field(default_factory=list)
    widths: list[float] = field(default_factory=list)
    #: Justesse par palier de largeur : `{"64": (2, 8)}` = 2 bonnes sur 8 tentées.
    by_width_bucket: dict[str, tuple[int, int]] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "textsDecoded": self.texts_decoded,
            "textsPublished": self.texts_published,
            "msPerCrop": _percentiles(self.crop_ms),
            "widthHistogram": _histogram(self.widths, (48.0, 64.0, 96.0, 150.0, 300.0)),
            "byWidthBucket": {
                bucket: {"correct": correct, "attempted": attempted}
                for bucket, (correct, attempted) in sorted(
                    self.by_width_bucket.items(), key=lambda item: -float(item[0])
                )
            },
        }


def _percentiles(values: Sequence[float]) -> dict[str, float]:
    """p50 et p95. Une moyenne cacherait la queue, et c'est la queue qui gêne."""
    if not values:
        return {"p50": 0.0, "p95": 0.0, "count": 0}
    ordered = sorted(values)
    return {
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
        "count": len(ordered),
    }


def _histogram(values: Sequence[float], edges: Sequence[float]) -> dict[str, int]:
    """Histogramme à bornes explicites, du plus petit au plus grand."""
    counts: dict[str, int] = {}
    for value in values:
        label = f"<{edges[0]}"
        for low, high in itertools.pairwise(edges):
            if low <= value < high:
                label = f"{low}-{high}"
                break
        else:
            if value >= edges[-1]:
                label = f">={edges[-1]}"
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


# ── Le mode « échelle de vérité terrain » ───────────────────────────────────


def run_truth_ladder(
    reader: OnnxPlateReader, params: RenderParams, widths: Sequence[int]
) -> dict[str, Any]:
    """Rejoue le tableau 8/8 → 0/8 des ADR, à chaque palier de largeur.

    **C'est la partie rejouable sans les vidéos**, donc en CI. Elle valide le banc
    lui-même avant qu'on lui fasse confiance pour mesurer autre chose : si elle ne
    reproduit pas le tableau d'origine, ce n'est pas la chaîne qui a changé, c'est
    le banc qui mesure mal.

    Chaque plaque est lue **isolément** et non en lot : le lot est le chemin de
    production, mais ici on veut la justesse par palier, et un lot mélangerait les
    largeurs dans une seule inférence.
    """
    from traffic_analysis.features.counting.domain.plate_text import normalise_plate_text

    rungs: list[dict[str, Any]] = []
    for width in widths:
        correct = 0
        decoded = 0
        durations: list[float] = []
        readings: list[dict[str, Any]] = []

        for seed, truth in enumerate(TRUTH_PLATES):
            plate = render_plate(truth, width, params, seed)
            height = plate.shape[0]
            # La vignette **est** l'image : la boîte couvre tout, ce qui isole la
            # lecture de toute question de recadrage.
            box = BoundingBox(x=0.0, y=0.0, width=float(width), height=float(height))

            started = time.perf_counter()
            results = reader.read(plate, (box,))
            durations.append((time.perf_counter() - started) * 1000.0)

            reading = results[0] if results else None
            published = "" if reading is None else normalise_plate_text(reading.text)
            expected = normalise_plate_text(truth)
            if reading is not None:
                decoded += 1
            if published and published == expected:
                correct += 1
            readings.append(
                {
                    "truth": expected,
                    "read": published,
                    "score": None if reading is None else round(reading.score, 3),
                }
            )

        rungs.append(
            {
                "widthPx": width,
                "correct": correct,
                "attempted": len(TRUTH_PLATES),
                "decoded": decoded,
                "msPerPlate": _percentiles(durations),
                "readings": readings,
            }
        )
    return {"renderParams": params.as_json(), "rungs": rungs}


# ── Le mode « vraies vidéos » ───────────────────────────────────────────────


def iter_frames(video: Path, limit: int, stride: int) -> Iterator[npt.NDArray[np.uint8]]:
    """Rend au plus `limit` images, une sur `stride`. Ferme toujours le décodeur."""
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            return
        index = 0
        yielded = 0
        while yielded < limit:
            ok, frame = capture.read()
            if not ok:
                return
            if index % stride == 0:
                yielded += 1
                yield frame
            index += 1
    finally:
        capture.release()


def run_videos(
    videos: Sequence[Path],
    detector: OnnxPlateDetector,
    reader: OnnxPlateReader | None,
    *,
    frames: int,
    stride: int,
    min_width: float,
) -> tuple[DetectionStats, OcrStats, list[dict[str, Any]]]:
    """Mesure la chaîne sur de vraies images.

    **Sans suivi ni vote** : le banc mesure le coût et le rendement des deux passes
    d'inférence, pas le comptage. Ajouter le suivi mêlerait deux sources de
    variation — le détecteur de véhicules et le détecteur de plaques — et on ne
    saurait pas laquelle a bougé. Les véhicules sont donc approchés par une grille
    de recadrages de taille réaliste.
    """
    from traffic_analysis.features.counting.domain.plate_text import normalise_plate_text

    detection = DetectionStats()
    ocr = OcrStats()
    sources: list[dict[str, Any]] = []

    for video in videos:
        digest = hashlib.sha256(video.read_bytes()[:1_048_576]).hexdigest()[:16]
        counted = 0
        for frame in iter_frames(video, frames, stride):
            counted += 1
            boxes = _pseudo_vehicles(frame.shape[1], frame.shape[0])

            started = time.perf_counter()
            found = detector.detect_many(frame, boxes)
            detection.frame_ms.append((time.perf_counter() - started) * 1000.0)
            detection.inferences += 1

            for box, plates in zip(boxes, found, strict=True):
                detection.boxes_raw += len(plates)
                for plate in plates:
                    detection.boxes_kept += 1
                    detection.relative_widths.append(plate.box.width / max(1.0, box.width))

                    if reader is None or plate.box.width < min_width:
                        if reader is not None:
                            detection.rejections["sous_min_width"] = (
                                detection.rejections.get("sous_min_width", 0) + 1
                            )
                        continue

                    ocr.attempts += 1
                    ocr.widths.append(plate.box.width)
                    started = time.perf_counter()
                    texts = reader.read(frame, (plate.box,))
                    ocr.crop_ms.append((time.perf_counter() - started) * 1000.0)

                    reading = texts[0] if texts else None
                    if reading is None:
                        continue
                    ocr.texts_decoded += 1
                    if normalise_plate_text(reading.text):
                        ocr.texts_published += 1

        sources.append({"name": video.name, "sha256Prefix": digest, "framesRead": counted})

    return detection, ocr, sources


def _pseudo_vehicles(width: int, height: int) -> tuple[BoundingBox, ...]:
    """Une grille de recadrages de taille plausible, à défaut de vrai suivi.

    Ce n'est **pas** une détection de véhicules et le banc ne prétend pas le
    contraire : c'est une charge de travail reproductible pour le détecteur de
    plaques, de la même taille et au même endroit d'une exécution à l'autre. Le
    coût par recadrage et la ventilation des rejets, eux, sont réels.
    """
    side_w = width // 3
    side_h = height // 2
    return tuple(
        BoundingBox(
            x=float(column * side_w),
            y=float(row * side_h),
            width=float(side_w),
            height=float(side_h),
        )
        for row in range(2)
        for column in range(3)
    )


# ── Rendu, comparaison, CLI ─────────────────────────────────────────────────


def print_ladder(ladder: dict[str, Any]) -> None:
    """L'échelle, en français, sur la sortie standard."""
    print("\n  Échelle de vérité terrain — lecture par palier de largeur")
    print("  " + "─" * 58)
    print(f"  {'largeur':>9}  {'justes':>8}  {'décodés':>8}  {'ms/plaque p50':>14}")
    for rung in ladder["rungs"]:
        print(
            f"  {rung['widthPx']:>7} px  "
            f"{rung['correct']:>3}/{rung['attempted']:<4}  "
            f"{rung['decoded']:>8}  "
            f"{rung['msPerPlate']['p50']:>14}"
        )
    print(
        "\n  « justes » compte les lectures **publiées** et exactes ; « décodés »\n"
        "  celles que le réseau a rendues, seuil de score compris. Un écart large\n"
        "  entre les deux est le comportement voulu : la chaîne lit du bruit et le\n"
        "  refuse, plutôt que de publier une plaque plausible et fausse."
    )


def print_run(report: dict[str, Any]) -> None:
    """Le rapport d'une exécution sur vidéos."""
    detection = report["detection"]
    ocr = report["ocr"]

    print("\n  Détection de plaques")
    print("  " + "─" * 58)
    print(f"  inférences            {detection['inferences']:>10}")
    print(f"  boîtes gardées        {detection['boxesKept']:>10}")
    print(f"  ms/image p50          {detection['msPerFrame']['p50']:>10}")
    print(f"  ms/image p95          {detection['msPerFrame']['p95']:>10}")
    if detection["rejections"]:
        print("  rejets :")
        for reason, count in detection["rejections"].items():
            print(f"    {reason:<24}{count:>8}")

    print("\n  Lecture (OCR)")
    print("  " + "─" * 58)
    print(f"  tentatives            {ocr['attempts']:>10}")
    print(f"  ms/vignette p50       {ocr['msPerCrop']['p50']:>10}")
    # **Le chiffre qui explique tout.** Un « 118 décodés / 0 publiés » dit que la
    # chaîne lit du bruit et le refuse — comportement voulu, et non panne. Il est
    # mis en avant parce que c'est celui qu'on vient chercher sans le savoir.
    print(f"\n  >>> textes décodés {ocr['textsDecoded']}  —  PUBLIÉS {ocr['textsPublished']} <<<")
    if ocr["textsDecoded"] > 0 and ocr["textsPublished"] == 0:
        print(
            "  Aucun texte publié alors que le réseau en a décodé : les vignettes\n"
            "  sont sous le plancher de lecture (~64 px mesurés). Ce n'est pas une\n"
            "  panne — la chaîne refuse d'inventer."
        )


def print_comparison(current: dict[str, Any], previous: dict[str, Any]) -> None:
    """Deux colonnes et un delta, sur les chiffres qui décident d'un arbitrage."""
    print("\n  Comparaison — avant → après")
    print("  " + "─" * 58)
    rows = (
        ("détection ms/image p50", ("detection", "msPerFrame", "p50")),
        ("détection ms/image p95", ("detection", "msPerFrame", "p95")),
        ("boîtes gardées", ("detection", "boxesKept")),
        ("OCR tentatives", ("ocr", "attempts")),
        ("OCR textes publiés", ("ocr", "textsPublished")),
    )
    for label, path in rows:
        before = _dig(previous, path)
        after = _dig(current, path)
        ratio = "" if not before else f"  (×{after / before:.2f})"
        print(f"  {label:<24}{before:>10} → {after:>10}{ratio}")


def _dig(report: dict[str, Any], path: Sequence[str]) -> float:
    value: Any = report
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return 0.0
        value = value[key]
    return float(value) if isinstance(value, (int | float)) else 0.0


def _videos_in(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    suffixes = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    return sorted(path for path in root.rglob("*") if path.suffix.lower() in suffixes)


def _sha256_of(path: Path) -> str | None:
    """Empreinte d'un artefact de modèle, pour que le contexte soit vérifiable.

    Sans elle, deux rapports produits avec deux versions du même modèle se
    comparent en silence, et le delta est attribué au réglage qu'on venait de
    changer.
    """
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Banc de mesure de la chaîne ANPR (détection, lecture, vote).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Mesure sur des plaques de synthèse plutôt que sur des vidéos.",
    )
    parser.add_argument(
        "--truth-ladder",
        action="store_true",
        help="Rejoue l'échelle 320 à 48 px des ADR. Implique --synthetic.",
    )
    parser.add_argument("--videos", type=Path, help="Fichier ou dossier de vidéos.")
    parser.add_argument("--frames", type=int, default=40, help="Images analysées par vidéo.")
    parser.add_argument("--stride", type=int, default=1, help="Une image sur N.")
    parser.add_argument(
        "--detect-every",
        type=int,
        default=1,
        help="Cadence de détection ; consignée dans le contexte du JSON.",
    )
    parser.add_argument(
        "--mosaic-side",
        type=int,
        default=None,
        help="Côté de la mosaïque. Par défaut : la valeur de la configuration.",
    )
    parser.add_argument(
        "--min-width",
        type=float,
        default=32.0,
        help="Largeur minimale d'une vignette envoyée à l'OCR.",
    )
    parser.add_argument("--ocr", action="store_true", help="Active la passe de lecture.")
    parser.add_argument("--json", type=Path, help="Écrit le rapport complet à ce chemin.")
    parser.add_argument("--compare", type=Path, help="Rapport JSON antérieur à comparer.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()

    # Le service pose ce budget dans son `lifespan`, avant toute inférence. Le banc
    # doit le poser aussi, et pour la même raison : mesurer une machine dont les
    # cœurs sont tous pris quand le service, lui, en laisse au navigateur donnerait
    # des chiffres qui ne décrivent aucune exécution réelle.
    if settings.inference_threads > 0:
        from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry

        ModelRegistry(
            settings.weights_dir,
            max_loaded=settings.max_loaded_models,
            device=settings.device,
            half=settings.half,
        ).apply_thread_budget(settings.inference_threads)

    synthetic = args.synthetic or args.truth_ladder
    if not synthetic and args.videos is None:
        print("Indiquez --videos, ou --synthetic --truth-ladder.", file=sys.stderr)
        return 2

    reader = OnnxPlateReader(
        settings.resolved_plate_ocr_model_path,
        settings.resolved_plate_ocr_charset_path,
        min_score=settings.plate_ocr_min_text_score,
        # Résolu, comme le fait le conteneur : un banc qui mesurerait une autre
        # configuration que le service ne mesurerait pas le service.
        intra_op_threads=settings.resolved_plate_ocr_intra_op_threads,
        variants=settings.plate_ocr_variants,
        dynamic_width=settings.plate_ocr_dynamic_width,
    )

    mosaic_side = args.mosaic_side if args.mosaic_side is not None else settings.plate_mosaic_side
    context: dict[str, Any] = {
        "device": settings.device,
        "half": settings.half,
        "weightsDir": str(settings.weights_dir),
        "plateModelSha256": _sha256_of(settings.resolved_plate_model_path),
        "plateOcrModelSha256": _sha256_of(settings.resolved_plate_ocr_model_path),
        "settings": {
            "detectEvery": args.detect_every,
            "mosaicSide": mosaic_side,
            "minWidthPx": args.min_width,
            "ocrMinTextScore": settings.plate_ocr_min_text_score,
            "ocrVariants": settings.plate_ocr_variants,
        },
    }
    report: dict[str, Any] = {"context": context}

    if synthetic:
        if not reader.available:
            print(
                "Le modèle d'OCR ou son dictionnaire est absent : l'échelle ne peut "
                f"pas être mesurée.\nCherché dans {settings.weights_dir}.\n"
                "Récupérez-les avec scripts/fetch_plate_ocr_model.py.",
                file=sys.stderr,
            )
            return 1
        ladder = run_truth_ladder(reader, RenderParams(), TRUTH_LADDER_WIDTHS)
        report["truthLadder"] = ladder
        print_ladder(ladder)
    else:
        videos = _videos_in(args.videos)
        if not videos:
            print(f"Aucune vidéo trouvée dans {args.videos}.", file=sys.stderr)
            return 1
        detector = OnnxPlateDetector(
            settings.resolved_plate_model_path,
            settings.plate_confidence,
            iou=settings.plate_iou,
            mosaic_side=mosaic_side,
            geometry=PlateGeometry(max_per_vehicle=settings.plate_max_per_vehicle),
        )
        if not detector.available:
            print(
                "Le modèle de plaques est absent : rien à mesurer.\n"
                f"Cherché à {settings.resolved_plate_model_path}.",
                file=sys.stderr,
            )
            return 1

        detection, ocr, sources = run_videos(
            videos,
            detector,
            reader if args.ocr and reader.available else None,
            frames=args.frames,
            stride=args.stride,
            min_width=args.min_width,
        )
        report["sources"] = sources
        report["detection"] = detection.as_json()
        report["ocr"] = ocr.as_json()
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


if __name__ == "__main__":
    raise SystemExit(main())
