"""Appartenance d'une piste à une zone — une seule définition, pour tout le domaine.

Le compteur de lignes (pour restreindre une ligne à une zone), le compteur de
zones (pour l'occupation) et le masque de la session (« ignorer hors zone »)
posent tous la même question. La poser trois fois, c'est prendre le risque que
l'une des trois réponses dérive : une ligne compterait un franchissement que le
masque a par ailleurs supprimé, et le total contredirait l'image.

Ce module est séparé de `geometry.py` parce qu'il connaît les modèles du domaine,
alors que `geometry.py` ne connaît que des points — et que `models.py` importe
`geometry.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.geometry import point_in_polygon

if TYPE_CHECKING:
    from collections.abc import Iterable

    from traffic_analysis.features.counting.domain.geometry import Point
    from traffic_analysis.features.counting.domain.models import SessionTrack, ZoneDef


def track_is_in_zone(track: SessionTrack, zone: ZoneDef) -> bool:
    """Le **centroïde** de la piste est-il dans la zone ?

    Le centroïde et non la boîte entière, ni son bord inférieur. Conséquence à
    dire dans l'interface : avec « ignorer hors zone », un véhicule dont le centre
    sort du polygone cesse d'être compté même si sa boîte le chevauche encore —
    d'où le conseil de dessiner large (piège 10 de prompt/13).
    """
    return point_in_polygon(track.centroid, zone.points)


def point_is_in_any_zone(point: Point, zones: Iterable[ZoneDef]) -> bool:
    """Le point est-il dans au moins une zone ?

    C'est la question du **masque**, posée sur une détection qui n'est pas encore
    une piste. Avec plusieurs zones, elles forment ensemble la région d'intérêt et
    non leur intersection : deux voies tracées séparément doivent toutes les deux
    être analysées.
    """
    return any(point_in_polygon(point, zone.points) for zone in zones)
