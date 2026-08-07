"""Orchestration d'une analyse : le seul module qui connaît l'**ordre** du pipeline.

Le domaine ignore d'où viennent les frames ; le moteur ignore ce qu'on en compte.
C'est ici que les deux se rencontrent, et nulle part ailleurs.

`run_video` est **bloquante et longue** — secondes à minutes. Elle est exécutée
dans un thread worker par le `JobManager` : la boucle asyncio ne fait que du
transport, de l'orchestration et de la base.
"""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import TYPE_CHECKING

from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import (
    TIMELINE_WARNING_THRESHOLD,
    AnalysisCancelled,
    AnalysisResultData,
    PlateDetectOptions,
    PlateDetectPolicy,
    PlateOcrOptions,
    PlateOcrPolicy,
    PreviewSample,
    Progress,
    TimelineRow,
)
from traffic_analysis.features.counting.domain.models import PlateDetection, VideoInfo
from traffic_analysis.features.counting.domain.plate_anchor import PlateAnchor, anchor_from
from traffic_analysis.features.counting.domain.tracking_session import AnalysisSession

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import numpy as np
    import numpy.typing as npt

    from traffic_analysis.features.counting.application.dto import AnalysisJobConfig
    from traffic_analysis.features.counting.application.ports import (
        DetectionTrackingEngine,
        PlateDetector,
        PlateReader,
    )
    from traffic_analysis.features.counting.domain.models import (
        CrossingEvent,
        SessionTrack,
        ZoneEntryEvent,
    )

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
#: Barrière de pause : **bloquante**, appelée entre deux images. Elle rend la main
#: quand l'analyse reprend, ou quand l'annulation est demandée — jamais avant, et
#: rend le temps attendu, en secondes.
#:
#: Ce temps n'est pas une curiosité : il est retranché de la mesure de cadence.
#: Sans cela, une pause déjeuner ferait tomber « images par seconde » à une valeur
#: qui ne décrit plus rien — ni la machine, ni le modèle, ni la vidéo.
type PauseGate = Callable[[], float]


class AnalysisService:
    """Exécute une analyse complète : moteur → session de comptage → résultat."""

    __slots__ = (
        "_engine",
        "_plate_detect",
        "_plate_detector",
        "_plate_ocr",
        "_plate_reader",
    )

    def __init__(
        self,
        engine: DetectionTrackingEngine,
        plate_detector: PlateDetector | None = None,
        plate_reader: PlateReader | None = None,
        plate_ocr: PlateOcrOptions | None = None,
        plate_detect: PlateDetectOptions | None = None,
    ) -> None:
        self._engine = engine
        self._plate_detector = plate_detector
        self._plate_reader = plate_reader
        self._plate_ocr = plate_ocr or PlateOcrOptions()
        # Réglages de déploiement, comme ceux de l'OCR : ils ne voyagent pas par
        # requête, parce qu'ils arbitrent du débit contre de la fraîcheur de
        # rectangle — un choix de machine, pas de scène (ADR 0008 §4).
        self._plate_detect = plate_detect or PlateDetectOptions()

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
        wait_while_paused: PauseGate | None = None,
    ) -> AnalysisResultData:
        """Analyse une vidéo de bout en bout. **Bloquante** : à appeler en thread.

        L'annulation est vérifiée à chaque frame plutôt que par `task.cancel()` :
        on n'interrompt pas un `track()` en cours, on lui demande de s'arrêter
        proprement entre deux images.

        La pause suit exactement la même règle, et pour les mêmes raisons : on
        attend **entre** deux images, jamais au milieu d'un `track()`. Le décodeur
        reste ouvert sur sa position, l'état du suivi reste vivant, et la reprise
        continue la même analyse — c'est ce qui la distingue d'un nouveau job.
        L'ordre est imposé : **annulation d'abord, pause ensuite**, sinon annuler
        un job suspendu ne prendrait effet qu'à sa reprise.

        `on_preview` reçoit un échantillon de l'état courant — pistes, événements
        cumulés, statistiques — au plus une fois toutes les `preview_interval_s`.
        C'est ce qui permet de **valider** une analyse pendant qu'elle tourne :
        sans lui, rien de visuel ne quitte le serveur avant la fin. Un intervalle
        nul publie chaque frame, ce dont seuls les tests ont l'usage.
        """
        info = self._engine.probe(video_path)
        result = AnalysisResultData(job_id=job_id, model_id=config.model_id, video=info)

        total = self._expected_frames(info.frame_count, config.frame_stride)
        self._warn_if_timeline_is_huge(job_id, total)

        detector = self._plate_detector if config.detect_plates else None
        if config.detect_plates and (detector is None or not detector.available):
            # Ne pas échouer : l'utilisateur veut avant tout son comptage.
            logger.warning("ANPR demandée mais indisponible", job_id=job_id)
            detector = None

        # Garde **indépendant** du précédent. L'OCR est une option DE l'option : son
        # absence ne doit jamais désactiver la détection de plaques, sinon un
        # déploiement sans le modèle de lecture perdrait aussi les boîtes qu'il sait
        # produire. Réciproquement, lire sans détecter n'a pas de sens : il n'y aurait
        # aucune boîte à lire.
        wants_text = config.read_plate_text and detector is not None
        reader = self._plate_reader if wants_text else None
        if wants_text and (reader is None or not reader.available):
            logger.warning("lecture de plaque demandée mais indisponible", job_id=job_id)
            reader = None
        # Une politique par course : aucun état d'étranglement partagé entre jobs.
        policy = PlateOcrPolicy(self._plate_ocr) if reader is not None else None
        detect_policy = PlateDetectPolicy(self._plate_detect)

        # La session est construite **après** la résolution de l'OCR, et pas avant :
        # elle a besoin de savoir si la lecture tourne *réellement* — modèle présent
        # compris — pour distinguer « rien n'a été tenté » des quatre autres raisons
        # de non-lecture. La requête seule ne le dit pas.
        session = AnalysisSession(
            replace(
                config.session_config(),
                plate_ocr_enabled=reader is not None,
                plate_ocr_min_width_px=self._plate_ocr.min_width_px,
            ),
            info.width,
            info.height,
        )
        #: Identité → dernière plaque **mesurée**, en repère relatif au véhicule.
        #: Par course, comme les politiques.
        anchors: dict[int, PlateAnchor] = {}

        started = perf_counter()
        processed = 0
        last_preview = started
        # Temps passé en pause, retranché de la mesure de cadence : une analyse
        # suspendue vingt minutes n'a pas ralenti, elle a attendu.
        paused_s = 0.0
        # Événements accumulés depuis le dernier aperçu publié : l'aperçu en
        # transporte l'intégralité, sinon le journal affiché perdrait la plupart
        # des franchissements que ses propres compteurs annoncent.
        pending_crossings: list[CrossingEvent] = []
        pending_zone_events: list[ZoneEntryEvent] = []

        for frame in self._engine.iter_video(video_path, config.engine_spec()):
            if is_cancelled is not None and is_cancelled():
                raise AnalysisCancelled

            if wait_while_paused is not None:
                paused_s += wait_while_paused()
                # Revérifié au réveil : une pause se termine aussi par une
                # annulation, et reprendre l'analyse d'un job annulé écrirait un
                # résultat que plus personne n'attend.
                if is_cancelled is not None and is_cancelled():
                    raise AnalysisCancelled

            outcome = session.feed(frame.frame_index, frame.timestamp_ms, frame.image, frame.tracks)

            if detector is not None and outcome.tracks:
                # `processed` n'est incrémenté que plus bas : il vaut donc ici
                # l'ordinal 0-indexé de l'image **analysée** courante, ce qu'attendent
                # les deux politiques. Un `frame.frame_index` serait faux dès que
                # `frame_stride > 1`.
                self._detect_plates(
                    detector=detector,
                    detect_policy=detect_policy,
                    anchors=anchors,
                    reader=reader,
                    ocr_policy=policy,
                    session=session,
                    image=frame.image,
                    ordinal=processed,
                    tracks=outcome.tracks,
                    confidence=config.plate_confidence,
                )

            # Le snapshot est pris **après** la passe ANPR ET la passe OCR, sinon les
            # plaques manquent de la timeline — ou, plus insidieux, y figurent sans
            # leur texte : la relecture afficherait des boîtes muettes que l'analyse,
            # elle, avait su lire.
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
                on_progress(Progress(processed, total, self._fps(processed, started, paused_s)))

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

        elapsed = perf_counter() - started - paused_s
        result.processing_fps = self._fps(processed, started, paused_s)
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

    def _detect_plates(
        self,
        *,
        detector: PlateDetector,
        detect_policy: PlateDetectPolicy,
        anchors: dict[int, PlateAnchor],
        reader: PlateReader | None,
        ocr_policy: PlateOcrPolicy | None,
        session: AnalysisSession,
        image: npt.NDArray[np.uint8],
        ordinal: int,
        tracks: Sequence[SessionTrack],
        confidence: float | None,
    ) -> None:
        """Détecte, reprojette, lit — dans cet ordre, et pour cette raison.

        **Seules les pistes retenues par la politique partent en inférence.** Les
        autres reçoivent l'ancre de leur dernière détection réelle, reprojetée sur
        leur boîte courante : c'est ce qui supprime le clignotement qui interdisait
        jusqu'ici d'étrangler le détecteur.

        **L'OCR ne tourne que sur les boîtes réellement mesurées.** Une
        extrapolation n'est pas une observation ; la faire voter fabriquerait de la
        confiance à partir de rien, et deux relectures du même clip pourraient
        publier deux plaques (invariant 4).

        Chaque piste reçoit un `record_plates`, y compris celles qui n'ont ni
        détection ni ancre : c'est ce qui garantit qu'aucun snapshot ne porte de
        trou, donc qu'aucun rectangle ne clignote.
        """
        confident = {
            track.global_id: session.plate_text_is_confident(track.global_id) for track in tracks
        }

        wanted = [
            track
            for track in tracks
            if detect_policy.should_detect(
                track.global_id,
                ordinal,
                track.box,
                vote_is_confident=confident[track.global_id],
                has_anchor=track.global_id in anchors,
            )
        ]

        measured: dict[int, tuple[PlateDetection, ...]] = {}
        if wanted:
            # **Un seul appel pour toutes les pistes retenues.** C'est à l'adaptateur
            # de décider comment amortir ses inférences ; il ne peut le faire que
            # s'il les voit d'un coup. Cette couche ne sait pas — et n'a pas à
            # savoir — s'il empaquette ou non.
            batch = detector.detect_many(image, [track.box for track in wanted], confidence)
            for track, plates in zip(wanted, batch, strict=True):
                detect_policy.record(track.global_id, ordinal)
                measured[track.global_id] = tuple(plates)

        for track in tracks:
            fresh = measured.get(track.global_id)
            if fresh is None:
                # Détection sautée : on repose l'estimation, jamais rien.
                session.record_plates(track, self._project_anchor(anchors, detect_policy, track))
                continue

            # Mesure fraîche : elle remplace l'ancre, et **elle seule** peut être lue.
            self._remember_anchor(anchors, track, fresh)
            if reader is not None and ocr_policy is not None and fresh:
                fresh = self._read_plate_text(
                    reader, ocr_policy, session, image, ordinal, track, fresh
                )
            session.record_plates(track, fresh)

    @staticmethod
    def _remember_anchor(
        anchors: dict[int, PlateAnchor],
        track: SessionTrack,
        plates: Sequence[PlateDetection],
    ) -> None:
        """Mémorise la meilleure plaque **mesurée** en repère relatif au véhicule.

        Une détection vide efface l'ancre : le détecteur vient de regarder et n'a
        rien vu, donc continuer à reprojeter une plaque d'il y a trois images
        affirmerait le contraire de ce qu'on vient de mesurer.
        """
        if not plates:
            anchors.pop(track.global_id, None)
            return
        best = max(plates, key=lambda plate: plate.score)
        anchor = anchor_from(track.box, best.box, best.score)
        if anchor is None:
            anchors.pop(track.global_id, None)
        else:
            anchors[track.global_id] = anchor

    @staticmethod
    def _project_anchor(
        anchors: dict[int, PlateAnchor],
        detect_policy: PlateDetectPolicy,
        track: SessionTrack,
    ) -> tuple[PlateDetection, ...]:
        """Reprojette l'ancre d'une piste dont la détection a été sautée.

        Rend un tuple vide au-delà de `max_anchor_age` : une plaque n'est solidaire
        de son véhicule que sur quelques images, et reprojeter au-delà promènerait
        un rectangle qui ne décrit plus rien. Ne rien dessiner est alors plus
        honnête que dessiner faux.
        """
        anchor = anchors.get(track.global_id)
        if anchor is None:
            return ()
        aged = anchor.aged()
        if aged.age > detect_policy.options.max_anchor_age:
            anchors.pop(track.global_id, None)
            return ()
        anchors[track.global_id] = aged
        return (PlateDetection(box=aged.project(track.box), score=aged.score, stale=True),)

    @staticmethod
    def _read_plate_text(
        reader: PlateReader,
        policy: PlateOcrPolicy,
        session: AnalysisSession,
        image: npt.NDArray[np.uint8],
        ordinal: int,
        track: SessionTrack,
        plates: Sequence[PlateDetection],
    ) -> tuple[PlateDetection, ...]:
        """Lit le texte des plaques qui le méritent, en **un seul** appel.

        Les plaques retenues partent en lot : le coût fixe d'une inférence domine sur
        un tenseur de 48×320, donc trois plaques en trois appels le paient trois fois.

        Le texte posé ici est **brut** — c'est `AnalysisSession.record_plates` qui le
        canonicalise. Ce partage est volontaire : cette couche compose deux ports,
        elle n'a pas à connaître la règle de normalisation du domaine.
        """
        confident = session.plate_text_is_confident(track.global_id)
        wanted = [
            (index, plate)
            for index, plate in enumerate(plates)
            if policy.should_read(
                track.global_id,
                ordinal,
                plate.box,
                vote_is_confident=confident,
                # La netteté vient du détecteur, seule couche à avoir les pixels.
                # Elle s'arrête à la politique : la timeline n'en a rien à faire.
                sharpness=plate.sharpness,
            )
        ]
        if not wanted:
            return tuple(plates)

        texts = reader.read(image, [plate.box for _, plate in wanted])
        if len(texts) != len(wanted):
            # Le port promet un élément par boîte. Un lecteur qui ne tient pas sa
            # promesse ne doit pas faire échouer un comptage : on renonce au texte de
            # cette frame et on le dit.
            logger.warning(
                "lecteur de plaque : longueur inattendue",
                expected=len(wanted),
                received=len(texts),
            )
            return tuple(plates)

        updated = list(plates)
        for (index, plate), text in zip(wanted, texts, strict=True):
            # Noté même quand la lecture a échoué : sans cela, une plaque durablement
            # illisible serait relue à chaque frame — le coût qu'on cherche à éviter.
            policy.record(track.global_id, ordinal, plate.box, plate.sharpness)
            if text is not None:
                updated[index] = replace(
                    plate,
                    text=text.text,
                    text_score=text.score,
                    # De passage jusqu'au vote, où `record_plates` les consomme puis
                    # les jette : le consensus par caractère a besoin de savoir quel
                    # caractère hésitait, la timeline non.
                    text_char_scores=text.char_scores,
                )
        return tuple(updated)

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
    def _fps(processed: int, started: float, paused_s: float = 0.0) -> float:
        """Cadence de **traitement**, en images par seconde d'horloge murale.

        C'est le seul usage légitime de l'horloge murale dans tout le pipeline :
        une mesure de performance, jamais un horodatage métier.

        Le temps passé en pause en est retranché. Une analyse suspendue pendant
        une réunion n'a pas ralenti : la cadence doit continuer de décrire la
        machine, le modèle et la vidéo — pas les allées et venues de qui regarde.
        """
        elapsed = perf_counter() - started - paused_s
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
