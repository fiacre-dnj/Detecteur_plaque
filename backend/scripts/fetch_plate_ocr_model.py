"""Récupération du modèle de **lecture** de plaques et de son dictionnaire.

    TRAFFIC_PLATE_OCR_MODEL_URL=https://… \
    TRAFFIC_PLATE_OCR_MODEL_SHA256=abc… \
    TRAFFIC_PLATE_OCR_CHARSET_URL=https://… \
    TRAFFIC_PLATE_OCR_CHARSET_SHA256=def… \
    uv run python scripts/fetch_plate_ocr_model.py

**Quel modèle.** Une tête de reconnaissance PP-OCR **anglaise** exportée en ONNX, avec
le `en_dict.txt` de PaddleOCR. Valeurs vérifiées de ce lot (voir ADR 0007) :

    modèle       : SWHL/RapidOCR, PP-OCRv3/en_PP-OCRv3_rec_infer.onnx  (97 classes)
    dictionnaire : PaddleOCR, ppocr/utils/en_dict.txt                  (95 lignes)

`en_PP-OCRv4_rec` n'est pas publié en ONNX — le dépôt de RapidOCR n'a d'export anglais
qu'en v3, la v4 n'y existe qu'en chinois. Même famille, même adaptateur.

**Jamais l'export chinois à 6625 classes** : il fonctionnerait, la normalisation du
domaine retirant tout ce qui sort de `A-Z0-9-`, mais il paierait un softmax 68 fois
plus large pour lire sept caractères latins.

**Attention au dictionnaire** : `en_dict.txt` contient une ligne dont le seul contenu
est un **espace**. C'est un caractère de l'alphabet, pas un blanc de mise en forme — le
filtrer décale tout ce qui suit de deux crans. 95 lignes + espace de `use_space_char`
+ blanc CTC = 97 classes.

**Les deux fichiers, ensemble.** Le dictionnaire n'est pas une donnée indépendante du
modèle : il *fait partie de son contrat*, puisque l'indice 37 signifie ce que le
dictionnaire d'entraînement disait. Les récupérer ensemble, hachés tous les deux, les
versionne ensemble. Voir ADR 0007.

Un script séparé et non un téléchargement au démarrage : **le démarrage du service ne
doit jamais dépendre du réseau**. L'absence de ces fichiers rend simplement la lecture
indisponible — ce que `/health` annonce par `plateOcrAvailable` — sans toucher à la
détection de plaques, qui continue de fonctionner.

`_download` est volontairement **dupliqué** depuis `fetch_plate_model.py` et non
factorisé : `scripts/` n'est pas un paquet, un module partagé demanderait un
`per-file-ignores` et des acrobaties de `sys.path` pour vingt lignes, et la règle que
ces deux outils font respecter — somme SHA-256 obligatoire, parce qu'un poids est du
code exécuté par le service — pèse plus lourd que le DRY. Ne pas « corriger » ceci.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traffic_analysis.core.settings import Settings

CHUNK = 1024 * 1024

#: Un alphabet latin de reconnaissance compte quelques dizaines d'entrées. Bien
#: au-delà, c'est presque sûrement le dictionnaire chinois — le seul avertissement
#: qu'un opérateur recevra avant des mois de plaques fausses.
SUSPICIOUS_CHARSET_SIZE = 500


def _download(url: str, destination: Path) -> str:
    """Télécharge par morceaux et rend l'empreinte SHA-256 du contenu écrit."""
    digest = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Fichier temporaire : une interruption réseau ne doit pas laisser un fichier
    # tronqué à l'emplacement final, où il serait pris pour valide.
    staging = destination.with_suffix(destination.suffix + ".part")

    with urllib.request.urlopen(url) as response, staging.open("wb") as output:  # noqa: S310
        while chunk := response.read(CHUNK):
            digest.update(chunk)
            output.write(chunk)

    computed = digest.hexdigest()
    staging.replace(destination)
    return computed


def _fetch(label: str, url: str, expected: str, destination: Path) -> bool:
    """Récupère un artefact et vérifie son empreinte. Rend `False` en cas d'échec."""
    if destination.is_file():
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual == expected:
            sys.stdout.write(f"{label} déjà présent et conforme : {destination}\n")
            return True
        sys.stdout.write(f"{label} présent mais empreinte différente — retéléchargement.\n")

    sys.stdout.write(f"Téléchargement du {label} depuis {url} …\n")
    computed = _download(url, destination)
    if computed != expected:
        destination.unlink(missing_ok=True)
        sys.stdout.write(
            f"ÉCHEC sur le {label} : l'empreinte ne correspond pas.\n"
            f"  attendue : {expected}\n"
            f"  obtenue  : {computed}\n"
            "Le fichier a été supprimé.\n"
        )
        return False
    return True


def _describe_charset(charset_path: Path) -> tuple[int, str]:
    """Nombre d'entrées et aperçu, pour qu'un opérateur reconnaisse son alphabet.

    L'aperçu n'est pas cosmétique : voir « 0…Z » sur 96 entrées ou des idéogrammes sur
    6625 est la façon la plus rapide de constater qu'on a récupéré le mauvais export.
    """
    # Aucune ligne n'est écartée : `en_dict.txt` contient une ligne dont le seul
    # contenu est un **espace**, qui est un caractère de l'alphabet et non un blanc de
    # mise en forme. La filtrer décalerait tout ce qui suit.
    lines = charset_path.read_text(encoding="utf-8").splitlines()
    if len(lines) > 16:
        preview = "".join(lines[:8]) + " … " + "".join(lines[-8:])
    else:
        preview = "".join(lines)
    return len(lines), preview


def _check_consistency(model_path: Path, charset_size: int) -> bool:
    """Le dictionnaire correspond-il à la sortie du modèle ?

    **La meilleure dépense de tout ce script.** C'est le seul moment où l'on peut
    transformer un décodage silencieusement faux en erreur bruyante, à un instant
    choisi par l'opérateur — plutôt qu'en mois de plaques plausibles et fausses.

    Une dimension dynamique n'est pas vérifiable : on le dit et on laisse passer, plutôt
    que de refuser un modèle valide.
    """
    try:
        import onnxruntime as ort
    except ImportError:  # pragma: no cover — onnxruntime est une dépendance dure
        sys.stdout.write("onnxruntime indisponible : contrôle de cohérence ignoré.\n")
        return True

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    classes = session.get_outputs()[0].shape[-1]
    if not isinstance(classes, int):
        sys.stdout.write(
            "La dimension de sortie du modèle est dynamique : cohérence non vérifiable ici.\n"
            f"Le dictionnaire compte {charset_size} entrées — vérifiez qu'elles correspondent.\n"
        )
        return True

    # Même arithmétique que `OnnxPlateReader._resolve_charset` : le blanc CTC est
    # implicite, et l'espace de `use_space_char` est ajouté par PaddleOCR sans figurer
    # dans le fichier. Les deux tailles acceptables sont donc `+1` et `+2`.
    if classes in (charset_size + 1, charset_size + 2):
        space = " + espace de use_space_char" if classes == charset_size + 2 else ""
        sys.stdout.write(
            f"Cohérence vérifiée : {classes} classes = {charset_size} entrées + blanc CTC{space}.\n"
        )
        return True

    sys.stdout.write(
        "ÉCHEC : le dictionnaire ne correspond pas au modèle.\n"
        f"  classes du modèle       : {classes}\n"
        f"  entrées du dictionnaire : {charset_size} (+ blanc CTC, + espace éventuel)\n"
        "Les deux fichiers doivent venir du même export. Un dictionnaire d'une autre "
        "taille ne lève rien à l'exécution : il produit des plaques fausses et "
        "parfaitement plausibles (ADR 0007).\n"
    )
    return False


def main() -> int:
    settings = Settings()
    model_url = settings.plate_ocr_model_url
    model_sha = (settings.plate_ocr_model_sha256 or "").lower().strip()
    charset_url = settings.plate_ocr_charset_url
    charset_sha = (settings.plate_ocr_charset_sha256 or "").lower().strip()

    missing = [
        name
        for name, value in (
            ("TRAFFIC_PLATE_OCR_MODEL_URL", model_url),
            ("TRAFFIC_PLATE_OCR_MODEL_SHA256", model_sha),
            ("TRAFFIC_PLATE_OCR_CHARSET_URL", charset_url),
            ("TRAFFIC_PLATE_OCR_CHARSET_SHA256", charset_sha),
        )
        if not value
    ]
    if missing:
        sys.stdout.write(
            "Réglages manquants : " + ", ".join(missing) + ".\n"
            "Les quatre sont nécessaires : le modèle et son dictionnaire sont "
            "inséparables, et un poids est du code exécuté par le service — il n'est "
            "pas téléchargé sans empreinte à vérifier.\n"
        )
        return 1
    # Les quatre sont non vides : `mypy` a besoin de le lire, pas seulement de le
    # déduire de la liste ci-dessus.
    assert model_url is not None and charset_url is not None  # noqa: S101

    model_path = settings.resolved_plate_ocr_model_path
    charset_path = settings.resolved_plate_ocr_charset_path

    if not _fetch("modèle de lecture", model_url, model_sha, model_path):
        return 1
    if not _fetch("dictionnaire", charset_url, charset_sha, charset_path):
        # Un modèle sans dictionnaire n'est pas un état utile : `available` rendrait
        # faux de toute façon, autant que le disque reflète cela.
        model_path.unlink(missing_ok=True)
        sys.stdout.write("Le modèle a été supprimé lui aussi : les deux vont ensemble.\n")
        return 1

    charset_size, preview = _describe_charset(charset_path)
    if not _check_consistency(model_path, charset_size):
        model_path.unlink(missing_ok=True)
        charset_path.unlink(missing_ok=True)
        return 1

    size_mb = model_path.stat().st_size / 1e6
    sys.stdout.write(
        f"Lecture de plaques installée.\n"
        f"  modèle       : {model_path} ({size_mb:.1f} Mo)\n"
        f"  dictionnaire : {charset_path} ({charset_size} entrées)\n"
        f"  aperçu       : {preview}\n"
    )
    if charset_size > SUSPICIOUS_CHARSET_SIZE:
        sys.stdout.write(
            "ATTENTION : un alphabet de cette taille n'est pas un alphabet latin. "
            "Vérifiez que vous avez bien récupéré `en_PP-OCRv4_rec` et non l'export "
            "chinois — sinon les plaques lues seront fausses sans qu'aucune erreur "
            "ne le signale.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
