"""Comptage de franchissements de lignes.

Le compteur **détecte et déduplique au même endroit**, et `observe()` ne rend que
les événements qui ont réellement atteint un compteur. C'est ce qui permet au
badge ✓ de l'interface de dériver du tally : si un franchissement est supprimé par
le garde d'identité, aucun événement ne sort, et l'overlay ne prétend pas qu'un
véhicule est compté alors que le total n'a pas bougé.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.geometry import (
    segments_intersect,
    side_of_line,
)
from traffic_analysis.features.counting.domain.models import (
    CountingLineDef,
    CrossingEvent,
    LineTally,
    SessionTrack,
    ZoneDef,
)
from traffic_analysis.features.counting.domain.zone_geometry import track_is_in_zone

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


@dataclass(slots=True)
class _LineState:
    """Ce que le compteur retient d'un couple (piste, ligne) — de la géométrie seule.

    Aucune comptabilité ici : la déduplication porte sur l'identité, pas sur la
    piste (piège 1 de prompt/13), et une piste détruite par une occlusion
    emporterait sa mémoire avec elle.
    """

    # Dernier côté observé. `0` signifie « pas encore amorcé » : une piste vue
    # pour la première fois n'a pas de côté précédent, donc rien à comparer.
    side: int = 0
    # Franchissement détecté alors que la piste n'était pas encore confirmée.
    # Il est mis en attente, pas jeté : le jeter perdrait tout véhicule qui
    # franchit dans ses premières frames — fréquent avec une ligne près du bord.
    pending_direction: int | None = None


class LineCrossingCounter:
    """Compte **un** franchissement par véhicule, jusqu'à sa prochaine réapparition.

    Deux gardes se superposent, et chacun répond à un bug distinct :

    1. **intersection de segments** — sinon un véhicule qui passe au-delà des
       extrémités tracées est compté, parce qu'il change de côté de la droite
       *infinie* ;
    2. **`(identité, génération)`** — le garde de comptage. La génération est le
       nombre de ré-identifications déjà subies par l'identité
       (`SessionTrack.reid_count`).

    Ce que le garde 2 **coûte**, et qui est voulu (ADR 0009) :

    - un aller-retour réel ne compte **qu'une fois**. Le sens ne ré-arme pas ;
    - un véhicule qui franchit deux lignes successives ne compte **qu'une fois**,
      sur la première ligne franchie. Les lignes suivantes restent à zéro pour
      lui. C'est ce qui garde `crossings == Σ by_line[*].total` vrai sans
      accumuler deux totaux en parallèle.

    Ce qui le **ré-arme** : une vraie ré-identification, et elle seule. La
    galerie n'incrémente `reid_count` que lorsqu'un véhicule réellement disparu
    revient (`reacquire` ou `Admission.reidentified`), donc un tremblement de
    boîte, une occlusion courte tenue par le tracker ou un simple demi-tour ne
    donnent jamais un second comptage. Après ré-armement, la règle repart
    identique : un franchissement, puis plus rien.
    """

    __slots__ = ("_lines", "_min_hits", "_state", "_tallied", "_zones", "by_line")

    def __init__(
        self,
        lines: Sequence[CountingLineDef],
        zones: Sequence[ZoneDef],
        min_hits: int,
    ) -> None:
        self._lines = tuple(lines)
        self._zones = {zone.id: zone for zone in zones}
        self._min_hits = min_hits
        self._state: dict[tuple[int, str], _LineState] = {}
        # Le garde de comptage. Clé : (identité, génération). Ni la ligne ni le
        # sens n'y figurent : un véhicule compte une fois, où qu'il franchisse et
        # dans quelque sens que ce soit, jusqu'à sa prochaine ré-identification.
        self._tallied: set[tuple[int, int]] = set()
        # Chaque ligne a son compteur dès le départ : une ligne sans
        # franchissement doit s'afficher à zéro, pas manquer du tableau.
        self.by_line: dict[str, LineTally] = {line.id: LineTally() for line in self._lines}

    def observe(
        self,
        tracks: Iterable[SessionTrack],
        timestamp_ms: float,
        frame_index: int,
    ) -> tuple[CrossingEvent, ...]:
        """Fait avancer le compteur d'une frame.

        Ne rend que les franchissements **effectivement comptabilisés**.
        """
        events: list[CrossingEvent] = []
        for track in tracks:
            confirmed = track.hits >= self._min_hits
            for line in self._lines:
                self._observe_line(track, line, confirmed, timestamp_ms, frame_index, events)
        return tuple(events)

    def counted_identities(self) -> set[int]:
        """Identités ayant réellement fait bouger un compteur.

        C'est la **source du badge ✓**. Le dériver d'ici et non de la comptabilité
        d'une piste est ce qui évite d'afficher « compté » pour un franchissement
        que le garde a supprimé.

        Le ✓ ne se rétracte **jamais** : un ré-armement ajoute une génération sans
        retirer les précédentes, donc un véhicule ré-identifié reste marqué compté
        en attendant de recroiser. Voir le franchissement disparaître de l'overlay
        parce que le véhicule est revenu se lirait comme une panne de comptage.
        """
        return {global_id for global_id, _ in self._tallied}

    def _observe_line(
        self,
        track: SessionTrack,
        line: CountingLineDef,
        confirmed: bool,
        timestamp_ms: float,
        frame_index: int,
        events: list[CrossingEvent],
    ) -> None:
        state = self._state.setdefault((track.track_id, line.id), _LineState())

        # 1. Émission différée : la piste vient de se confirmer, et un
        #    franchissement l'attendait.
        if state.pending_direction is not None and confirmed:
            event = self._tally(track, line, state.pending_direction, timestamp_ms, frame_index)
            state.pending_direction = None
            if event is not None:
                events.append(event)

        side = side_of_line(line.a, line.b, track.centroid)
        # 2. Pile sur la ligne : on attend la frame suivante. Trancher
        #    arbitrairement produirait un faux franchissement dans un sens au
        #    hasard dès que le centroïde effleure la ligne.
        if side == 0:
            return

        # 3. Amorçage : une piste vue pour la première fois déjà au-delà d'une
        #    ligne n'a pas été *observée* la franchir. On mémorise son côté et on
        #    ne compte rien — sinon chaque véhicule déjà passé au démarrage de
        #    l'analyse serait compté.
        if state.side == 0:
            state.side = side
            return

        if side == state.side:
            return

        # 4. Changement de côté : deux conditions **géométriques** doivent tenir.
        #    La déduplication n'en fait pas partie — elle est décidée dans
        #    `_tally`, qui refuse en rendant `None`. Filtrer ici sur ce qui a déjà
        #    compté remettrait un garde sur la piste, que l'occlusion efface.
        accepted = self._crossing_is_in_scope(track, line) and segments_intersect(
            track.previous_centroid or track.centroid, track.centroid, line.a, line.b
        )
        if accepted:
            if confirmed:
                event = self._tally(track, line, side, timestamp_ms, frame_index)
                if event is not None:
                    events.append(event)
            else:
                state.pending_direction = side

        # 5. Le côté est écrit **même quand le franchissement est rejeté**.
        #    Sans cela, la piste « regarde dans le mauvais sens » et son
        #    franchissement suivant compte à l'envers (piège 11 de prompt/13).
        state.side = side

    def _crossing_is_in_scope(self, track: SessionTrack, line: CountingLineDef) -> bool:
        """La ligne est-elle active à cet endroit pour cette piste ?

        Une ligne liée à une zone ne compte que ce qui traverse *dans* la zone :
        c'est ce qui permet de compter une seule voie d'un carrefour que la même
        ligne traverse deux fois.

        Une zone référencée mais absente laisse la ligne compter partout. Le cas
        est déjà refusé à la validation de l'API ; si une configuration ancienne y
        échappe, sous-compter en silence serait l'erreur la plus difficile à
        remarquer.
        """
        if line.zone_id is None:
            return True
        zone = self._zones.get(line.zone_id)
        if zone is None:
            return True
        return track_is_in_zone(track, zone)

    def _tally(
        self,
        track: SessionTrack,
        line: CountingLineDef,
        direction: int,
        timestamp_ms: float,
        frame_index: int,
    ) -> CrossingEvent | None:
        """Comptabilise un franchissement, ou refuse et rend `None`.

        Un seul refus : cette identité a déjà compté pour sa génération courante.
        Peu importe que ce soit sur une autre ligne, dans l'autre sens, ou sous
        une piste depuis longtemps détruite — c'est le même véhicule, il a déjà
        été compté, et il ne le sera plus tant qu'il ne sera pas réapparu.

        `track.reid_count` est lu et non recalculé : la session l'a arrêté pour
        cette frame dans `_resolve_identities`, juste avant `observe`. Le
        compteur n'a donc pas à savoir ce qu'est une galerie.

        Rendre `None` plutôt qu'un événement est ce qui garde le badge ✓ honnête.
        """
        key = (track.global_id, track.reid_count)
        if key in self._tallied:
            return None
        self._tallied.add(key)

        label = track.counting_label
        tally = self.by_line[line.id]
        tally.total += 1
        tally.by_class[label] = tally.by_class.get(label, 0) + 1
        if direction > 0:
            tally.positive += 1
        else:
            tally.negative += 1

        return CrossingEvent(
            line_id=line.id,
            global_id=track.global_id,
            track_id=track.track_id,
            label=label,
            direction=direction,
            timestamp_ms=timestamp_ms,
            frame_index=frame_index,
            # Le texte **voté** porté par la piste, jamais la lecture d'une frame :
            # le compteur ne sait pas qu'une OCR existe, il lit un champ. `None` et
            # non `""` — « pas encore lu » est une information, une chaîne vide
            # serait une plaque vide.
            plate_text=track.plate_text or None,
            plate_text_score=track.plate_text_score or None,
        )
