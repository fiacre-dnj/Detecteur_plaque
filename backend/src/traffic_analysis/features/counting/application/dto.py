"""Objets de transfert entre l'orchestration et ce qui l'entoure.

Le domaine n'est **jamais** sérialisé directement : un renommage de champ métier
ne doit pas casser le contrat HTTP, et inversement. Ces DTO sont la charnière.

**Ce module est aussi le contrat publié de la feature `counting`.** Une autre
feature — `jobs`, `realtime`, `benchmark` — importe d'ici, et jamais de
`counting/domain/`. C'est pour cela que les quelques types de domaine dont un
appelant a réellement besoin pour *construire* une configuration sont réexportés
plus bas : sans eux, chaque appelant devrait fouiller dans le domaine, et la
frontière ne voudrait plus rien dire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.application.ports import EngineSpec
from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import (
    VEHICLE_CLASS_IDS,
    CountingLineDef,
    TrackObservation,
    VideoInfo,
    ZoneDef,
)
from traffic_analysis.features.counting.domain.reid import ReidOptions
from traffic_analysis.features.counting.domain.tracking_session import SessionConfig

if TYPE_CHECKING:
    from traffic_analysis.features.counting.domain.models import (
        AnalysisStats,
        CrossingEvent,
        SessionTrack,
        VehicleRecord,
        ZoneEntryEvent,
    )

# Réexports : le vocabulaire minimal qu'un appelant doit manipuler pour décrire
# une analyse. Une feature qui a besoin d'autre chose du domaine du comptage a
# besoin d'un nouveau port, pas d'un import direct.
__all__ = [
    "TIMELINE_WARNING_THRESHOLD",
    "AnalysisCancelled",
    "AnalysisJobConfig",
    "AnalysisResultData",
    "CountingLineDef",
    "Point",
    "Progress",
    "TimelineRow",
    "TrackObservation",
    "VideoInfo",
    "ZoneDef",
]

# Au-delà, la timeline devient un objet de plusieurs centaines de mégaoctets.
# On n'interdit pas — l'utilisateur peut avoir de bonnes raisons — mais on
# avertit et on suggère un pas d'analyse supérieur.
TIMELINE_WARNING_THRESHOLD = 200_000


@dataclass(frozen=True, slots=True)
class AnalysisJobConfig:
    """Configuration complète d'une analyse, telle que l'orchestration la reçoit.

    Un seul objet plutôt que douze paramètres : il traverse le service, le
    `JobManager` et le thread worker sans qu'aucun d'eux ait à connaître le détail
    de ce qu'il transporte.
    """

    model_id: str
    confidence_threshold: float = 0.35
    iou_threshold: float = 0.45
    min_hits: int = 2
    mask_outside_zones: bool = False
    frame_stride: int = 1
    detect_plates: bool = False
    plate_confidence: float | None = None
    pixels_per_meter: float | None = None
    reid_min_similarity: float = 0.80
    max_lost_ms: float = 2500.0
    lines: tuple[CountingLineDef, ...] = ()
    zones: tuple[ZoneDef, ...] = ()

    def engine_spec(self) -> EngineSpec:
        """Ce que le moteur doit savoir : les seuils **vivants** de la requête."""
        return EngineSpec(
            model_id=self.model_id,
            confidence=self.confidence_threshold,
            iou=self.iou_threshold,
            class_ids=VEHICLE_CLASS_IDS,
            frame_stride=self.frame_stride,
        )

    def session_config(self) -> SessionConfig:
        """Ce que le domaine doit savoir : la géométrie et les règles de comptage."""
        return SessionConfig(
            lines=self.lines,
            zones=self.zones,
            mask_outside_zones=self.mask_outside_zones,
            min_hits=self.min_hits,
            max_lost_ms=self.max_lost_ms,
            pixels_per_meter=self.pixels_per_meter,
            reid=ReidOptions(min_similarity=self.reid_min_similarity),
        )


@dataclass(frozen=True, slots=True)
class Progress:
    """Avancement d'une analyse, publié vers le SSE.

    `processed` et `total` sont en **images analysées**, pas en images du fichier :
    avec `frame_stride = 3`, diviser par le nombre total d'images ferait plafonner
    la barre à 33 % (piège 22 de prompt/13).
    """

    processed_frames: int
    total_frames: int
    processing_fps: float

    @property
    def ratio(self) -> float:
        """Fraction accomplie, bornée à 1.

        Bornée parce que le nombre d'images annoncé par un conteneur est parfois
        approximatif : une barre à 103 % est un bug visible par tout le monde.
        """
        if self.total_frames <= 0:
            return 0.0
        return min(1.0, self.processed_frames / self.total_frames)


@dataclass(frozen=True, slots=True)
class TimelineRow:
    """Une frame figée de la timeline.

    Les pistes sont des **snapshots**, pris après la passe ANPR. Stocker la
    référence vivante ferait converger toutes les frames vers l'état final.
    """

    frame_index: int
    timestamp_ms: float
    tracks: tuple[SessionTrack, ...]


@dataclass(slots=True)
class AnalysisResultData:
    """Le résultat complet d'une analyse, avant sérialisation.

    Mutable et non gelé : il se remplit au fil de l'analyse. Il ne quitte le
    processus que sérialisé en `json.gz` — une timeline de 30 minutes ne reste pas
    en mémoire après la fin du job.
    """

    job_id: str
    model_id: str
    video: VideoInfo
    processing_fps: float = 0.0
    timeline: list[TimelineRow] = field(default_factory=list)
    crossings: list[CrossingEvent] = field(default_factory=list)
    zone_events: list[ZoneEntryEvent] = field(default_factory=list)
    vehicles: tuple[VehicleRecord, ...] = ()
    stats: AnalysisStats | None = None


class AnalysisCancelled(Exception):
    """Une annulation demandée par l'utilisateur.

    **Ce n'est pas une erreur.** Le `JobManager` la traduit en statut `cancelled`,
    et l'interface n'affiche aucun message rouge : l'utilisateur sait ce qu'il a
    fait, lui dire que « l'analyse a échoué » serait faux.
    """
