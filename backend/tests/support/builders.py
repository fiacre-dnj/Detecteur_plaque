"""Constructeurs de scénarios de comptage.

Un scénario de comptage écrit à la main est illisible : vingt `TrackObservation`
avec leurs coordonnées noient l'intention. Ces helpers rendent l'intention
visible :

    frames = compose(
        track_path(1, CAR, straight_line((100, 300), (100, 700), steps=20)),
        track_path(2, TRUCK, straight_line((900, 700), (900, 300), steps=20)),
    )

Ils vivent dans `tests/support/` et non dans `conftest.py` : la roue
`ultralytics` embarque son propre paquet `tests`, et un import ambigu y résoudrait
(piège 50 de prompt/13).
"""

from __future__ import annotations

from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import (
    BoundingBox,
    CountingLineDef,
    SessionTrack,
    TrackObservation,
    ZoneDef,
)

# Identifiants COCO, nommés pour que les scénarios se lisent.
PERSON = 0
CAR = 2
MOTORCYCLE = 3
BUS = 5
TRUCK = 7

CLASS_LABELS: dict[int, str] = {
    PERSON: "person",
    CAR: "car",
    MOTORCYCLE: "motorcycle",
    BUS: "bus",
    TRUCK: "truck",
}

type XY = tuple[float, float]


def make_line(
    line_id: str = "l1",
    *,
    a: XY = (0.0, 500.0),
    b: XY = (1920.0, 500.0),
    name: str = "",
    zone_id: str | None = None,
) -> CountingLineDef:
    """Ligne horizontale par défaut, dans le tiers inférieur d'une image 1080p."""
    return CountingLineDef(
        id=line_id,
        name=name or f"Ligne {line_id}",
        a=Point(*a),
        b=Point(*b),
        zone_id=zone_id,
    )


def make_zone(
    zone_id: str = "z1", *, points: tuple[XY, ...] | None = None, name: str = ""
) -> ZoneDef:
    """Zone rectangulaire par défaut, couvrant le centre de l'image."""
    corners = points or ((400.0, 200.0), (1500.0, 200.0), (1500.0, 800.0), (400.0, 800.0))
    return ZoneDef(
        id=zone_id,
        name=name or f"Zone {zone_id}",
        points=tuple(Point(*corner) for corner in corners),
    )


def straight_line(start: XY, end: XY, *, steps: int) -> list[XY]:
    """`steps` positions réparties de `start` à `end`, bornes incluses.

    Un seul pas rend simplement le point de départ : un trajet a besoin de deux
    positions pour avoir une direction.
    """
    if steps <= 1:
        return [start]
    dx = (end[0] - start[0]) / (steps - 1)
    dy = (end[1] - start[1]) / (steps - 1)
    return [(start[0] + dx * i, start[1] + dy * i) for i in range(steps)]


def box_at(centre: XY, *, size: XY = (80.0, 60.0)) -> BoundingBox:
    """Boîte **centrée** sur le point donné.

    Centrée et non ancrée au coin : les scénarios raisonnent en centroïdes, parce
    que c'est le centroïde qui décide du franchissement et de l'appartenance à une
    zone.
    """
    width, height = size
    return BoundingBox(centre[0] - width / 2.0, centre[1] - height / 2.0, width, height)


def track_path(
    track_id: int,
    class_id: int,
    points: list[XY],
    *,
    score: float = 0.9,
    box_size: XY = (80.0, 60.0),
    label: str | None = None,
) -> list[TrackObservation]:
    """Une observation par position : la trajectoire d'une piste, frame par frame."""
    resolved = label or CLASS_LABELS.get(class_id, str(class_id))
    return [
        TrackObservation(
            track_id=track_id,
            class_id=class_id,
            label=resolved,
            score=score,
            box=box_at(point, size=box_size),
        )
        for point in points
    ]


def compose(*paths: list[TrackObservation]) -> list[list[TrackObservation]]:
    """Entrelace plusieurs trajectoires en une suite de frames.

    Les trajectoires de longueurs différentes sont admises : une piste plus
    courte disparaît simplement des frames suivantes, ce qui est exactement ce
    qu'on veut simuler pour une occlusion ou une sortie de champ.
    """
    if not paths:
        return []
    length = max(len(path) for path in paths)
    return [[path[i] for path in paths if i < len(path)] for i in range(length)]


def session_track(
    observation: TrackObservation,
    *,
    hits: int = 5,
    global_id: int = 1,
    previous: XY | None = None,
    identity_label: str = "",
) -> SessionTrack:
    """`SessionTrack` prête à être passée à un compteur, sans passer par la session.

    Les tests des compteurs isolent volontairement le comptage du suivi : ils
    fixent `hits`, `global_id` et le centroïde précédent à la main, ce qui rend
    chaque scénario indépendant de la numérotation.

    `hits=5` et `global_id=1` par défaut : la piste est confirmée et numérotée,
    donc le compteur peut compter. Un scénario qui teste la montée en confiance
    passe explicitement `hits=0`.
    """
    return SessionTrack(
        track_id=observation.track_id,
        class_id=observation.class_id,
        label=observation.label,
        score=observation.score,
        box=observation.box,
        centroid=observation.box.centroid,
        previous_centroid=Point(*previous) if previous else None,
        hits=hits,
        global_id=global_id,
        identity_label=identity_label,
    )
