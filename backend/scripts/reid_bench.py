"""Banc de l'encodeur de ressemblance — est-ce que ça sépare, et à partir de quand ?

    cd backend
    # La question qui décide : les embeddings séparent-ils deux véhicules ?
    uv run python scripts/reid_bench.py --videos data/jobs/<id>/input.mp4 \
        --frames 300 --json out/reid.json
    # Le prétraitement, qui n'est documenté nulle part en amont.
    uv run python scripts/reid_bench.py --videos … --variants
    # Le plancher de largeur, qui devient un réglage.
    uv run python scripts/reid_bench.py --videos … --truth-ladder

Ce banc existe pour la même raison qu'`anpr_bench.py` : ADR 0008 a démontré une fois
que l'intuition se trompe sur ce genre de question, et ADR 0032 a montré qu'un étage
peut consommer 73 % du budget pour un résultat structurellement impossible. Avant
d'écrire une interface de recherche, il faut savoir si la recherche peut marcher.

**Pourquoi il ne lit pas les captures déjà sur disque.** ADR 0042 n'écrit qu'**une**
capture par véhicule : `data/jobs/*/snapshots/` ne contient donc aucune paire
même-véhicule, et c'est exactement ce qu'il faut mesurer. Le banc extrait ses propres
recadrages en faisant tourner le vrai moteur, et garde plusieurs vues **de la même
piste** à des instants différents — ce qui donne des paires positives avec un vrai
changement d'angle, de taille et d'éclairage.

**Les trois chiffres qui décident**, et le troisième est le seul qui compte vraiment :

- `sameMean` / `diffMean` — similarité moyenne entre deux vues du même véhicule, et
  entre deux véhicules différents. Deux moyennes écartées ne suffisent pas : c'est le
  recouvrement des distributions qui décide, pas l'écart des centres ;
- `separation` — `sameMean - diffMean`, commode mais trompeur seul ;
- **`rank1`** — pour chaque vue, son plus proche voisin (elle-même exclue) appartient-il
  au même véhicule ? C'est la métrique de la tâche réelle : « retrouve ce véhicule
  parmi les autres ». À 1,0 la recherche est exacte ; à 1/n_vues elle vaut le hasard.

**Ce que ce banc ne mesure pas** : le cas inter-caméra. Toutes ses vues viennent d'une
même vidéo, donc d'un même point de vue. Une photo importée par l'utilisateur vient
d'ailleurs, et c'est plus difficile. `rank1` est donc une **borne haute** de ce que la
fonctionnalité rendra, jamais une promesse — même précaution que l'échelle synthétique
d'ADR 0029, qui rend des plaques trop propres.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings
from traffic_analysis.features.counting.application.ports import EngineSpec
from traffic_analysis.features.counting.infrastructure.onnx_vehicle_embedder import (
    EMBEDDING_DIM,
    NET_SIZE,
)
from traffic_analysis.features.counting.infrastructure.vehicle_crop import (
    VEHICLE_MARGIN,
    crop,
    resize,
    sharpness,
)
from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    UltralyticsEngine,
)

if TYPE_CHECKING:
    import numpy.typing as npt

#: Les statistiques ImageNet de `torchreid`. Elles vivent **dans le banc** et non dans
#: l'adaptateur, parce que la mesure a montré qu'elles n'ont aucun effet sur ce modèle
#: (OSNet-AIN normalise par instance). Elles restent ici pour que la variante reste
#: rejouable — c'est le seul endroit où elles ont encore un sens.
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

#: Vues gardées par piste. Au-delà, les vues d'une même piste se ressemblent trop
#: (images consécutives) et gonfleraient `sameMean` sans rien apprendre.
VIEWS_PER_TRACK = 4

#: Écart minimal, en images analysées, entre deux vues gardées d'une même piste.
#: Deux recadrages consécutifs sont quasiment le même pixel : les compter comme une
#: paire positive mesurerait la stabilité du décodeur, pas celle de l'encodeur.
MIN_VIEW_GAP_FRAMES = 8

#: Pistes minimales pour que `diffMean` veuille dire quelque chose.
MIN_TRACKS = 4

#: Paliers de largeur de l'échelle de vérité terrain, en pixels. 208 est l'entrée du
#: réseau ; en dessous, le recadrage est agrandi et n'apporte plus d'information.
LADDER_WIDTHS = (208, 160, 128, 96, 64, 48)


@dataclass(frozen=True, slots=True)
class View:
    """Une vue d'un véhicule : ses pixels, sa piste, son instant."""

    track_id: int
    frame_index: int
    width_px: float
    sharpness: float
    pixels: npt.NDArray[np.uint8]


def _preprocess(thumbs: list[npt.NDArray[np.uint8]], *, variant: str) -> npt.NDArray[np.float32]:
    """Les prétraitements candidats, dont celui que l'adaptateur embarque.

    `imagenet-rgb` est ce que `torchreid` applique à l'entraînement et ce que
    l'adaptateur fait. Les trois autres existent pour **vérifier** ce choix plutôt que
    de le supposer : le README de l'OMZ ne documente ni moyenne ni écart-type, et
    l'indice dont on dispose (`--reverse_input_channels` dans la conversion IR) ne dit
    que l'ordre des canaux.
    """
    import cv2

    mean = np.asarray(IMAGENET_MEAN, dtype=np.float32).reshape(3, 1, 1)
    std = np.asarray(IMAGENET_STD, dtype=np.float32).reshape(3, 1, 1)
    batch = np.empty((len(thumbs), 3, NET_SIZE, NET_SIZE), dtype=np.float32)
    for index, thumb in enumerate(thumbs):
        resized = cv2.resize(thumb, (NET_SIZE, NET_SIZE), interpolation=cv2.INTER_LINEAR)
        pixels = resized if variant.endswith("bgr") else resized[..., ::-1]
        planes = np.ascontiguousarray(pixels.transpose(2, 0, 1), dtype=np.float32) / 255.0
        batch[index] = (planes - mean) / std if variant.startswith("imagenet") else planes
    return batch


def _embed(session: Any, views: list[View], *, variant: str) -> npt.NDArray[np.float32]:  # noqa: ANN401
    """Encode toutes les vues et rend une matrice de vecteurs **normalisés L2**."""
    name = session.get_inputs()[0].name
    out = np.empty((len(views), EMBEDDING_DIM), dtype=np.float32)
    step = 16
    for start in range(0, len(views), step):
        chunk = views[start : start + step]
        batch = _preprocess([view.pixels for view in chunk], variant=variant)
        raw = np.asarray(session.run(None, {name: batch})[0], dtype=np.float32)
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        out[start : start + len(chunk)] = raw / np.where(norms < 1e-12, 1.0, norms)
    return out


def _score(vectors: npt.NDArray[np.float32], views: list[View]) -> dict[str, Any]:
    """Les distributions same/diff et le rang 1, sur une matrice de similarités.

    `rank1` exclut la diagonale : une vue est toujours sa plus proche voisine, et
    l'inclure rendrait 1,0 quelle que soit la qualité du modèle. C'est l'erreur qui
    ferait passer un encodeur inutile pour parfait.
    """
    tracks = np.asarray([view.track_id for view in views])
    similarity = vectors @ vectors.T
    same_mask = tracks[:, None] == tracks[None, :]
    np.fill_diagonal(same_mask, False)

    same = similarity[same_mask]
    diff = similarity[~same_mask & ~np.eye(len(views), dtype=bool)]
    if same.size == 0 or diff.size == 0:
        return {"error": "pas assez de paires : augmentez --frames ou changez de vidéo"}

    ranked = similarity.copy()
    np.fill_diagonal(ranked, -np.inf)
    nearest = ranked.argmax(axis=1)
    # Une piste vue une seule fois n'a aucun voisin correct atteignable : l'inclure
    # plafonnerait `rank1` sous 1,0 pour une raison qui ne dit rien de l'encodeur.
    answerable = same_mask.any(axis=1)
    hits = tracks[nearest][answerable] == tracks[answerable]

    return {
        "views": len(views),
        "tracks": len(set(tracks.tolist())),
        "sameMean": round(float(same.mean()), 4),
        "sameMin": round(float(same.min()), 4),
        "diffMean": round(float(diff.mean()), 4),
        "diffMax": round(float(diff.max()), 4),
        "separation": round(float(same.mean() - diff.mean()), 4),
        "rank1": round(float(hits.mean()), 4) if hits.size else None,
        "rank1Answerable": int(answerable.sum()),
    }


def _collect(engine: UltralyticsEngine, video: Path, spec: EngineSpec, frames: int) -> list[View]:
    """Plusieurs vues par piste, en faisant tourner le vrai moteur.

    Le recadrage passe par `vehicle_crop.crop` avec `VEHICLE_MARGIN` : c'est **la**
    définition d'une vignette de véhicule, la même que celle des captures et celle que
    l'adaptateur applique. Mesurer sur un autre cadrage mesurerait autre chose que ce
    qui sera livré.
    """
    per_track: dict[int, list[View]] = {}
    for processed, frame in enumerate(engine.iter_video(video, spec)):
        if processed >= frames:
            break
        for track in frame.tracks:
            kept = per_track.setdefault(track.track_id, [])
            if len(kept) >= VIEWS_PER_TRACK:
                continue
            if kept and frame.frame_index - kept[-1].frame_index < MIN_VIEW_GAP_FRAMES:
                continue
            thumb = crop(frame.image, track.box, margin=VEHICLE_MARGIN)
            if thumb is None:
                continue
            pixels = np.ascontiguousarray(thumb)
            kept.append(
                View(
                    track_id=track.track_id,
                    frame_index=frame.frame_index,
                    width_px=track.box.width,
                    sharpness=sharpness(pixels),
                    pixels=pixels,
                )
            )
    # Une piste vue une seule fois ne produit aucune paire positive : elle reste utile
    # comme distracteur pour `diffMean`, donc on la garde.
    return [view for views in per_track.values() for view in views]


def _at_width(views: list[View], width: int) -> list[View]:
    """Les mêmes vues, ramenées à une largeur donnée. Jamais agrandies.

    C'est ce qui rend l'échelle honnête : on ne demande pas au réseau de lire une
    image qu'on vient d'inventer, on lui donne la même scène **moins définie**, ce qui
    est ce qu'un véhicule plus lointain produit réellement.

    L'appelant doit avoir **déjà** restreint `views` au vivier commun (voir
    `_ladder_pool`) : sans cela chaque palier noterait une population différente. La
    première version de ce banc comparait ainsi 4 pistes à 160 px avec 9 pistes à
    48 px, et présentait le tout comme une progression — deux tâches de difficultés
    différentes lues comme une dégradation de l'encodeur.
    """
    out: list[View] = []
    for view in views:
        native = view.pixels.shape[1]
        smaller = view.pixels if native <= width else resize(view.pixels, width / native)
        out.append(
            View(
                track_id=view.track_id,
                frame_index=view.frame_index,
                width_px=float(min(native, width)),
                sharpness=sharpness(smaller),
                pixels=smaller,
            )
        )
    return out


def _ladder_pool(views: list[View], anchor: int) -> list[View]:
    """Le vivier commun : les vues nativement au moins aussi larges que le plus haut
    palier.

    Décidé **une fois** pour tous les paliers : c'est la seule façon qu'une baisse de
    rang-1 d'un rang au suivant veuille dire « la définition manque » plutôt que « la
    population a changé ».
    """
    return [view for view in views if view.pixels.shape[1] >= anchor]


def _session(path: Path) -> Any:  # noqa: ANN401
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def _print(title: str, result: dict[str, Any]) -> None:
    if "error" in result:
        print(f"  {title:22s} {result['error']}")
        return
    rank1 = result["rank1"]
    # Le nombre de pistes est **affiché à côté du rang-1**, et ce n'est pas décoratif :
    # un rang-1 de 100 % sur quatre véhicules très différents ne dit presque rien, et
    # c'est le piège dans lequel la première course de ce banc est tombée. La difficulté
    # de la tâche est proportionnelle au nombre de distracteurs.
    print(
        f"  {title:14s} {result['tracks']:>3d} pistes / {result['views']:>3d} vues  "
        f"same {result['sameMean']:+.3f} (min {result['sameMin']:+.3f})  "
        f"diff {result['diffMean']:+.3f} (max {result['diffMax']:+.3f})  "
        f"écart {result['separation']:+.3f}  "
        f"rang-1 {'—' if rank1 is None else f'{rank1:.1%}'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=Path, required=True, help="Fichier ou dossier de vidéos.")
    parser.add_argument("--frames", type=int, default=300, help="Images analysées par vidéo.")
    parser.add_argument("--model", default=None, help="Identifiant de modèle du catalogue.")
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--start", type=float, default=0.0, help="Début en secondes.")
    parser.add_argument(
        "--variants", action="store_true", help="Compare les quatre prétraitements."
    )
    parser.add_argument("--truth-ladder", action="store_true", help="Sépare-t-on encore à 64 px ?")
    parser.add_argument("--json", type=Path, help="Écrit le rapport complet à ce chemin.")
    args = parser.parse_args()

    settings = Settings()
    weights = settings.resolved_reid_model_path
    if not weights.is_file():
        sys.stdout.write(
            f"Encodeur absent : {weights}\n"
            "Lancez `uv run python scripts/fetch_reid_model.py` (voir .env.example).\n"
        )
        return 1

    videos = sorted(args.videos.glob("**/*.mp4")) if args.videos.is_dir() else [args.videos]
    if not videos:
        sys.stdout.write(f"Aucune vidéo sous {args.videos}\n")
        return 1

    registry = ModelRegistry(
        settings.weights_dir, max_loaded=1, device=settings.device, half=settings.half
    )
    engine = UltralyticsEngine(registry)
    session = _session(weights)
    model_id = args.model or settings.default_model_id

    report: dict[str, Any] = {
        "context": {
            "model": model_id,
            "encoder": weights.name,
            "netSize": NET_SIZE,
            "frames": args.frames,
            "viewsPerTrack": VIEWS_PER_TRACK,
            "minViewGapFrames": MIN_VIEW_GAP_FRAMES,
        },
        "sources": [],
    }

    for video in videos:
        spec = EngineSpec(
            model_id=model_id,
            confidence=args.confidence,
            iou=settings.iou_threshold if hasattr(settings, "iou_threshold") else 0.45,
            class_ids=(2, 3, 5, 7),
            start_ms=args.start * 1000.0,
        )
        print(f"\n  {video.parent.name if video.name == 'input.mp4' else video.name}")
        views = _collect(engine, video, spec, args.frames)
        tracks = len({view.track_id for view in views})
        print(f"    {len(views)} vues, {tracks} pistes")
        if tracks < MIN_TRACKS:
            print(f"    trop peu de pistes (< {MIN_TRACKS}) — mesure non concluante")
            continue

        source: dict[str, Any] = {"name": video.parent.name, "views": len(views), "tracks": tracks}

        variants = (
            ("imagenet-rgb", "imagenet-bgr", "plain-rgb", "plain-bgr")
            if args.variants
            else ("imagenet-rgb",)
        )
        print("\n    Prétraitement")
        source["variants"] = {}
        for variant in variants:
            result = _score(_embed(session, views, variant=variant), views)
            source["variants"][variant] = result
            _print(variant, result)

        if args.truth_ladder:
            anchor = max(LADDER_WIDTHS)
            pool = _ladder_pool(views, anchor)
            pool_tracks = len({view.track_id for view in pool})
            print()
            print(
                f"    Échelle de vérité terrain — vivier commun : "
                f"{len(pool)} vues / {pool_tracks} pistes nativement ≥ {anchor} px"
            )
            source["ladder"] = {"anchor": anchor, "poolViews": len(pool)}
            if pool_tracks < MIN_TRACKS:
                print(
                    f"      vivier trop petit (< {MIN_TRACKS} pistes) — augmentez "
                    "--frames, ou filmez plus serré : sur cette scène les véhicules "
                    "n'atteignent pas l'entrée du réseau."
                )
            else:
                for width in LADDER_WIDTHS:
                    scaled = _at_width(pool, width)
                    result = _score(_embed(session, scaled, variant="imagenet-rgb"), scaled)
                    source["ladder"][str(width)] = result
                    _print(f"{width} px", result)

        report["sources"].append(source)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n  Rapport écrit : {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
