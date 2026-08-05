"""Stockage des résultats détaillés en `json.gz` sur disque.

Un résultat de 30 minutes ne reste pas en mémoire après la fin du job : il compte
54 000 lignes de timeline, soit des centaines de milliers d'objets. Il est écrit
compressé et servi en fichier — le client le décompresse, ce que tout navigateur
fait nativement.

La compression n'est pas un détail : sur un résultat réel, le `json.gz` pèse
environ un dixième du JSON brut, parce qu'une timeline est extrêmement répétitive.
"""

from __future__ import annotations

import gzip
import json
import shutil
from typing import TYPE_CHECKING, Any

from traffic_analysis.core.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("traffic_analysis.results")

RESULT_FILENAME = "result.json.gz"
INPUT_STEM = "input"

# Niveau 6 : le défaut de gzip. Monter à 9 double le temps d'écriture d'un gros
# résultat pour quelques pour cent de taille — un mauvais échange quand
# l'utilisateur attend la fin de son analyse.
COMPRESS_LEVEL = 6


class FileResultStore:
    """Un répertoire par job, sous `data/jobs/<id>/`.

    Un répertoire et non un fichier plat : la vidéo déposée et le résultat vivent
    ensemble, et la purge d'un job est un simple `rmtree` — donc atomique du point
    de vue de l'utilisateur, et impossible à laisser à moitié faite.
    """

    __slots__ = ("_root",)

    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "jobs"

    def directory_for(self, job_id: str) -> Path:
        """Répertoire du job, créé si besoin.

        `job_id` est un uuid4 hexadécimal généré par le service, **jamais** une
        entrée utilisateur : aucun chemin de ce module ne vient du client, ce qui
        élimine la traversée de répertoire à la racine plutôt que par filtrage.
        """
        directory = self._root / job_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def input_path(self, job_id: str, suffix: str) -> Path:
        """Chemin de la vidéo déposée.

        Le nom d'origine n'est **jamais** utilisé comme chemin : il est conservé en
        base pour l'affichage, et le fichier s'appelle `input<ext>`. Seule
        l'extension est reprise, et l'appelant l'a validée.
        """
        return self.directory_for(job_id) / f"{INPUT_STEM}{suffix}"

    def write(self, job_id: str, payload: dict[str, Any]) -> Path:
        """Écrit le résultat compressé et rend son chemin."""
        path = self.directory_for(job_id) / RESULT_FILENAME
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=COMPRESS_LEVEL) as stream:
            # `separators` sans espaces : sur une timeline de 54 000 lignes, les
            # espaces d'indentation par défaut de json pèsent plusieurs mégaoctets.
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        logger.info("résultat écrit", job_id=job_id, size_bytes=path.stat().st_size)
        return path

    def path_for(self, job_id: str) -> Path | None:
        """Chemin du résultat s'il existe, `None` sinon.

        `None` plutôt qu'une exception : un fichier disparu — purge, volume
        démonté, disque plein pendant l'écriture — doit produire un message clair
        pour l'utilisateur, pas un 500.
        """
        path = self._root / job_id / RESULT_FILENAME
        return path if path.is_file() else None

    def delete_input(self, job_id: str) -> None:
        """Supprime la vidéo déposée mais garde le résultat.

        La vidéo est la donnée la plus lourde **et la plus sensible** — une scène
        de trafic contient des plaques réelles — et elle n'est plus nécessaire une
        fois le résultat produit. Elle a donc son propre TTL, plus court.
        """
        directory = self._root / job_id
        if not directory.is_dir():
            return
        for candidate in directory.glob(f"{INPUT_STEM}.*"):
            candidate.unlink(missing_ok=True)

    def delete(self, job_id: str) -> None:
        """Supprime tous les artefacts du job. **Idempotent**.

        Un répertoire déjà absent n'est pas une erreur : la purge doit pouvoir
        rejouer sans conséquence, sinon un incident partiel la bloque pour toujours.
        """
        shutil.rmtree(self._root / job_id, ignore_errors=True)
