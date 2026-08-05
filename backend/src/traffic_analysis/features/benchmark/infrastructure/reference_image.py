"""L'image de référence d'un run : échantillon embarqué, ou frame d'un job.

C'est la règle 1 du protocole, et la plus facile à enfreindre sans le remarquer :
**une image unique pour tous les modèles**. Une scène chargée coûte plus de
post-traitement qu'une route vide ; mesurer deux modèles sur deux images
différentes ferait passer cet écart pour une différence entre les modèles.

L'échantillon embarqué est **synthétisé**, pas committé. Deux raisons :

- aucun binaire dans git, comme pour les poids (ADR 0002) ;
- une image synthétisée par une formule fixe a un `sha256` **stable et
  reproductible** sur toute machine, donc deux runs pris sur l'échantillon sont
  comparables par construction, et le hash le prouve.

Son contenu importe peu pour **la mesure du temps** — un détecteur paie son
inférence sur la taille de l'entrée, pas sur ce qu'il y voit — et c'est ce que
l'échantillon sert à mesurer.

**Limite à connaître, vérifiée sur un vrai YOLOv8n : l'échantillon synthétique
donne zéro détection.** C'est attendu et non un défaut : des blocs contrastés ne
sont pas des véhicules, et aucun motif procédural raisonnable ne le serait. La
conséquence est que la colonne « détections » n'apprend rien sur l'échantillon —
elle ne devient informative qu'avec `imageSource=job`, sur une vraie scène. Les
temps, eux, sont valables dans les deux cas. Ce choix est assumé plutôt que
contourné : embarquer une photo de trafic réelle mettrait des plaques réelles dans
le dépôt, et truquer le compte serait pire que de le laisser à zéro.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from traffic_analysis.core.errors import ConflictError, NotFoundError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.benchmark.application.ports import ReferenceImage

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt

logger = get_logger("traffic_analysis.benchmark")

# Résolution de l'échantillon : celle d'une caméra de trafic courante. Mesurer sur
# 640×640 flatterait tous les modèles d'un facteur trois par rapport à l'usage
# réel, et le tableau servirait alors à choisir un modèle pour une charge qui
# n'existe pas.
SAMPLE_WIDTH = 1280
SAMPLE_HEIGHT = 720

SAMPLE_SOURCE = "échantillon embarqué"
JOB_SOURCE_PREFIX = "frame du job"

# Nom du fichier d'entrée déposé, tel que `FileResultStore` le nomme. Repris ici
# comme motif de recherche : l'extension varie avec le format déposé.
INPUT_GLOB = "input.*"


class VideoFrameProvider:
    """Fournit l'image de référence, depuis l'échantillon ou depuis un job.

    Le répertoire de données lui est passé plutôt que le dépôt de jobs : ce
    fournisseur n'a besoin que d'un chemin, et lui donner accès au dépôt lui
    ouvrirait des lectures qu'il n'a aucune raison de faire.
    """

    __slots__ = ("_jobs_root",)

    def __init__(self, data_dir: Path) -> None:
        self._jobs_root = data_dir / "jobs"

    def sample(self) -> ReferenceImage:
        """L'échantillon embarqué. Toujours disponible, sans réseau ni disque."""
        pixels = _synthetic_scene(SAMPLE_WIDTH, SAMPLE_HEIGHT)
        return ReferenceImage(
            pixels=pixels,
            sha256=_hash_of(pixels),
            width=SAMPLE_WIDTH,
            height=SAMPLE_HEIGHT,
            source=SAMPLE_SOURCE,
        )

    def from_job(self, job_id: str) -> ReferenceImage:
        """Extrait une frame de la vidéo d'un job. Bloquant : lit le disque.

        Refuse explicitement quand la vidéo n'est plus là — elle a son propre TTL,
        plus court que celui du job (`input_ttl_minutes`), donc l'absence est le
        cas **normal** sur un job d'hier. Retomber en silence sur l'échantillon
        serait pire qu'un refus : l'utilisateur croirait mesurer sur sa scène.
        """
        video_path = self._input_path(job_id)
        pixels = _read_middle_frame(video_path)
        height, width = pixels.shape[0], pixels.shape[1]
        return ReferenceImage(
            pixels=pixels,
            sha256=_hash_of(pixels),
            width=int(width),
            height=int(height),
            source=f"{JOB_SOURCE_PREFIX} {job_id}",
        )

    def _input_path(self, job_id: str) -> Path:
        directory = self._jobs_root / job_id
        if not directory.is_dir():
            raise NotFoundError(
                f"Le job « {job_id} » n'existe pas ou ses fichiers ont été purgés.",
                code="benchmark_job_not_found",
            )
        candidates = sorted(directory.glob(INPUT_GLOB))
        if not candidates:
            raise ConflictError(
                "La vidéo de ce job a été supprimée (sa durée de conservation est "
                "plus courte que celle du job). Lancez le benchmark sur "
                "l'échantillon embarqué, ou déposez une nouvelle vidéo.",
                code="benchmark_input_purged",
            )
        return candidates[0]


def _read_middle_frame(video_path: Path) -> npt.NDArray[np.uint8]:
    """Lit **une** frame au milieu de la vidéo.

    Au milieu et non la première : la première image d'un enregistrement est
    souvent une mire, un fondu au noir ou une frame de calibration — donc vide de
    véhicules, ce qui rendrait la colonne « détections » uniformément nulle.

    Le repli sur la première frame n'est pas un luxe : `CAP_PROP_POS_FRAMES` est
    inopérant sur certains conteneurs (flux sans index de recherche), et il vaut
    mieux une image du début qu'un refus.
    """
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise ConflictError(
                "La vidéo de ce job n'a pas pu être ouverte pour en extraire une image.",
                code="benchmark_video_unreadable",
            )
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if total > 1:
            capture.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
        ok, frame = capture.read()
        if not ok or frame is None:
            # La recherche a échoué : on repart du début plutôt que de refuser.
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = capture.read()
        if not ok or frame is None:
            raise ConflictError(
                "Aucune image n'a pu être lue dans la vidéo de ce job.",
                code="benchmark_video_unreadable",
            )
    finally:
        capture.release()

    # `frame` est déjà un tableau BGR uint8 : c'est exactement ce qu'attend
    # `predict`, et le convertir en RGB ici décalerait les scores par rapport à
    # ceux d'une analyse réelle. Le `asarray` ne copie rien ici ; il affirme le
    # dtype, que les stubs d'OpenCV ne garantissent pas.
    import numpy as np

    return np.asarray(frame, dtype=np.uint8)


def _synthetic_scene(width: int, height: int) -> npt.NDArray[np.uint8]:
    """Construit une scène synthétique déterministe.

    Déterministe **sans générateur pseudo-aléatoire** : la formule ne dépend que
    des indices, donc le `sha256` est identique sur toute machine et pour toujours.
    Un `np.random` même graine dépendrait de la version de numpy, et le hash
    changerait un jour sans que personne comprenne pourquoi deux runs ne sont plus
    comparables.
    """
    import numpy as np

    rows = np.arange(height, dtype=np.int32)[:, None]
    cols = np.arange(width, dtype=np.int32)[None, :]

    image = np.zeros((height, width, 3), dtype=np.uint8)
    # Dégradé vertical : un fond de type chaussée, plus clair vers l'horizon.
    image[:, :, 0] = (60 + rows * 60 // max(1, height)).astype(np.uint8)
    image[:, :, 1] = (62 + rows * 58 // max(1, height)).astype(np.uint8)
    image[:, :, 2] = (66 + rows * 54 // max(1, height)).astype(np.uint8)

    # Marquage central discontinu, puis des blocs contrastés de la taille d'un
    # véhicule : de quoi donner au détecteur des contours à traiter.
    band = (rows > height * 0.55) & (((cols // 60) % 2) == 0)
    image[np.broadcast_to(band, (height, width))] = 210

    for index in range(6):
        left = 120 + index * 180
        top = int(height * 0.45) + (index % 3) * 60
        image[top : top + 90, left : left + 150] = (
            40 + index * 30,
            120 - index * 12,
            200 - index * 25,
        )
    return image


def _hash_of(pixels: npt.NDArray[np.uint8]) -> str:
    """`sha256` du contenu brut de l'image.

    Sur les octets du tableau et non sur un encodage JPEG : un encodeur peut
    changer de version et produire un flux différent pour les mêmes pixels, ce qui
    ferait diverger le hash sans que l'image ait bougé.
    """
    return hashlib.sha256(pixels.tobytes()).hexdigest()
