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
    PreviewSample,
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
    from traffic_analysis.features.counting.domain.models import CrossingEvent, ZoneEntryEvent

logger = get_logger("traffic_analysis.analysis")

# La progression est publiée toutes les N images analysées. Plus souvent, on noie
# le flux SSE ; moins souvent, la barre paraît figée.
PROGRESS_EVERY_FRAMES = 10

#: Intervalle minimal entre deux aperçus, en secondes.
#:
#: Échantillonné en **temps**, et non en nombre d'images, contrairement à la
#: progression. La raison est que la cadence d'analyse varie d'un facteur dix
#: entre un CPU et un GPU : « une image sur dix » donnerait un aperçu toutes les
#: cinq secondes sur cette machine et cinquante par seconde sur une autre. Ce
#: qu'on veut borner est le débit du flux et le travail du navigateur, qui se
#: mesurent en secondes.
PREVIEW_MIN_INTERVAL_S = 0.2

type ProgressCallback = Callable[[Progress], None]
type PreviewCallback = Callable[[PreviewSample], None]
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
        on_preview: PreviewCallback | None = None,
        preview_interval_s: float = PREVIEW_MIN_INTERVAL_S,
        is_cancelled: CancellationCheck | None = None,
    ) -> AnalysisResultData:
        """Analyse une vidéo de bout en bout. **Bloquante** : à appeler en thread.

        L'annulation est vérifiée à chaque frame plutôt que par `task.cancel()` :
        on n'interrompt pas un `track()` en cours, on lui demande de s'arrêter
        proprement entre deux images.

        `on_preview` reçoit un échantillon de l'état courant — pistes, événements
        cumulés, statistiques — au plus une fois toutes les `preview_interval_s`.
        C'est ce qui permet de **valider** une analyse pendant qu'elle tourne :
        sans lui, rien de visuel ne quitte le serveur avant la fin. Un intervalle
        nul publie chaque frame, ce dont seuls les tests ont l'usage.
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
        last_preview = started
        # Événements accumulés depuis le dernier aperçu publié : l'aperçu en
        # transporte l'intégralité, sinon le journal affiché perdrait la plupart
        # des franchissements que ses propres compteurs annoncent.
        pending_crossings: list[CrossingEvent] = []
        pending_zone_events: list[ZoneEntryEvent] = []

        for frame in self._engine.iter_video(video_path, config.engine_spec()):
            if is_cancelled is not None and is_cancelled():
                raise AnalysisCancelled

            outcome = session.feed(frame.frame_index, frame.timestamp_ms, frame.image, frame.tracks)

            if detector is not None:
                for track in outcome.tracks:
                    session.record_plates(track, detector.detect(frame.image, track.box))

            # Le snapshot est pris **après** la passe ANPR, sinon les plaques
            # manquent de la timeline et la relecture n'en affiche aucune.
            snapshots = tuple(track.snapshot() for track in outcome.tracks)
            result.timeline.append(
                TimelineRow(
                    frame_index=frame.frame_index,
                    timestamp_ms=frame.timestamp_ms,
                    tracks=snapshots,
                )
            )
            result.crossings.extend(outcome.crossings)
            result.zone_events.extend(outcome.zone_events)
            processed += 1

            if on_progress is not None and processed % PROGRESS_EVERY_FRAMES == 0:
                on_progress(Progress(processed, total, self._fps(processed, started)))

            if on_preview is not None:
                pending_crossings.extend(outcome.crossings)
                pending_zone_events.extend(outcome.zone_events)
                # `perf_counter` est ici une **cadence de publication**, pas un
                # horodatage métier : même statut que la mesure de `_fps`
                # (invariant 1). Les temps portés par l'aperçu, eux, restent du
                # temps de scène.
                now = perf_counter()
                if now - last_preview >= preview_interval_s:
                    last_preview = now
                    # `session.stats()` n'est calculé **que** lorsqu'on publie :
                    # l'appeler à chaque frame pour le jeter aussitôt taxerait
                    # l'analyse au profit de personne.
                    on_preview(
                        PreviewSample(
                            frame_index=frame.frame_index,
                            timestamp_ms=frame.timestamp_ms,
                            frame_width=info.width,
                            frame_height=info.height,
                            tracks=snapshots,
                            crossings=tuple(pending_crossings),
                            zone_events=tuple(pending_zone_events),
                            stats=session.stats(),
                        )
                    )
                    pending_crossings.clear()
                    pending_zone_events.clear()

        elapsed = perf_counter() - started
        result.processing_fps = self._fps(processed, started)
        result.vehicles = session.vehicles()
        result.stats = session.stats()

        if on_progress is not None:
            # Publication finale obligatoire : sans elle, la barre s'arrête au
            # dernier multiple de dix et l'utilisateur croit l'analyse bloquée.
            on_progress(Progress(processed, max(total, processed), result.processing_fps))

        if on_preview is not None and result.timeline:
            # Aperçu final, obligatoire pour la même raison que la progression
            # finale : sans lui, la dernière image affichée est celle d'un
            # échantillon quelconque, et ses compteurs ne correspondent pas à
            # ceux du résultat — l'écart se lit comme un bug de comptage.
            last = result.timeline[-1]
            on_preview(
                PreviewSample(
                    frame_index=last.frame_index,
                    timestamp_ms=last.timestamp_ms,
                    frame_width=info.width,
                    frame_height=info.height,
                    tracks=last.tracks,
                    crossings=tuple(pending_crossings),
                    zone_events=tuple(pending_zone_events),
                    stats=result.stats,
                )
            )

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
