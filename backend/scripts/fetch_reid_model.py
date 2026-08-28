"""Récupération de l'encodeur de ressemblance de véhicule, empreinte vérifiée.

    TRAFFIC_REID_MODEL_URL=https://… \
    TRAFFIC_REID_MODEL_SHA256=abc… \
    uv run python scripts/fetch_reid_model.py

Un script séparé et non un téléchargement au démarrage, pour la même raison que les
deux étages de plaques : **le démarrage du service ne doit jamais dépendre du
réseau**. Son absence rend simplement la recherche par image indisponible, ce que
`/health` annonce et ce que l'interface désactive.

C'est aussi, très directement, la leçon d'ADR 0047 : un poids qu'une bibliothèque
va chercher toute seule au premier appel se télécharge dans le répertoire courant,
en silence, et personne ne s'en aperçoit avant de trouver deux copies de 5,8 Mo à la
racine du dépôt.

La somme SHA-256 est **obligatoire**. Un poids de modèle est du code exécuté par le
service : le télécharger sans vérifier son empreinte reviendrait à exécuter ce que
renvoie une URL, quoi que ce soit.

Le **suffixe** est vérifié pour une raison distincte de l'empreinte : l'adaptateur
charge par `onnxruntime`, qui ne lit que de l'ONNX. Un `.pt` téléchargé vers
`vehicle-reid.onnx` passerait l'empreinte, existerait sur le disque, rendrait
`reidAvailable: true` — et échouerait au chargement. Même piège qu'ADR 0015, à
l'envers.

Le modèle attendu est `vehicle-reid-0001` de l'Open Model Zoo — OSNet-AIN entraîné
sur VeRi-776, entrée `1×3×208×208` en **RGB**, sortie `1×512` comparée par distance
cosinus, 2,18 MParams, licence MIT. Rank-1 96,31 % / mAP 85,15 %. Voir `.env.example`
pour l'URL et l'empreinte, et ADR 0048 pour le choix.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings

CHUNK = 1024 * 1024

#: Le seul format que l'adaptateur sait charger. Pas de `.pt` ici, contrairement au
#: détecteur de plaques : il n'y a pas de chemin Ultralytics pour ce modèle.
KNOWN_SUFFIXES = frozenset({".onnx"})


def _download(url: str, destination: Path) -> str:
    """Télécharge par morceaux et rend l'empreinte SHA-256 du contenu écrit.

    Volontairement dupliqué depuis `fetch_plate_model.py`, comme
    `fetch_plate_ocr_model.py` le fait déjà et le documente : ces scripts sont des
    outils autonomes, et les factoriser créerait un module partagé dont la seule
    raison d'être serait d'économiser quinze lignes. Ne pas « corriger » ceci.
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


def suffix_mismatch(url: str, destination: Path) -> str | None:
    """Décrit le désaccord de format entre l'URL et la destination, ou `None`.

    Le suffixe de l'URL est lu **sans sa requête** : un lien de CDN se termine
    couramment par `?download=true`, ce qu'un `Path(url).suffix` naïf prendrait pour
    l'extension.
    """
    url_suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    target_suffix = destination.suffix.lower()
    if url_suffix not in KNOWN_SUFFIXES:
        # Silence plutôt qu'un refus : une URL peut légitimement ne rien annoncer
        # (redirection, lien signé). L'auto-test du démarrage reste le filet.
        return None
    if url_suffix == target_suffix:
        return None
    return (
        f"L'URL annonce un fichier « {url_suffix} » et la destination est "
        f"« {target_suffix} » :\n"
        f"  URL         : {url}\n"
        f"  destination : {destination}\n"
        "L'adaptateur charge par `onnxruntime`, qui ne lit que de l'ONNX.\n"
        f"Un « {url_suffix} » nommé « {target_suffix} » se téléchargerait sans erreur, "
        "existerait sur le disque,\n"
        "rendrait `reidAvailable: true` — puis échouerait au chargement.\n"
        f"Posez TRAFFIC_REID_MODEL_PATH=./.weights/vehicle-reid{url_suffix} "
        "et relancez.\n"
    )


def main() -> int:
    settings = Settings()
    url = settings.reid_model_url
    expected = (settings.reid_model_sha256 or "").lower().strip()
    destination = settings.resolved_reid_model_path

    if not url:
        sys.stdout.write(
            "TRAFFIC_REID_MODEL_URL n'est pas renseignée.\n"
            "Indiquez l'URL de l'encodeur de ressemblance et sa somme SHA-256 dans "
            ".env, puis relancez ce script.\n"
            "Les valeurs de référence sont commentées dans .env.example.\n"
        )
        return 1
    if not expected:
        sys.stdout.write(
            "TRAFFIC_REID_MODEL_SHA256 n'est pas renseignée.\n"
            "Un poids de modèle est du code exécuté par le service : "
            "il n'est pas téléchargé sans empreinte à vérifier.\n"
        )
        return 1

    # Avant le téléchargement, et non après : un refus qui a déjà écrit le fichier
    # laisse derrière lui exactement le piège qu'il prétend éviter.
    mismatch = suffix_mismatch(url, destination)
    if mismatch is not None:
        sys.stdout.write(f"ÉCHEC : format incohérent.\n{mismatch}")
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
    sys.stdout.write(f"Encodeur de ressemblance installé : {destination} ({size_mb:.1f} Mo)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
