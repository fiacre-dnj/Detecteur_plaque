"""La session de comptage : la composition, une frame à la fois.

**La même session sert le fichier différé et le flux temps réel.** C'est tout
l'intérêt du découpage : il n'existe qu'une implémentation du comptage, donc les
deux modes ne peuvent pas divergerurer.

L'ordre des étapes de `feed()` est impératif et deux d'entre elles ont été payées
au prix d'un bug :

- **`_mask` avant le suivi**, jamais après : avec « ignorer hors zone », une
  détection hors zone ne doit jamais devenir une piste ;
- **relâcher avant d'admettre** : le moteur détruit une piste morte et crée sa
  remplaçante dans le *même* appel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.line_counter import LineCrossingCounter
from traffic_analysis.features.counting.domain.models import (
    AnalysisStats,
    CountingLineDef,
    CrossingEvent,
    Diagnostics,
    FrameOutcome,
    LineCrossing,
    PlateDetection,
    SessionTrack,
    TrackObservation,
    VehicleRecord,
    ZoneDef,
)
from traffic_analysis.features.counting.domain.reid import (
    IdentityGallery,
    ReidCandidate,
    ReidOptions,
    build_signature,
)
from traffic_analysis.features.counting.domain.speed import SpeedEstimator, to_kmh
from traffic_analysis.features.counting.domain.zone_counter import ZonePresenceCounter
from traffic_analysis.features.counting.domain.zone_geometry import point_is_in_any_zone

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    import numpy.typing as npt

# En dessous de trois secondes de flux analysé, l'extrapolation du débit oscille
# trop pour être publiable : on rend 0 et l'interface le dit.
MIN_SCENE_MS_FOR_FLOW = 3000.0
_MS_PER_MINUTE = 60_000.0


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """Réglages de comptage d'une session.

    Tous viennent de la requête : ce sont les réglages *vivants* de l'utilisateur,
    et non des constantes du catalogue.
    """

    lines: tuple[CountingLineDef, ...] = ()
    zones: tuple[ZoneDef, ...] = ()
    mask_outside_zones: bool = False
    min_hits: int = 2
    # Miroir exact de `track_buffer: 75` du tracker Ultralytics (≈ 2,5 s à 30 fps).
    # Si l'une des deux valeurs change, l'autre doit suivre, sinon le moteur et le
    # domaine ne sont plus d'accord sur ce qu'est « une piste perdue ».
    max_lost_ms: float = 2500.0
    pixels_per_meter: float | None = None
    reid: ReidOptions = field(default_factory=ReidOptions)


@dataclass(slots=True)
class _IdentityAggregate:
    """Ce que la session retient d'une identité sur toute la session.

    La galerie connaît l'apparence et la classe votée ; cet agrégat connaît
    l'histoire — vu de/à, lignes franchies, zones visitées, meilleure plaque.
    """

    first_seen_ms: float
    last_seen_ms: float
    crossings: list[LineCrossing] = field(default_factory=list)
    best_plate_score: float | None = None


class AnalysisSession:
    """Compte les véhicules d'un flux de détections suivies, frame par frame."""

    __slots__ = (
        "_aggregates",
        "_config",
        "_counter",
        "_first_timestamp_ms",
        "_frame_diagonal",
        "_frame_index",
        "_gallery",
        "_identity_of_lost_track",
        "_last_timestamp_ms",
        "_masked_out",
        "_released_ids",
        "_speed",
        "_tracks",
        "_zones",
    )

    def __init__(self, config: SessionConfig, frame_width: int, frame_height: int) -> None:
        self._config = config
        self._frame_diagonal = (frame_width**2 + frame_height**2) ** 0.5
        self._counter = LineCrossingCounter(config.lines, config.zones, config.min_hits)
        self._zones = ZonePresenceCounter(config.zones, config.min_hits)
        self._gallery = IdentityGallery(config.reid)
        self._speed = SpeedEstimator()
        # Toutes les pistes connues, pas seulement les actives : `_release_lost`
        # doit pouvoir relâcher une piste qui a cessé d'être rapportée.
        self._tracks: dict[int, SessionTrack] = {}
        self._aggregates: dict[int, _IdentityAggregate] = {}
        # Identités relâchées mais dont la piste peut ressusciter avec le même id.
        self._released_ids: set[int] = set()
        # id de piste perdu → (identité qu'il portait, dernier instant vu).
        # BoT-SORT réutilise ses ids : c'est ce qui permet la récupération par id.
        self._identity_of_lost_track: dict[int, tuple[int, float]] = {}
        self._first_timestamp_ms: float | None = None
        self._last_timestamp_ms: float = 0.0
        self._frame_index = 0
        self._masked_out = 0

    def feed(
        self,
        frame_index: int,
        timestamp_ms: float,
        image: npt.NDArray[np.uint8],
        observations: Sequence[TrackObservation],
    ) -> FrameOutcome:
        """Fait avancer la session d'une frame. **L'ordre des étapes est le contrat.**"""
        kept = self._mask(observations)
        active = self._advance_tracks(kept, timestamp_ms)

        # Relâcher AVANT d'admettre. Le moteur détruit une piste morte et crée sa
        # remplaçante dans le même appel : relâcher les identités *après*
        # `admit_batch` laisserait l'ancienne marquée vivante exactement quand sa
        # remplaçante la demande, l'exclusivité refuserait le match, et le véhicule
        # serait admis comme neuf. Mesuré avec le mauvais ordre : 2 véhicules
        # uniques et 0 ré-identification ; avec le bon : 1 et 1.
        self._release_lost(timestamp_ms)
        self._resolve_identities(active, image, timestamp_ms)

        crossings = self._counter.observe(active, timestamp_ms, frame_index)
        zone_events = self._zones.observe(active, timestamp_ms, frame_index)

        # Le badge ✓ dérive du tally, jamais de la comptabilité d'une piste : un
        # franchissement supprimé par le garde d'identité ne doit pas peindre ✓,
        # tandis qu'une ré-identification doit le conserver.
        counted = self._counter.counted_identities()
        for track in active:
            track.counted = track.global_id != 0 and track.global_id in counted
            track.speed_px_s = self._speed.observe(track.global_id, track.centroid, timestamp_ms)

        self._aggregate(active, crossings, timestamp_ms)

        self._frame_index = frame_index
        if self._first_timestamp_ms is None:
            self._first_timestamp_ms = timestamp_ms
        self._last_timestamp_ms = timestamp_ms

        return FrameOutcome(
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            tracks=active,
            crossings=crossings,
            zone_events=zone_events,
        )

    # ── Étapes de `feed` ─────────────────────────────────────────────────────

    def _mask(self, observations: Sequence[TrackObservation]) -> tuple[TrackObservation, ...]:
        """Filtre les détections hors zone quand le masque est actif.

        **Avant le suivi, jamais après.** Avec `mask_outside_zones`, les zones sont
        la région d'intérêt : une détection en dehors ne devient jamais une piste,
        donc les voitures en stationnement et le parking dans un coin de l'image ne
        coûtent rien et n'entrent dans aucun compteur. Sans le masque, une zone
        n'est qu'un filtre de comptage.
        """
        if not self._config.mask_outside_zones or not self._config.zones:
            return tuple(observations)

        kept: list[TrackObservation] = []
        for observation in observations:
            if point_is_in_any_zone(observation.box.centroid, self._config.zones):
                kept.append(observation)
            else:
                self._masked_out += 1
        return tuple(kept)

    def _advance_tracks(
        self, observations: Sequence[TrackObservation], timestamp_ms: float
    ) -> tuple[SessionTrack, ...]:
        """Met à jour l'état vivant des pistes rapportées sur cette frame."""
        active: list[SessionTrack] = []
        for observation in observations:
            centroid = observation.box.centroid
            track = self._tracks.get(observation.track_id)
            if track is None:
                recovered_id = self._recover_identity(observation.track_id, timestamp_ms)
                track = SessionTrack(
                    track_id=observation.track_id,
                    class_id=observation.class_id,
                    label=observation.label,
                    score=observation.score,
                    box=observation.box,
                    centroid=centroid,
                    hits=1,
                    global_id=recovered_id,
                    last_seen_ms=timestamp_ms,
                )
                self._tracks[observation.track_id] = track
            else:
                track.previous_centroid = track.centroid
                track.class_id = observation.class_id
                track.label = observation.label
                track.score = observation.score
                track.box = observation.box
                track.centroid = centroid
                track.hits += 1
                track.last_seen_ms = timestamp_ms
            # Les plaques appartiennent à la frame courante : les garder d'une
            # frame à l'autre ferait afficher une plaque là où le modèle n'en voit
            # plus.
            track.plates.clear()
            active.append(track)
        return tuple(active)

    def _release_lost(self, timestamp_ms: float) -> None:
        """Relâche les identités des pistes silencieuses depuis trop longtemps.

        Parcourt **toutes** les pistes connues, pas seulement les actives : une
        piste qui a cessé d'être rapportée n'apparaît plus dans `active` et ne
        serait donc jamais relâchée.

        Le release est daté de `last_seen_ms` — le dernier instant réellement vu —
        et non de « maintenant ». C'est ce qui préserve le budget de déplacement de
        la ré-identification (piège 14 de prompt/13).
        """
        lost: list[int] = []
        for track_id, track in self._tracks.items():
            if timestamp_ms - track.last_seen_ms <= self._config.max_lost_ms:
                continue
            lost.append(track_id)
            if track.global_id != 0:
                self._gallery.release(track.global_id, track.last_seen_ms, track.centroid)
                self._released_ids.add(track.global_id)
                # On retient quelle identité portait cet id de piste : BoT-SORT
                # peut ressusciter le même id pour le même véhicule, et c'est une
                # récupération plus fiable qu'un appariement d'apparence.
                self._identity_of_lost_track[track_id] = (track.global_id, track.last_seen_ms)
        for track_id in lost:
            del self._tracks[track_id]

        # Purge de la mémoire des ids perdus, pour la borner sur un clip long.
        # Ce n'est **pas** ce qui garantit la fraîcheur d'une récupération :
        # `_advance_tracks` s'exécute avant cette méthode, donc la vérification
        # d'âge doit avoir lieu au moment de la reprise, dans `_recover_identity`.
        expired = [
            track_id
            for track_id, (_, last_seen) in self._identity_of_lost_track.items()
            if timestamp_ms - last_seen > self._config.reid.max_gap_ms
        ]
        for track_id in expired:
            del self._identity_of_lost_track[track_id]

    def _recover_identity(self, track_id: int, timestamp_ms: float) -> int:
        """Identité que cet id de piste portait avant d'être perdu, ou `0`.

        BoT-SORT réutilise ses identifiants : quand le même id revient peu après
        avoir été perdu, c'est le même véhicule. Cette récupération est **plus
        fiable** qu'un appariement d'apparence — un véhicule à contre-jour ou trop
        petit peut ne produire aucune signature exploitable, et deviendrait alors
        un véhicule de plus.

        Au-delà de la fenêtre d'appariement de la galerie, en revanche, un id
        réutilisé désigne presque sûrement un **autre** véhicule : le rattacher
        fusionnerait deux véhicules distincts, ce qui est l'erreur la plus
        difficile à remarquer — le total baisse sans raison visible à l'écran.
        """
        previous = self._identity_of_lost_track.pop(track_id, None)
        if previous is None:
            return 0
        global_id, last_seen_ms = previous
        if timestamp_ms - last_seen_ms > self._config.reid.max_gap_ms:
            return 0
        return global_id

    def _resolve_identities(
        self,
        active: Sequence[SessionTrack],
        image: npt.NDArray[np.uint8],
        timestamp_ms: float,
    ) -> None:
        """Attribue, retrouve ou entretient l'identité de chaque piste active."""
        candidates: list[ReidCandidate] = []
        for track in active:
            if track.global_id == 0:
                candidates.append(
                    ReidCandidate(
                        track_id=track.track_id,
                        class_id=track.class_id,
                        label=track.label,
                        centroid=track.centroid,
                        signature=build_signature(image, track.box),
                    )
                )
                continue

            # Récupération par id : BoT-SORT peut ressusciter un id de piste dont
            # l'identité venait d'être relâchée. C'est une vraie ré-identification.
            if track.global_id in self._released_ids:
                if self._gallery.reacquire(
                    track.global_id, track.track_id, timestamp_ms, track.centroid
                ):
                    track.reid_count = self._gallery.reid_count_of(track.global_id)
                self._released_ids.discard(track.global_id)

            self._gallery.vote(track.global_id, track.class_id, track.label)
            track.identity_label = self._gallery.label_of(track.global_id)

            # Rafraîchissement d'apparence une frame sur N : plusieurs points de
            # vue par identité, à coût maîtrisé.
            if self._frame_index % self._config.reid.refresh_every_frames == 0:
                signature = build_signature(image, track.box)
                if signature is not None:
                    self._gallery.refresh(track.global_id, signature)

        if not candidates:
            return

        admissions = self._gallery.admit_batch(candidates, timestamp_ms, self._frame_diagonal)
        by_track = {admission.track_id: admission for admission in admissions}
        for track in active:
            admission = by_track.get(track.track_id)
            if admission is None:
                continue
            track.global_id = admission.global_id
            track.reid_count = self._gallery.reid_count_of(admission.global_id)
            self._gallery.vote(track.global_id, track.class_id, track.label)
            track.identity_label = self._gallery.label_of(track.global_id)
            self._released_ids.discard(track.global_id)

    def _aggregate(
        self,
        active: Sequence[SessionTrack],
        crossings: Sequence[CrossingEvent],
        timestamp_ms: float,
    ) -> None:
        """Tient à jour l'histoire de chaque identité, pour le registre."""
        for track in active:
            if track.global_id == 0:
                continue
            aggregate = self._aggregates.get(track.global_id)
            if aggregate is None:
                self._aggregates[track.global_id] = _IdentityAggregate(
                    first_seen_ms=timestamp_ms, last_seen_ms=timestamp_ms
                )
            else:
                aggregate.last_seen_ms = timestamp_ms

        for crossing in crossings:
            aggregate = self._aggregates.get(crossing.global_id)
            if aggregate is not None:
                aggregate.crossings.append(
                    LineCrossing(crossing.line_id, crossing.direction, crossing.timestamp_ms)
                )

    # ── ANPR ─────────────────────────────────────────────────────────────────

    def record_plates(self, track: SessionTrack, plates: Sequence[PlateDetection]) -> None:
        """Attache les plaques détectées à une piste et met à jour son agrégat.

        Appelée par le service **après** `feed` et **avant** le snapshot : la
        timeline doit porter les plaques, sinon la relecture n'en affiche aucune.
        """
        if not plates:
            return
        track.plates.extend(plates)

        best = max(plate.score for plate in plates)
        aggregate = self._aggregates.get(track.global_id)
        if aggregate is None:
            return
        if aggregate.best_plate_score is None or best > aggregate.best_plate_score:
            aggregate.best_plate_score = best

    # ── Sorties ──────────────────────────────────────────────────────────────

    def stats(self) -> AnalysisStats:
        """Statistiques courantes, dans la forme exacte que l'interface affiche.

        `crossings` et `by_class` sont **dérivés** de `by_line` : les accumuler en
        parallèle produirait tôt ou tard deux compteurs qui se contredisent.
        """
        by_line = self._counter.by_line
        crossings = sum(tally.total for tally in by_line.values())

        by_class: dict[str, int] = {}
        for tally in by_line.values():
            for label, count in tally.by_class.items():
                by_class[label] = by_class.get(label, 0) + count

        analysed_ms = (
            self._last_timestamp_ms - self._first_timestamp_ms
            if self._first_timestamp_ms is not None
            else 0.0
        )
        # En dessous de trois secondes de flux, le débit oscille trop pour être
        # publiable : rendre 0 et le dire dans l'interface vaut mieux qu'un chiffre
        # qui saute de 12 à 240 véhicules par minute.
        vehicles_per_minute = (
            crossings / analysed_ms * _MS_PER_MINUTE
            if analysed_ms >= MIN_SCENE_MS_FOR_FLOW
            else 0.0
        )

        confirmed = sum(1 for track in self._tracks.values() if track.hits >= self._config.min_hits)

        return AnalysisStats(
            unique_vehicles=self._gallery.size,
            unique_by_class=self._gallery.count_by_class(),
            crossings=crossings,
            by_class=by_class,
            by_line=dict(by_line),
            by_zone=dict(self._zones.by_zone),
            reid_hits=self._gallery.hits,
            vehicles_per_minute=vehicles_per_minute,
            active_tracks=len(self._tracks),
            # Côté serveur, le temps « écoulé » **est** le temps de scène analysé :
            # il n'y a pas d'attente d'utilisateur à mesurer. Le champ reste dans
            # le contrat parce que l'interface affiche les deux.
            elapsed_ms=analysed_ms,
            analysed_scene_ms=analysed_ms,
            diagnostics=Diagnostics(
                # Les détections fortes et faibles n'existent qu'avant le seuil du
                # moteur : le domaine ne les voit pas, et inventer un chiffre
                # serait pire que rendre zéro. L'adaptateur les renseignera s'il
                # peut les observer.
                masked_out=self._masked_out,
                confirmed_tracks=confirmed,
                tentative_tracks=len(self._tracks) - confirmed,
            ),
        )

    def vehicles(self) -> tuple[VehicleRecord, ...]:
        """Le registre : une ligne par identité, triée par `global_id`.

        Les cartes de synthèse disent *combien*, le registre dit *lesquels*. C'est
        ce qui rend un total vérifiable plutôt que croyable.
        """
        records: list[VehicleRecord] = []
        for global_id in sorted(self._aggregates):
            aggregate = self._aggregates[global_id]
            average = self._speed.average_px_s(global_id)
            records.append(
                VehicleRecord(
                    global_id=global_id,
                    # Le libellé du **vote**, pas la dernière lecture.
                    label=self._gallery.label_of(global_id),
                    first_seen_ms=aggregate.first_seen_ms,
                    last_seen_ms=aggregate.last_seen_ms,
                    crossed_lines=tuple(aggregate.crossings),
                    zones_visited=self._zones.zones_visited(global_id),
                    reid_count=self._gallery.reid_count_of(global_id),
                    avg_speed_px_s=average,
                    avg_speed_kmh=to_kmh(average, self._config.pixels_per_meter),
                    best_plate_score=aggregate.best_plate_score,
                )
            )
        return tuple(records)
