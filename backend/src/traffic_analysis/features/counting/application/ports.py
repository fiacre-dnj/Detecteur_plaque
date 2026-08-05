"""Ports du comptage : ce dont l'orchestration a besoin, sans savoir qui le fournit.

C'est **la** décision qui rend tout le projet testable. Les tests injectent un
`FakeEngine` et n'ont donc besoin ni de GPU, ni de poids, ni d'ultralytics ; la
CI tourne en moins de cinq minutes sur une machine sans carte graphique.

Des `Protocol` et non des classes de base abstraites : une implémentation n'a
rien à hériter ni à importer pour satisfaire le contrat, et le port peut donc
vivre ici pendant que l'adaptateur vit dans une autre feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt

    from traffic_analysis.features.counting.domain.models import (
        BoundingBox,
        PlateDetection,
        TrackObservation,
        VideoInfo,
    )


@dataclass(frozen=True, slots=True)
class EngineSpec:
    """Ce que l'orchestration demande au moteur pour une course donnée.

    Les seuils viennent de la requête de l'utilisateur, jamais du catalogue :
    c'est ce qui garantit que les chiffres affichés correspondent aux réglages
    visibles à l'écran.
    """

    model_id: str
    confidence: float
    iou: float
    class_ids: tuple[int, ...]
    frame_stride: int = 1


@dataclass(frozen=True, slots=True)
class EngineFrame:
    """Une frame analysée, telle que le moteur la rapporte.

    `timestamp_ms` est du **temps de scène** (`frame_index / fps × 1000`), calculé
    par l'adaptateur. Il n'y a pas d'horloge murale dans ce flux.
    """

    frame_index: int
    timestamp_ms: float
    image: npt.NDArray[np.uint8]
    tracks: tuple[TrackObservation, ...]


@runtime_checkable
class TrackingStream(Protocol):
    """Flux de suivi ouvert, pour le temps réel.

    Un flux et non des images indépendantes : c'est `persist=True` côté
    Ultralytics qui fait qu'une suite de frames partage un état de suivi. Le bail
    du modèle reste ouvert jusqu'à `close()`.
    """

    def track(
        self, image: npt.NDArray[np.uint8], timestamp_ms: float
    ) -> tuple[TrackObservation, ...]:
        """Suit les objets d'une frame et rend les observations."""
        ...

    def close(self) -> None:
        """Ferme le flux et **rend le bail du modèle**.

        Appelée depuis un `finally` : un bail non rendu immobilise une instance de
        modèle jusqu'au redémarrage du service.
        """
        ...


@runtime_checkable
class DetectionTrackingEngine(Protocol):
    """Détection et suivi. Ultralytics aujourd'hui, un autre moteur demain."""

    def probe(self, video_path: Path) -> VideoInfo:
        """Dimensions, cadence et nombre d'images d'une vidéo.

        Sert aussi de **validation de format** : une vidéo qu'on ne peut pas
        sonder n'est pas une vidéo, quoi qu'en dise son `content-type`.
        """
        ...

    def iter_video(self, video_path: Path, spec: EngineSpec) -> Iterator[EngineFrame]:
        """Parcourt la vidéo image par image, sous un **unique bail** de modèle.

        Un bail pour toute l'itération : deux `track()` simultanés sur la même
        instance partagent l'état de suivi et mélangent deux vidéos — des chiffres
        plausibles et complètement faux.
        """
        ...

    def open_stream(self, spec: EngineSpec) -> TrackingStream:
        """Ouvre un flux de suivi persistant pour le temps réel."""
        ...


@runtime_checkable
class PlateDetector(Protocol):
    """Localisation de plaques sur le recadrage d'un véhicule suivi.

    Deux étages, pour une raison mesurée : une plaque fait ~15 px de large sur un
    plan large 1920×1080, et ~240 px une fois recadrée sur son véhicule. Le modèle
    plein cadre ne la voit pas.
    """

    def detect(self, image: npt.NDArray[np.uint8], box: BoundingBox) -> tuple[PlateDetection, ...]:
        """Cherche une plaque dans `box`, en coordonnées de l'image **complète**.

        Ne lève jamais : une passe ANPR ratée rend une liste vide et journalise.
        Un comptage ne doit pas échouer parce qu'une plaque était illisible.
        """
        ...

    @property
    def available(self) -> bool:
        """Le modèle est-il réellement chargeable ?

        Distinct de « l'objet existe » : les poids sont chargés paresseusement, et
        leur absence ne doit pas empêcher le service de démarrer — l'option est
        simplement signalée indisponible dans `/health` et désactivée dans l'UI.
        """
        ...
