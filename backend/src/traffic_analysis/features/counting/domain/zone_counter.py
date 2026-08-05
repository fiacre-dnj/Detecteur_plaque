"""Présence en zone : entrées uniques et occupation instantanée.

Deux notions dans le même objet, et la confusion entre elles est l'erreur
classique :

- **`entries`** est un cumul d'entrées uniques par identité. Il ne décroît jamais.
- **`inside`** est une lecture instantanée, **réécrite** à chaque frame. La
  cumuler produirait un nombre de « présents » qui ne cesse de croître.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.models import (
    SessionTrack,
    ZoneDef,
    ZoneEntryEvent,
    ZoneTally,
)
from traffic_analysis.features.counting.domain.zone_geometry import track_is_in_zone

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class ZonePresenceCounter:
    """Compte les entrées de zone et lit l'occupation, frame par frame."""

    __slots__ = ("_entered", "_inside", "_min_hits", "_zones", "by_zone")

    def __init__(self, zones: Sequence[ZoneDef], min_hits: int) -> None:
        self._zones = tuple(zones)
        self._min_hits = min_hits
        # Dernier état connu par couple (piste, zone). `None` (absent) signifie
        # « pas encore évalué », ce qui est distinct de `False` (« vu dehors ») :
        # seule la transition False → True est une entrée.
        self._inside: dict[tuple[int, str], bool] = {}
        # Garde d'unicité par identité : un véhicule qui sort puis revient n'est
        # pas une seconde entrée.
        self._entered: set[tuple[str, int]] = set()
        # Chaque zone a son compteur dès le départ : une zone sans entrée doit
        # s'afficher à zéro, pas manquer du tableau.
        self.by_zone: dict[str, ZoneTally] = {zone.id: ZoneTally() for zone in self._zones}

    def observe(
        self,
        tracks: Iterable[SessionTrack],
        timestamp_ms: float,
        frame_index: int,
    ) -> tuple[ZoneEntryEvent, ...]:
        """Fait avancer le compteur d'une frame.

        L'occupation est recalculée intégralement : une piste qui disparaît du
        champ vide bien la zone, alors qu'une mise à jour incrémentale laisserait
        le dernier chiffre affiché pour toujours.
        """
        events: list[ZoneEntryEvent] = []
        materialised = tuple(tracks)

        for zone in self._zones:
            inside_now = 0
            for track in materialised:
                inside = track_is_in_zone(track, zone)
                if inside:
                    # L'occupation compte ce que l'on **voit**, y compris les
                    # pistes encore provisoires : les exclure ferait retarder le
                    # chiffre affiché de `min_hits` frames par rapport à l'image,
                    # ce que l'utilisateur lit comme un bug d'affichage.
                    inside_now += 1

                event = self._evaluate_entry(track, zone, inside, timestamp_ms, frame_index)
                if event is not None:
                    events.append(event)

            # Une lecture, pas une accumulation.
            self.by_zone[zone.id].inside = inside_now

        return tuple(events)

    def _evaluate_entry(
        self,
        track: SessionTrack,
        zone: ZoneDef,
        inside: bool,
        timestamp_ms: float,
        frame_index: int,
    ) -> ZoneEntryEvent | None:
        key = (track.track_id, zone.id)

        # Report sous `min_hits` : on sort **sans écrire `_inside`**.
        #
        # C'est l'écriture de l'état qu'il faut différer, pas seulement
        # l'émission. Si le front dehors→dedans était consommé pendant que la
        # piste est encore provisoire, l'entrée serait perdue **silencieusement**
        # — et rien dans les compteurs ne permettrait de s'en apercevoir
        # (piège 9 de prompt/13).
        if inside and track.hits < self._min_hits:
            return None

        previous = self._inside.get(key)
        self._inside[key] = inside

        # `previous is False` et non `not previous` : `None` signifie « première
        # évaluation », et une piste déjà dedans à sa première évaluation amorce
        # l'état sans émettre — elle n'a pas été *observée* entrer.
        if previous is not False or not inside:
            return None

        identity_key = (zone.id, track.global_id)
        if identity_key in self._entered:
            return None
        self._entered.add(identity_key)

        label = track.counting_label
        tally = self.by_zone[zone.id]
        tally.entries += 1
        tally.by_class[label] = tally.by_class.get(label, 0) + 1

        return ZoneEntryEvent(
            zone_id=zone.id,
            global_id=track.global_id,
            label=label,
            timestamp_ms=timestamp_ms,
            frame_index=frame_index,
        )

    def zones_visited(self, global_id: int) -> tuple[str, ...]:
        """Zones dans lesquelles cette identité est entrée, pour son registre."""
        return tuple(zone_id for zone_id, entered_id in self._entered if entered_id == global_id)
