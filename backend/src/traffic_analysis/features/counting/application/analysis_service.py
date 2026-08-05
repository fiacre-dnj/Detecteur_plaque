"""Orchestration d'une analyse : le seul module qui connaît l'**ordre** du pipeline.

Le domaine ignore d'où viennent les frames ; le moteur ignore ce qu'on en compte.
C'est ici que les deux se rencontrent, et nulle part ailleurs.

`run_video` est **bloquante et longue** — secondes à minutes. Elle est exécutée
dans un thread worker par le `JobManager` : la boucle asyncio ne fait que du
transport, de l'orchestration et de la base.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import (
    TIMELINE_WARNING_THRESHOLD,
    AnalysisCancelled,
    AnalysisResultData,
    Progress,
    TimelineRow,
)
from traffic_analysis.features.counting.domain.models import VideoInfo
from traffic_analysis.features.counting.domain.tracking_session import AnalysisSession

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import AnalysisJobConfig
    from traffic_analysis.features.counting.application.ports import (
        DetectionTrackingEngine,
        PlateDetector,
    )

logger = get_logger("traffic_analysis.analysis")

# La progression est publiée toutes les N images analysées. Plus souvent, on noie
# le flux SSE ; moins souvent, la barre paraît figée.
PROGRESS_EVERY_FRAMES = 10

type ProgressCallback = Callable[[Progress], None]
type CancellationCheck = Callable[[], bool]


class AnalysisService:
    """Exécute une analyse complète : moteur → session de comptage → résultat."""

    __slots__ = ("_engine", "_plate_detector")

    def __init__(
        self,
        engine: DetectionTrackingEngine,
        plate_detector: PlateDetector | None = None,
    ) -> None:
        self._engine = engine
        self._plate_detector = plate_detector

    def probe(self, video_path: Path) -> VideoInfo:
        """Sonde une vidéo. Sert aussi de validation de format réelle."""
        return self._engine.probe(video_path)

    def run_video(
        self,
        job_id: str,
        video_path: Path,
        config: AnalysisJobConfig,
        *,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancellationCheck | None = None,
    ) -> AnalysisResultData:
        """Analyse une vidéo de bout en bout. **Bloquante** : à appeler en thread.

        L'annulation est vérifiée à chaque frame plutôt que par `task.cancel()` :
        on n'interrompt pas un `track()` en cours, on lui demande de s'arrêter
        proprement entre deux images.
        """
        info = self._engine.probe(video_path)
        session = AnalysisSession(config.session_config(), info.width, info.height)
        result = AnalysisResultData(job_id=job_id, model_id=config.model_id, video=info)

        total = self._expected_frames(info.frame_count, config.frame_stride)
        self._warn_if_timeline_is_huge(job_id, total)

        detector = self._plate_detector if config.detect_plates else None
        if config.detect_plates and (detector is None or not detector.available):
            # Ne pas échouer : l'utilisateur veut avant tout son comptage.
            logger.warning("ANPR demandée mais indisponible", job_id=job_id)
            detector = None

        started = perf_counter()
        processed = 0

        for frame in self._engine.iter_video(video_path, config.engine_spec()):
            if is_cancelled is not None and is_cancelled():
                raise AnalysisCancelled

            outcome = session.feed(frame.frame_index, frame.timestamp_ms, frame.image, frame.tracks)

            if detector is not None:
                for track in outcome.tracks:
                    session.record_plates(track, detector.detect(frame.image, track.box))

            # Le snapshot est pris **après** la passe ANPR, sinon les plaques
            # manquent de la timeline et la relecture n'en affiche aucune.
            result.timeline.append(
                TimelineRow(
                    frame_index=frame.frame_index,
                    timestamp_ms=frame.timestamp_ms,
                    tracks=tuple(track.snapshot() for track in outcome.tracks),
                )
            )
            result.crossings.extend(outcome.crossings)
            result.zone_events.extend(outcome.zone_events)
            processed += 1

            if on_progress is not None and processed % PROGRESS_EVERY_FRAMES == 0:
                on_progress(Progress(processed, total, self._fps(processed, started)))

        elapsed = perf_counter() - started
        result.processing_fps = self._fps(processed, started)
        result.vehicles = session.vehicles()
        result.stats = session.stats()

        if on_progress is not None:
            # Publication finale obligatoire : sans elle, la barre s'arrête au
            # dernier multiple de dix et l'utilisateur croit l'analyse bloquée.
            on_progress(Progress(processed, max(total, processed), result.processing_fps))

        logger.info(
            "analyse terminée",
            job_id=job_id,
            model_id=config.model_id,
            frames=processed,
            duration_s=round(elapsed, 2),
            processing_fps=round(result.processing_fps, 2),
            unique_vehicles=result.stats.unique_vehicles,
            crossings=result.stats.crossings,
        )
        return result

    @staticmethod
    def _expected_frames(frame_count: int, stride: int) -> int:
        """Nombre d'images **analysées**, pas d'images du fichier.

        C'est l'unité de la barre de progression : diviser par `frame_count` avec
        un pas de 3 la ferait plafonner à 33 %.
        """
        if frame_count <= 0:
            return 0
        return max(1, frame_count // max(1, stride))

    @staticmethod
    def _fps(processed: int, started: float) -> float:
        """Cadence de **traitement**, en images par seconde d'horloge murale.

        C'est le seul usage légitime de l'horloge murale dans tout le pipeline :
        une mesure de performance, jamais un horodatage métier.
        """
        elapsed = perf_counter() - started
        return processed / elapsed if elapsed > 0 else 0.0

    @staticmethod
    def _warn_if_timeline_is_huge(job_id: str, total: int) -> None:
        if total > TIMELINE_WARNING_THRESHOLD:
            logger.warning(
                "timeline volumineuse — augmenter le pas d'analyse réduirait la mémoire",
                job_id=job_id,
                expected_frames=total,
                threshold=TIMELINE_WARNING_THRESHOLD,
            )
