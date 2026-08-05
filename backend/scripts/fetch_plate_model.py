"""Récupération du modèle de plaques, avec vérification de somme SHA-256.

    TRAFFIC_PLATE_MODEL_URL=https://… \
    TRAFFIC_PLATE_MODEL_SHA256=abc… \
    uv run python scripts/fetch_plate_model.py

Un script séparé et non un téléchargement au démarrage : **le démarrage du
service ne doit jamais dépendre du réseau**. Son absence rend simplement l'option
ANPR indisponible, ce que `/health` annonce et ce que l'interface désactive.

La somme SHA-256 est **obligatoire**. Un poids de modèle est du code exécuté par
le service : le télécharger sans vérifier son empreinte reviendrait à exécuter ce
que renvoie une URL, quoi que ce soit.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings

CHUNK = 1024 * 1024


def _download(url: str, destination: Path) -> str:
    """Télécharge par morceaux et rend l'empreinte SHA-256 du contenu écrit.

    Par morceaux : un poids peut peser des dizaines de mégaoctets, et le charger
    entièrement en mémoire pour le hacher serait inutile.
    """
    digest = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Fichier temporaire : une interruption réseau ne doit pas laisser un poids
    # tronqué à l'emplacement final, où il serait pris pour valide.
    staging = destination.with_suffix(destination.suffix + ".part")

    with urllib.request.urlopen(url) as response, staging.open("wb") as output:  # noqa: S310
        while chunk := response.read(CHUNK):
            digest.update(chunk)
            output.write(chunk)

    computed = digest.hexdigest()
    staging.replace(destination)
    return computed


def main() -> int:
    settings = Settings()
    url = settings.plate_model_url
    expected = (settings.plate_model_sha256 or "").lower().strip()
    destination = settings.resolved_plate_model_path

    if not url:
        sys.stdout.write(
            "TRAFFIC_PLATE_MODEL_URL n'est pas renseignée.\n"
            "Indiquez l'URL du modèle de plaques et sa somme SHA-256 dans .env, "
            "puis relancez ce script.\n"
        )
        return 1
    if not expected:
        sys.stdout.write(
            "TRAFFIC_PLATE_MODEL_SHA256 n'est pas renseignée.\n"
            "Un poids de modèle est du code exécuté par le service : "
            "il n'est pas téléchargé sans empreinte à vérifier.\n"
        )
        return 1

    if destination.is_file():
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual == expected:
            sys.stdout.write(f"Déjà présent et conforme : {destination}\n")
            return 0
        sys.stdout.write("Fichier présent mais empreinte différente — retéléchargement.\n")

    sys.stdout.write(f"Téléchargement depuis {url} …\n")
    computed = _download(url, destination)

    if computed != expected:
        destination.unlink(missing_ok=True)
        sys.stdout.write(
            "ÉCHEC : l'empreinte ne correspond pas.\n"
            f"  attendue : {expected}\n"
            f"  obtenue  : {computed}\n"
            "Le fichier a été supprimé.\n"
        )
        return 1

    size_mb = destination.stat().st_size / 1e6
    sys.stdout.write(f"Modèle de plaques installé : {destination} ({size_mb:.1f} Mo)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
