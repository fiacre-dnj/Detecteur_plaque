"""Orchestration d'une analyse : le seul module qui connaît l'**ordre** du pipeline.

Le domaine ignore d'où viennent les frames ; le moteur ignore ce qu'on en compte.
C'est ici que les deux se rencontrent, et nulle part ailleurs.

`run_video` est **bloquante et longue** — secondes à minutes. Elle est exécutée
dans un thread worker par le `JobManager` : la boucle asyncio ne fait que du
transport, de l'orchestration et de la base.
"""

from __future__ import annotations

from dataclasses import replace
from math import ceil
from time import perf_counter, sleep
from typing import TYPE_CHECKING

from traffic_analysis.core.errors import ValidationAppError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import (
    TIMELINE_WARNING_THRESHOLD,
    AnalysisCancelled,
    AnalysisResultData,
    DetectionCandidate,
    PlateDetectOptions,
    PlateDetectPolicy,
    PlateOcrOptions,
    PlateOcrPolicy,
    PreviewSample,
    Progress,
    TimelineRow,
    select_within_budget,
)
from traffic_analysis.features.counting.domain.models import PlateDetection, VideoInfo
from traffic_analysis.features.counting.domain.pacing import ScenePacer
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

#: Intervalle d'aperçu quand l'analyse est **bridée**, en secondes.
#:
#: Plus serré que le régime normal, et ce n'est pas un raffinement. Un aperçu
#: toutes les 200 ms sur une analyse bridée à 1× ne montre que cinq images de
#: scène par seconde : la vitesse est juste, mais l'aperçu ressemble à un
#: diaporama. Or brider est précisément la décision de *regarder* l'analyse — donc
#: celle d'accepter deux fois plus de trames sur le flux, qui ne portent que des
#: boîtes et des compteurs, jamais de pixels.
#:
#: N'élargit jamais l'intervalle du déploiement : le minimum des deux est retenu.
PACED_PREVIEW_INTERVAL_S = 0.1

#: Intervalle de republication du **registre** dans l'aperçu, en secondes.
#:
#: Une cadence à part, et bien plus lente que celle des boîtes, parce que les deux
#: charges n'ont rien de comparable. Les pistes d'une image sont une poignée et leur
#: nombre ne dépend pas de la durée de l'analyse ; le registre, lui, **grossit** —
#: 350 octets par véhicule mesurés sur les résultats archivés de ce dépôt, soit
#: 35 ko pour cent véhicules. Le republier dix fois par seconde ferait grimper le
#: flux SSE avec l'avancement de l'analyse, jusqu'à mettre le navigateur à genoux sur
#: une vidéo longue — et pour rien : un tableau de véhicules n'a pas besoin de
#: rafraîchir dix fois par seconde pour se lire comme vivant.
#:
#: `None` désactive la republication : le registre reste alors vide jusqu'à la fin de
#: l'analyse, comme avant qu'elle existe. `0.0`, comme pour l'intervalle d'aperçu,
#: publie à **chaque** aperçu — le seul mode déterministe, donc celui des tests.
#: L'aperçu **final** porte le registre dans tous les cas.
PREVIEW_VEHICLES_INTERVAL_S = 1.0

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
        paced_preview_interval_s: float = PACED_PREVIEW_INTERVAL_S,
        preview_vehicles_interval_s: float | None = PREVIEW_VEHICLES_INTERVAL_S,
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

        L'aperçu porte aussi le **registre** — `PreviewSample.vehicles` —, mais à
        sa propre cadence, `preview_vehicles_interval_s`, bien plus lente : les
        échantillons intermédiaires portent `None`, qui veut dire « inchangé » et
        jamais « aucun véhicule ». Même convention de valeurs que l'intervalle
        d'aperçu — `0.0` publie à chaque aperçu, `None` ne publie jamais. C'est ce
        champ qui permet au registre et à la statistique de se remplir pendant
        l'analyse sans que le flux grossisse avec elle. L'aperçu **final** le porte
        toujours, quel que soit
        l'intervalle : sans lui, la dernière liste affichée serait celle d'un
        échantillon quelconque, et son écart avec le résultat se lirait comme un
        bug de comptage — même raison que la progression finale obligatoire.

        `config.analysis_speed` et `config.max_analysis_fps` **brident** la
        boucle : elle attend entre deux images pour que le temps de scène
        n'avance jamais plus vite que le multiple demandé du temps réel, et que
        le serveur n'analyse jamais plus vite que le plafond absolu — le plus
        restrictif des deux s'applique. C'est ce qui rend l'aperçu regardable, au
        prix d'une analyse qui dure plus longtemps (`domain/pacing.py`). Une
        analyse bridée resserre aussi son intervalle d'aperçu à
        `paced_preview_interval_s`, sans jamais l'élargir.

        **`processing_fps` d'une analyse bridée mesure le bridage, pas la
        machine.** Le temps d'attente n'est pas retranché, contrairement au temps
        de pause : l'attendre est du travail que l'analyse a choisi de faire, et le
        déduire donnerait une progression dont l'échéance annoncée serait fausse
        d'un facteur égal au bridage. Ne comparer que des runs de même cadence —
        le banc, lui, ne bride jamais.
        """
        info = self._engine.probe(video_path)
        result = AnalysisResultData(job_id=job_id, model_id=config.model_id, video=info)

        total = self._expected_frames(info, config.frame_stride, config.start_ms, config.end_ms)
        self._warn_if_timeline_is_huge(job_id, total)
        if config.start_ms > 0.0 or config.end_ms is not None:
            if total == 0:
                # Refusé **avant** d'analyser, et non rendu en compteurs à zéro.
                # C'est le seul contrôle de fenêtre qui ne peut pas vivre dans le
                # schéma de requête : lui ne connaît pas la durée du fichier, qui
                # n'existe qu'une fois la vidéo reçue et sondée. Sans ce refus, une
                # borne posée au-delà de la fin — un preset rejoué sur un clip plus
                # court, une saisie d'un chiffre de trop — produirait un job
                # « terminé » et parfaitement vide, indiscernable d'une panne de
                # détection.
                duration_ms = info.frame_count / info.fps * 1000.0 if info.fps > 0 else 0.0
                msg = (
                    "L'intervalle demandé ne contient aucune image de cette vidéo : "
                    f"elle dure {duration_ms / 1000:.1f} s et l'analyse était bornée "
                    f"à [{config.start_ms / 1000:.1f} s ; "
                    + ("fin]" if config.end_ms is None else f"{config.end_ms / 1000:.1f} s]")
                    + ". Corrigez les bornes, ou analysez toute la vidéo."
                )
                raise ValidationAppError(msg, code="empty_analysis_range")
            logger.info(
                "analyse restreinte à une fenêtre de la vidéo",
                job_id=job_id,
                start_ms=round(config.start_ms),
                end_ms=None if config.end_ms is None else round(config.end_ms),
                expected_frames=total,
            )

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

        # `None` = pleine vitesse, le défaut. Construit ici parce que la cadence de
        # la source ne se connaît qu'après `probe()`.
        pacer = ScenePacer.for_video(
            info.fps, config.frame_stride, config.analysis_speed, config.max_analysis_fps
        )
        if pacer is not None:
            # `> 0` : zéro signifie « ne pas resserrer », pas « publier chaque
            # image ». La seule valeur qui décide de l'existence de l'aperçu reste
            # `preview_interval_s`, et un déploiement qui met ce champ à zéro ne doit
            # pas se retrouver avec vingt-cinq trames par seconde sur le flux.
            if paced_preview_interval_s > 0.0:
                preview_interval_s = min(preview_interval_s, paced_preview_interval_s)
            logger.info(
                "analyse bridée sur le temps de la scène",
                job_id=job_id,
                analysis_speed=config.analysis_speed,
                max_analysis_fps=config.max_analysis_fps,
                video_fps=round(info.fps, 2),
                frame_period_ms=round(pacer.period_s * 1000, 1),
            )
        elif config.analysis_speed is not None:
            # Le seul cas où un bridage relatif est demandé et refusé : une source
            # qui ne dit pas sa cadence. `max_analysis_fps`, lui, ne dépend jamais
            # de `fps` — s'il était seul demandé, `pacer` ne serait pas `None` ici.
            # Le dire, plutôt que d'analyser à pleine vitesse en laissant croire au
            # bridage — l'aperçu défilerait vite et le réglage paraîtrait sans effet.
            logger.warning(
                "bridage relatif impossible : la source ne déclare pas de cadence",
                job_id=job_id,
                video_fps=info.fps,
            )

        started = perf_counter()
        processed = 0
        last_preview = started
        # `None` et non `started` : le **premier** aperçu doit porter le registre,
        # sinon l'écran reste vide une seconde entière au démarrage — le moment
        # précis où l'on regarde si quelque chose se passe.
        last_vehicles_preview: float | None = None
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

            # ── La fenêtre d'analyse, tranchée **ici** et pas dans l'adaptateur ──
            #
            # C'est la couche qui voit les horodatages de tous les moteurs, donc la
            # seule où la règle puisse être unique et testée sans GPU. `EngineSpec`
            # porte bien `start_ms`, mais uniquement pour qu'un adaptateur puisse
            # éviter de décoder ce qui précède : un moteur qui l'ignore rend les
            # mêmes chiffres, simplement plus lentement. Cette symétrie est ce qui
            # empêche la fenêtre de devenir une de ces divergences que le moteur
            # factice ne traverse jamais.
            #
            # **La fin sort de la boucle**, elle ne saute pas l'image : refermer le
            # générateur arrête le décodage du moteur, ce qui est tout l'intérêt de
            # borner une analyse à cinq minutes d'un fichier d'une heure. La borne
            # est **exclue** — deux fenêtres adjacentes ne partagent donc aucune
            # image, et ne comptent pas deux fois ce qui se passe à leur jointure.
            if config.end_ms is not None and frame.timestamp_ms >= config.end_ms:
                break
            if frame.timestamp_ms < config.start_ms:
                continue

            outcome = session.feed(frame.frame_index, frame.timestamp_ms, frame.tracks)

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
                    # Le registre suit sa **propre** échéance, plus lente : le
                    # construire et le sérialiser à chaque aperçu ferait grossir le
                    # flux avec l'avancement de l'analyse. `None` dit « inchangé »,
                    # et le client garde alors la dernière liste reçue.
                    #
                    # **`None` désactive, `0.0` publie à chaque aperçu** — la même
                    # convention que `preview_interval_s`, délibérément : deux
                    # paramètres voisins où le zéro voudrait dire deux choses
                    # opposées seraient un piège garanti.
                    vehicles = None
                    if preview_vehicles_interval_s is not None and (
                        last_vehicles_preview is None
                        or now - last_vehicles_preview >= preview_vehicles_interval_s
                    ):
                        last_vehicles_preview = now
                        vehicles = session.vehicles(crossed_only=True)
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
                            vehicles=vehicles,
                        )
                    )
                    pending_crossings.clear()
                    pending_zone_events.clear()

            if pacer is not None:
                # **En fin de corps de boucle, délibérément.** L'annulation et la
                # pause sont observées en tête de l'itération suivante : attendre
                # ici les laisse donc toutes deux reprendre la main juste après
                # l'attente, sans troisième point de contrôle à maintenir. Le coût
                # est une attente inutile après la dernière image — au plus une
                # période, sur une analyse qui dure la durée de la vidéo.
                #
                # Les pauses sont déduites du temps écoulé : une analyse suspendue
                # ne doit pas reprendre en rafale pour rattraper son échéance.
                wait = pacer.wait_s(perf_counter() - started - paused_s)
                if wait > 0.0:
                    sleep(wait)

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
                    # **Toujours**, quel que soit l'intervalle, et pour la même
                    # raison que la progression finale : sans lui la dernière liste
                    # affichée serait celle d'un échantillon quelconque, en retard
                    # de quelques véhicules sur les compteurs voisins.
                    #
                    # Filtré depuis `result.vehicles` plutôt que reconstruit :
                    # `session.vehicles()` vient d'être appelé, et le refaire
                    # revoterait chaque plaque pour un résultat identique.
                    vehicles=tuple(record for record in result.vehicles if record.crossed_lines),
                )
            )

        logger.info(
            "analyse terminée",
            job_id=job_id,
            model_id=config.model_id,
            frames=processed,
            duration_s=round(elapsed, 2),
            processing_fps=round(result.processing_fps, 2),
            tracked_vehicles=result.stats.tracked_vehicles,
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

        # **Le plafond par image**, quand il est posé. Il vient après les gardes et non
        # à leur place : `should_detect` dit ce qui *mérite* une inférence, le budget
        # dit combien on en paie sur cette image. Ce qui est écarté ici n'est pas
        # perdu — la piste reçoit l'ancre reprojetée comme n'importe quelle image
        # sautée, et repassera devant le budget à l'image suivante.
        budget = detect_policy.options.max_per_frame
        if budget > 0 and len(wanted) > budget:
            keep = select_within_budget(
                [
                    DetectionCandidate(
                        global_id=track.global_id,
                        width=track.box.width,
                        never_detected=track.global_id not in detect_policy.last_ordinal,
                    )
                    for track in wanted
                ],
                budget,
            )
            wanted = [track for track in wanted if track.global_id in keep]

        measured: dict[int, tuple[PlateDetection, ...]] = {}
        if wanted:
            # **Un seul appel pour toutes les pistes retenues.** C'est à l'adaptateur
            # de décider comment amortir ses inférences ; il ne peut le faire que
            # s'il les voit d'un coup. Cette couche ne sait pas — et n'a pas à
            # savoir — s'il empaquette ou non.
            batch = detector.detect_many(image, [track.box for track in wanted], confidence)
            for track, plates in zip(wanted, batch, strict=True):
                detect_policy.record(track.global_id, ordinal, found=bool(plates))
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
    def _expected_frames(
        info: VideoInfo, stride: int, start_ms: float = 0.0, end_ms: float | None = None
    ) -> int:
        """Nombre d'images **analysées**, pas d'images du fichier.

        C'est l'unité de la barre de progression : diviser par `frame_count` avec
        un pas de 3 la ferait plafonner à 33 %.

        La **fenêtre** entre dans le calcul, et ce n'est pas un raffinement : sans
        elle, une analyse bornée à cinq minutes d'un fichier d'une heure
        s'arrêterait à 8 % en annonçant « terminé », ce qui se lit comme une
        analyse tronquée par une panne. Les bornes sont converties en index par la
        cadence — le seul chemin possible, l'utilisateur choisissant ses bornes sur
        une barre de lecture qui ne connaît que des secondes.

        Une source sans cadence exploitable rend la fenêtre incalculable ; on
        retombe alors sur le compte complet, qui surestime. Une barre qui n'atteint
        pas 100 % est moins trompeuse qu'une barre qui le dépasse — `Progress.ratio`
        borne déjà le second cas, et le premier reste rare.
        """
        stride = max(1, stride)
        if info.frame_count <= 0:
            return 0
        total = max(1, info.frame_count // stride)
        if info.fps <= 0.0 or (start_ms <= 0.0 and end_ms is None):
            return total

        # Les images analysées sont les multiples de `stride`. On borne donc leur
        # **ordinal** `k`, pas leur index : c'est `k` que compte la progression.
        per_ms = info.fps / 1000.0
        first_index = ceil(start_ms * per_ms) if start_ms > 0.0 else 0
        last_index = info.frame_count if end_ms is None else ceil(end_ms * per_ms)
        low = ceil(first_index / stride)
        high = min(total, ceil(last_index / stride))
        return max(0, high - low)

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
