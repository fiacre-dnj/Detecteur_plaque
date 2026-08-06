"""Résidence mémoire des modèles : bail, éviction LRU, préchauffage.

Responsabilités, et **rien d'autre** : cataloguer, charger paresseusement,
prêter, évincer, préchauffer, dire le device.

Deux règles y sont vitales :

- **Un bail par usage.** Deux `track()` simultanés sur la même instance
  partagent l'état de suivi et **mélangent deux vidéos** — des chiffres
  plausibles et complètement faux, que rien ne signale (piège 28 de prompt/13).
- **Un plafond de résidence.** Un modèle résident coûte des centaines de
  mégaoctets ; dix modèles résidents épuisent la mémoire. C'est la leçon du
  benchmark de la version précédente.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from traffic_analysis.core.errors import UnavailableError, UnknownModelError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.models_registry.domain.catalogue import (
    CATALOGUE,
    ModelDescriptor,
    find,
    known_ids,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = get_logger("traffic_analysis.models")

WARMUP_SIDE = 640


@dataclass(slots=True)
class _Resident:
    """Une instance chargée en mémoire, et le verrou qui en sérialise l'usage."""

    model: Any
    # Une instance occupée n'est **jamais** évincée : son bail est en cours
    # d'usage, et la retirer laisserait une analyse sans modèle en plein vol.
    busy: bool = False
    leases: int = field(default=0)
    #: **Le verrou d'exclusion mutuelle de l'invariant 9.**
    #:
    #: Sans lui, `leases` était un simple compteur d'usages concurrents : deux
    #: appelants recevaient la *même* instance et appelaient `model.track(...,
    #: persist=True)` en parallèle depuis deux threads. Le tracker BoT-SORT garde
    #: son état d'une frame à l'autre — les deux flux se mélangeaient, et le
    #: résultat était plausible et complètement faux. Aucune erreur, aucun journal.
    #:
    #: Le cas concret n'était pas théorique : `max_concurrent_jobs` borne les jobs
    #: entre eux et `max_realtime_sessions` les sessions entre elles, mais **rien**
    #: ne bornait un job et une session ensemble — et le conteneur les construit
    #: sur le même registre.
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelRegistry:
    """Prête des instances de modèle, une à la fois, sous plafond mémoire."""

    __slots__ = (
        "_configured_device",
        "_configured_half",
        "_device",
        "_half",
        "_lock",
        "_max_loaded",
        "_residents",
        "_weights_dir",
    )

    def __init__(self, weights_dir: Path, *, max_loaded: int, device: str, half: bool) -> None:
        self._weights_dir = weights_dir
        self._max_loaded = max_loaded
        self._configured_device = device
        self._configured_half = half
        # `OrderedDict` : l'ordre d'insertion **est** l'ordre d'usage, donc le
        # candidat à l'éviction est simplement le premier.
        self._residents: OrderedDict[str, _Resident] = OrderedDict()
        # Le registre est appelé depuis des threads workers : l'état de résidence
        # doit être protégé. Le verrou n'est **jamais** tenu pendant un
        # chargement, qui peut durer le temps d'un téléchargement de 137 Mo.
        self._lock = threading.Lock()
        self._device: str | None = None
        self._half: bool | None = None

    # ── Catalogue ────────────────────────────────────────────────────────────

    def catalogue(self) -> tuple[ModelDescriptor, ...]:
        return CATALOGUE

    def describe(self, model_id: str) -> ModelDescriptor:
        descriptor = find(model_id)
        if descriptor is None:
            raise UnknownModelError(
                f"Le modèle « {model_id} » n'existe pas au catalogue. "
                f"Modèles valides : {', '.join(known_ids())}."
            )
        return descriptor

    def weights_path(self, model_id: str) -> Path:
        return self._weights_dir / self.describe(model_id).weights

    def is_downloaded(self, model_id: str) -> bool:
        return self.weights_path(model_id).is_file()

    def size_bytes(self, model_id: str) -> int | None:
        """Taille réelle sur disque, ou `None` si le poids n'est pas là.

        Réelle et non celle du catalogue : cette dernière est indicative et sert
        seulement à annoncer un téléchargement avant qu'il ait lieu.
        """
        path = self.weights_path(model_id)
        return path.stat().st_size if path.is_file() else None

    # ── Matériel ─────────────────────────────────────────────────────────────

    def device(self) -> str:
        """Device effectif, résolu **une seule fois** puis mémorisé.

        `torch` est importé localement : les tests du domaine ne doivent jamais
        payer un import de deux secondes pour une valeur qu'ils n'utilisent pas.
        """
        if self._device is not None:
            return self._device

        if self._configured_device != "auto":
            self._device = self._configured_device
            return self._device

        try:
            import torch

            self._device = "0" if torch.cuda.is_available() else "cpu"
        except Exception:
            logger.warning("torch indisponible — bascule sur CPU")
            self._device = "cpu"
        return self._device

    def half(self) -> bool:
        """fp16 **seulement sur GPU**.

        Sur CPU, `half=True` ne va pas plus vite : il ralentit, parce que les
        noyaux fp16 n'y sont pas optimisés (piège 30 de prompt/13).
        """
        if self._half is None:
            self._half = self._configured_half and self.device() != "cpu"
        return self._half

    def loaded_ids(self) -> list[str]:
        with self._lock:
            return list(self._residents)

    def ultralytics_version(self) -> str:
        """Version d'Ultralytics, ou « indisponible ».

        Une chaîne et jamais une exception : cette valeur est affichée dans le
        badge d'état du frontend, et un badge ne doit pas faire tomber une page.
        """
        try:
            import ultralytics
        except Exception:
            return "indisponible"
        return str(getattr(ultralytics, "__version__", "inconnue"))

    # ── Bail ─────────────────────────────────────────────────────────────────

    @contextmanager
    def lease(self, model_id: str) -> Iterator[Any]:
        """Réserve une instance **en exclusivité** pour la durée de l'usage.

        Deux garanties, et il a fallu les deux :

        1. l'instance est marquée occupée, donc à l'abri de l'éviction — la
           retirer laisserait une analyse sans modèle en plein vol ;
        2. **un seul appelant à la fois** l'utilise réellement. Un second bail sur
           le même modèle *attend* que le premier soit rendu.

        La seconde manquait, et c'est l'invariant 9 du projet. `leases` ne comptait
        que les usages concurrents sans jamais les empêcher : deux appelants
        recevaient la même instance et lançaient `model.track(..., persist=True)`
        en parallèle. Le tracker garde son état d'une frame à l'autre, donc les
        deux flux se mélangeaient — des chiffres plausibles et complètement faux,
        sans la moindre erreur.

        **Le bail attend plutôt que de refuser.** Un refus obligerait chaque
        appelant à gérer une indisponibilité transitoire, alors que le travail est
        déjà mis en file en amont (`max_concurrent_jobs`, `max_realtime_sessions`).
        Attendre est ici le comportement correct : l'analyse suivante démarre dès
        que la précédente rend la main.

        L'attente a lieu **hors** du verrou du registre : le tenir pendant une
        analyse de plusieurs minutes bloquerait jusqu'à la lecture du catalogue.
        """
        self.describe(model_id)  # 404 explicite avant tout chargement
        resident = self._acquire(model_id)
        # Sérialise l'usage réel. Acquis après `_acquire`, donc l'instance est déjà
        # comptée occupée et ne peut pas être évincée pendant qu'on attend son tour.
        with resident.lock:
            try:
                yield resident.model
            finally:
                with self._lock:
                    current = self._residents.get(model_id)
                    if current is not None:
                        current.leases = max(0, current.leases - 1)
                        current.busy = current.leases > 0

    def _acquire(self, model_id: str) -> _Resident:
        """Réserve l'instance et rend le **résident**, verrou compris.

        Le résident et non le modèle nu : l'appelant a besoin du verrou pour
        sérialiser l'usage, et le lui faire rechercher séparément rouvrirait une
        course entre l'obtention de l'instance et celle de son verrou.
        """
        with self._lock:
            resident = self._residents.get(model_id)
            if resident is not None:
                self._residents.move_to_end(model_id)
                resident.leases += 1
                resident.busy = True
                return resident

        # Chargement **hors verrou** : il peut durer le temps d'un téléchargement
        # de 137 Mo, et tenir le verrou bloquerait toute autre analyse.
        model = self._load(model_id)

        with self._lock:
            existing = self._residents.get(model_id)
            if existing is not None:
                # Une autre course a chargé le même modèle pendant ce temps :
                # on garde la sienne et on abandonne la nôtre au GC.
                self._residents.move_to_end(model_id)
                existing.leases += 1
                existing.busy = True
                return existing

            fresh = _Resident(model=model, busy=True, leases=1)
            self._residents[model_id] = fresh
            self._evict_if_needed()
            return fresh

    def _evict_if_needed(self) -> None:
        """Évince les plus anciennes instances **non occupées**.

        Appelée sous verrou. Si toutes les instances résidentes sont occupées, on
        dépasse temporairement le plafond plutôt que d'arracher un modèle à une
        analyse en cours — dépasser est récupérable, pas l'autre.
        """
        while len(self._residents) > self._max_loaded:
            victim = next(
                (name for name, resident in self._residents.items() if not resident.busy), None
            )
            if victim is None:
                logger.warning(
                    "plafond de modèles dépassé : toutes les instances sont occupées",
                    loaded=len(self._residents),
                    limit=self._max_loaded,
                )
                return
            del self._residents[victim]
            logger.info("modèle évincé", model_id=victim, limit=self._max_loaded)

    def _load(self, model_id: str) -> Any:  # noqa: ANN401
        descriptor = self.describe(model_id)
        self._weights_dir.mkdir(parents=True, exist_ok=True)
        target = self._weights_dir / descriptor.weights

        try:
            from ultralytics import YOLO  # type: ignore[attr-defined]
        except Exception as exc:
            raise UnavailableError(
                "Ultralytics n'est pas installé sur ce serveur : aucune analyse n'est possible.",
                code="engine_unavailable",
            ) from exc

        logger.info(
            "chargement du modèle",
            model_id=model_id,
            downloaded=target.is_file(),
            device=self.device(),
        )
        try:
            # Chemin absolu quand le poids est déjà là : sinon Ultralytics croit
            # à un identifiant et retélécharge.
            model = YOLO(str(target) if target.is_file() else descriptor.weights)
        except Exception as exc:
            raise UnavailableError(
                f"Le modèle « {model_id} » n'a pas pu être chargé "
                f"(téléchargement impossible ou poids corrompu).",
                code="model_unavailable",
            ) from exc

        self._tidy_downloaded_weights(descriptor, target)
        return model

    def _tidy_downloaded_weights(self, descriptor: ModelDescriptor, target: Path) -> None:
        """Range le poids qu'Ultralytics a déposé dans le répertoire courant.

        Ultralytics télécharge dans le CWD quand le fichier n'existe pas au chemin
        demandé. Sans ce déplacement, chaque démarrage retéléchargerait le même
        modèle, et le répertoire de travail se remplirait de `.pt`.
        """
        if target.is_file():
            return
        stray = Path.cwd() / descriptor.weights
        if stray.is_file():
            stray.replace(target)
            logger.info("poids rangé", model_id=descriptor.id, path=str(target))

    # ── Préchauffage et déchargement ─────────────────────────────────────────

    def warmup(self, model_id: str) -> None:
        """Une inférence à vide, pour que la première requête réelle ne paie pas.

        Le premier appel d'un modèle inclut son chargement **et** sa fusion de
        couches : sans préchauffage, il se lit comme un blocage de plusieurs
        dizaines de secondes (piège 31 de prompt/13).

        Un échec est **journalisé, pas fatal** : mieux vaut un service qui démarre
        et qui sera lent une fois qu'un service qui refuse de démarrer.
        """
        try:
            import numpy as np

            blank = np.zeros((WARMUP_SIDE, WARMUP_SIDE, 3), dtype=np.uint8)
            with self.lease(model_id) as model:
                model.predict(blank, verbose=False, device=self.device(), half=self.half())
            logger.info("modèle préchauffé", model_id=model_id)
        except Exception as exc:
            logger.warning("préchauffage en échec", model_id=model_id, error=str(exc))

    def unload(self, model_id: str) -> bool:
        """Décharge une instance résidente. Refuse si elle est occupée."""
        with self._lock:
            resident = self._residents.get(model_id)
            if resident is None:
                return False
            if resident.busy:
                logger.info("déchargement refusé : instance occupée", model_id=model_id)
                return False
            del self._residents[model_id]
        logger.info("modèle déchargé", model_id=model_id)
        return True
