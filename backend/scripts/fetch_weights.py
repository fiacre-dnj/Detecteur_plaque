"""Pré-téléchargement des poids YOLO, pour travailler hors ligne.

    uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
    uv run python scripts/fetch_weights.py --families yolo11,yolo26 --tiers all
    uv run python scripts/fetch_weights.py --list

Sans ce script, le **premier** benchmark passe son temps à télécharger : vingt
modèles, jusqu'à 137 Mo chacun, au milieu d'une mesure de latence dont les
chiffres n'auraient alors plus aucun sens.

Le script est **idempotent** — un poids déjà présent est sauté — et **échoue
modèle par modèle** : si une famille n'existe pas dans la version d'Ultralytics
installée, sa ligne porte l'erreur et les autres continuent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings
from traffic_analysis.features.models_registry.domain.catalogue import (
    CATALOGUE,
    TIER_ORDER,
    ModelDescriptor,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tiers",
        default="nano",
        help="Paliers séparés par des virgules, ou « all ». Défaut : nano.",
    )
    parser.add_argument(
        "--families",
        default="all",
        help="Familles séparées par des virgules, ou « all ». Défaut : all.",
    )
    parser.add_argument("--list", action="store_true", help="Liste la sélection sans télécharger.")
    return parser.parse_args()


def _selection(tiers: str, families: str) -> list[ModelDescriptor]:
    wanted_tiers = set(TIER_ORDER) if tiers == "all" else {t.strip() for t in tiers.split(",")}
    unknown = wanted_tiers - set(TIER_ORDER)
    if unknown:
        message = (
            f"Paliers inconnus : {', '.join(sorted(unknown))}. Valides : {', '.join(TIER_ORDER)}."
        )
        raise SystemExit(message)

    known_families = {model.family for model in CATALOGUE}
    wanted_families = (
        known_families if families == "all" else {f.strip() for f in families.split(",")}
    )
    unknown_families = wanted_families - known_families
    if unknown_families:
        message = (
            f"Familles inconnues : {', '.join(sorted(unknown_families))}. "
            f"Valides : {', '.join(sorted(known_families))}."
        )
        raise SystemExit(message)

    return [
        model
        for model in CATALOGUE
        if model.tier in wanted_tiers and model.family in wanted_families
    ]


def _download(model: ModelDescriptor, weights_dir: Path) -> tuple[bool, str]:
    """Télécharge un poids et le range. Rend `(succès, message)`."""
    target = weights_dir / model.weights
    if target.is_file():
        return True, f"déjà présent ({target.stat().st_size / 1e6:.0f} Mo)"

    try:
        from ultralytics import YOLO  # type: ignore[attr-defined]

        YOLO(model.weights)
        # Ultralytics dépose dans le répertoire courant quand le fichier n'existe
        # pas au chemin demandé : le déplacer est ce qui évite un nouveau
        # téléchargement au prochain démarrage.
        stray = Path.cwd() / model.weights
        if stray.is_file():
            stray.replace(target)
    except Exception as exc:
        return False, f"échec : {exc}"

    if not target.is_file():
        return False, "échec : le fichier n'a pas été trouvé après téléchargement"
    return True, f"téléchargé ({target.stat().st_size / 1e6:.0f} Mo)"


def main() -> int:
    args = _parse_args()
    models = _selection(args.tiers, args.families)
    if not models:
        sys.stdout.write("Aucun modèle ne correspond à cette sélection.\n")
        return 1

    total_mb = sum(model.size_mb for model in models)
    sys.stdout.write(f"{len(models)} modèle(s) sélectionné(s), ~{total_mb} Mo au total.\n\n")

    if args.list:
        for model in models:
            sys.stdout.write(f"  {model.id:<10} {model.tier:<8} ~{model.size_mb:>4} Mo\n")
        return 0

    weights_dir = Settings().weights_dir
    weights_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for index, model in enumerate(models, start=1):
        sys.stdout.write(f"[{index}/{len(models)}] {model.id} … ")
        sys.stdout.flush()
        ok, message = _download(model, weights_dir)
        sys.stdout.write(f"{message}\n")
        if not ok:
            failures += 1

    sys.stdout.write(f"\nTerminé : {len(models) - failures} réussite(s), {failures} échec(s).\n")
    if failures:
        sys.stdout.write(
            "Un échec par modèle n'empêche pas les autres : les familles récentes "
            "ne sont pas publiées par toutes les versions d'Ultralytics.\n"
        )
    return 1 if failures == len(models) else 0


if __name__ == "__main__":
    raise SystemExit(main())
