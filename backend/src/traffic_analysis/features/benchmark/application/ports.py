"""Ports du benchmark : mesurer, fournir une image, persister.

Le service de benchmark ne sait ni charger un modèle, ni décoder une vidéo, ni
écrire en base. Il connaît le **protocole de mesure**, et rien d'autre — c'est ce
qui permet de le tester en entier avec trois doublures et sans matériel.

`InferenceProbe` mérite une explication. Le port existant du comptage
(`DetectionTrackingEngine`) ne sait faire que deux choses : parcourir une vidéo, et
ouvrir un flux de suivi. Ni l'un ni l'autre ne convient ici : le benchmark mesure
**une inférence sur une image fixe**, répétée, sans suivi — un tracker introduirait
un état qui rendrait la deuxième mesure incomparable à la première. D'où un port
distinct.

Son adaptateur de production vit dans
`models_registry/infrastructure/inference_probe.py`, et **pas** dans
`benchmark/infrastructure/`. La raison est la règle de dépendance entre features :
seul `models_registry` peut toucher son propre registre. Le port est donc publié
ici, et implémenté là-bas — c'est le sens normal d'une inversion de dépendance, et
`tests/test_architecture.py` la vérifie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.benchmark.domain.records import (
        BenchmarkEntry,
        BenchmarkRun,
    )


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    """Les seuils d'une mesure — ceux de la **requête**, jamais ceux du catalogue.

    C'est la règle 4 du protocole (prompt/04 §6), et elle a une conséquence
    visible : la colonne « détections » du tableau de benchmark doit correspondre à
    ce que l'utilisateur voit à l'écran avec ses réglages courants. Mesurer avec
    d'autres seuils produirait un nombre de détections que rien ne permet de
    rapprocher de son analyse.
    """

    confidence: float
    iou: float
    class_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Une inférence unique et ce qu'elle a coûté.

    `inference_ms` est chronométré autour de l'appel : c'est le seul usage
    légitime de l'horloge murale dans ce projet, parce que c'est une **mesure de
    performance** et non un horodatage métier (invariant 1).

    `preprocess_ms` et `postprocess_ms` sont `None` quand le moteur ne les expose
    pas. `None` et non `0.0` : un zéro se lirait comme « instantané ».
    """

    inference_ms: float
    detections: int
    preprocess_ms: float | None = None
    postprocess_ms: float | None = None


@dataclass(frozen=True, slots=True)
class ReferenceImage:
    """L'image de référence, unique pour tous les modèles d'un run.

    Unique, parce qu'une comparaison sur des images différentes ne compare rien :
    une image chargée en véhicules coûte plus de post-traitement qu'une route
    vide, et l'écart se lirait comme une différence entre les modèles.

    `sha256` est persisté avec le run. C'est ce qui permet, six mois plus tard, de
    savoir si deux runs sont comparables — ou pourquoi ils ne le sont pas.
    """

    pixels: npt.NDArray[np.uint8]
    sha256: str
    width: int
    height: int
    source: str


@runtime_checkable
class InferenceProbe(Protocol):
    """Une inférence chronométrée sur une image fixe, et la résidence mémoire.

    Toutes les méthodes sont **synchrones et bloquantes** : elles touchent PyTorch
    et le disque. Le service les appelle depuis un thread worker (invariant 11).
    """

    def is_loaded(self, model_id: str) -> bool:
        """L'instance est-elle déjà résidente ?

        Interrogé **avant** le chargement : c'est ce qui permet de rapporter
        `load_ms = 0` honnêtement au lieu d'inventer un chargement rapide.
        """
        ...

    def load(self, model_id: str) -> None:
        """Charge l'instance en mémoire, sans mesurer. Lève si c'est impossible."""
        ...

    def infer_once(
        self, model_id: str, image: npt.NDArray[np.uint8], spec: ProbeSpec
    ) -> ProbeResult:
        """Une inférence, chronométrée, **sans suivi**.

        Sans suivi délibérément : un tracker garde un état entre les appels, donc
        la deuxième mesure ne serait pas comparable à la première.
        """
        ...

    def release(self, model_id: str) -> bool:
        """Libère l'instance. Rend `False` si elle est occupée par une analyse.

        Le refus n'est pas un échec : un modèle utilisé par une analyse en cours
        doit rester résident, et la ligne le dit (`released: false`).
        """
        ...

    def device(self) -> str: ...

    def half(self) -> bool: ...

    def ultralytics_version(self) -> str: ...

    def describe(self, model_id: str) -> tuple[str, str]:
        """Libellé et palier d'un modèle. Lève si l'identifiant est inconnu.

        Le palier vient du catalogue et **jamais du nom de fichier** (invariant
        10) : c'est le catalogue qui le porte.
        """
        ...


@runtime_checkable
class ReferenceImageProvider(Protocol):
    """Fournit l'image de référence d'un run."""

    def sample(self) -> ReferenceImage:
        """L'échantillon embarqué. Toujours disponible, sans réseau."""
        ...

    def from_job(self, job_id: str) -> ReferenceImage:
        """Une frame extraite de la vidéo d'un job existant.

        Lève une erreur explicite si la vidéo a été purgée : mesurer sur
        l'échantillon en croyant mesurer sur sa propre scène serait pire qu'un
        refus.
        """
        ...


@runtime_checkable
class BenchmarkRepository(Protocol):
    """Persistance des runs. Un run survit au redémarrage du service."""

    async def add(self, run: BenchmarkRun) -> None: ...

    async def get(self, run_id: str) -> BenchmarkRun | None: ...

    async def latest(self) -> BenchmarkRun | None:
        """Le run le plus récent, pour ne pas ouvrir la page sur un écran vide."""
        ...

    async def list(self, page: PageParams) -> Page[BenchmarkRun]: ...

    async def append_entry(self, run_id: str, entry: BenchmarkEntry) -> None:
        """Ajoute une ligne au fil du run.

        Ligne par ligne et non en bloc à la fin : un benchmark de vingt modèles
        sur CPU dure plusieurs minutes, et un redémarrage en cours de route ne
        doit pas perdre les mesures déjà acquises.
        """
        ...

    async def set_status(self, run_id: str, status: str, *, error: str | None = None) -> None: ...

    async def delete(self, run_id: str) -> None: ...
