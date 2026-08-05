"""Scénarios de trafic partagés, rejouables par n'importe quel test.

Ils existent pour que les invariants comptables puissent être vérifiés sur une
**variété** de situations plutôt que sur un cas favorable : un invariant qui ne
tient que sur un véhicule qui traverse tout droit ne protège de rien.

Chaque scénario est décrit par des `TrackObservation` fabriquées à la main — aucun
moteur, aucun modèle, aucun GPU.
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.support.builders import (
    BUS,
    CAR,
    MOTORCYCLE,
    TRUCK,
    compose,
    make_line,
    make_zone,
    straight_line,
    track_path,
)
from traffic_analysis.features.counting.domain.models import TrackObservation
from traffic_analysis.features.counting.domain.tracking_session import SessionConfig

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FPS = 25.0
FRAME_MS = 1000.0 / FPS

_LINE = make_line("l1")
_ZONE = make_zone("z1", points=((400.0, 200.0), (1500.0, 200.0), (1500.0, 800.0), (400.0, 800.0)))


@dataclass(frozen=True, slots=True)
class Scenario:
    """Un scénario de trafic rejouable frame par frame."""

    name: str
    config: SessionConfig
    frames: list[list[TrackObservation]]

    def __str__(self) -> str:
        return self.name


def _descending(x: float, *, steps: int = 14) -> list[tuple[float, float]]:
    return straight_line((x, 250.0), (x, 800.0), steps=steps)


def _ascending(x: float, *, steps: int = 14) -> list[tuple[float, float]]:
    return straight_line((x, 800.0), (x, 250.0), steps=steps)


def all_scenarios() -> list[Scenario]:
    """La batterie complète, du cas trivial aux cas qui ont produit des bugs."""
    return [
        Scenario(
            "un-vehicule-traverse",
            SessionConfig(lines=(_LINE,)),
            compose(track_path(1, CAR, _descending(900.0))),
        ),
        Scenario(
            "deux-sens-simultanes",
            SessionConfig(lines=(_LINE,)),
            compose(
                track_path(1, CAR, _descending(700.0)),
                track_path(2, TRUCK, _ascending(1200.0)),
            ),
        ),
        Scenario(
            "quatre-classes-melangees",
            SessionConfig(lines=(_LINE,)),
            compose(
                track_path(1, CAR, _descending(500.0)),
                track_path(2, TRUCK, _descending(800.0)),
                track_path(3, BUS, _ascending(1100.0)),
                track_path(4, MOTORCYCLE, _ascending(1400.0), box_size=(40.0, 60.0)),
            ),
        ),
        Scenario(
            "aller-retour-du-meme-vehicule",
            SessionConfig(lines=(_LINE,)),
            compose(
                track_path(1, CAR, [*_descending(900.0, steps=8), *_ascending(900.0, steps=8)])
            ),
        ),
        Scenario(
            "tremblement-sur-la-ligne",
            SessionConfig(lines=(_LINE,)),
            compose(
                track_path(
                    1,
                    CAR,
                    [
                        (900.0, 460.0),
                        (900.0, 470.0),
                        (900.0, 520.0),
                        (900.0, 490.0),
                        (900.0, 515.0),
                        (900.0, 495.0),
                        (900.0, 600.0),
                        (900.0, 700.0),
                    ],
                )
            ),
        ),
        Scenario(
            "vehicule-au-dela-des-extremites",
            SessionConfig(lines=(make_line("l1", a=(800.0, 500.0), b=(1000.0, 500.0)),)),
            compose(
                track_path(1, CAR, _descending(900.0)),  # traverse le segment
                track_path(2, CAR, _descending(200.0)),  # passe bien à côté
            ),
        ),
        Scenario(
            "ne-fait-que-passer-sans-jamais-croiser",
            SessionConfig(lines=(_LINE,)),
            compose(track_path(1, CAR, straight_line((300.0, 250.0), (1600.0, 250.0), steps=14))),
        ),
        Scenario(
            "deux-lignes-successives",
            SessionConfig(
                lines=(
                    make_line("haute", a=(0.0, 400.0), b=(1920.0, 400.0)),
                    make_line("basse", a=(0.0, 700.0), b=(1920.0, 700.0)),
                )
            ),
            compose(track_path(1, CAR, _descending(900.0, steps=20))),
        ),
        Scenario(
            "ligne-restreinte-a-une-zone",
            SessionConfig(lines=(make_line("l1", zone_id="z1"),), zones=(_ZONE,)),
            compose(
                track_path(1, CAR, _descending(900.0)),  # dans la zone
                track_path(2, TRUCK, _descending(150.0)),  # hors de la zone
            ),
        ),
        Scenario(
            "zone-avec-entrees-et-sorties",
            SessionConfig(lines=(_LINE,), zones=(_ZONE,)),
            compose(
                track_path(1, CAR, straight_line((100.0, 500.0), (1700.0, 500.0), steps=16)),
                track_path(2, BUS, _descending(900.0)),
            ),
        ),
        Scenario(
            "masque-hors-zone-actif",
            SessionConfig(lines=(_LINE,), zones=(_ZONE,), mask_outside_zones=True),
            compose(
                track_path(1, CAR, _descending(900.0)),
                track_path(2, TRUCK, _descending(150.0)),  # masqué : jamais suivi
            ),
        ),
        Scenario(
            "classe-qui-vacille-entre-bus-et-camion",
            SessionConfig(lines=(_LINE,)),
            _alternating_class_frames(),
        ),
        Scenario(
            "aucune-geometrie",
            SessionConfig(),
            compose(track_path(1, CAR, _descending(900.0))),
        ),
        Scenario(
            "frames-vides-au-milieu",
            SessionConfig(lines=(_LINE,)),
            [
                *compose(track_path(1, CAR, _descending(900.0, steps=8))),
                *[[] for _ in range(5)],
                *compose(track_path(2, TRUCK, _ascending(600.0, steps=8))),
            ],
        ),
    ]


def _alternating_class_frames() -> list[list[TrackObservation]]:
    """Une piste dont la lecture alterne, avec une majorité nette pour `truck`.

    Le vote majoritaire doit stabiliser le libellé ; la répartition par classe doit
    continuer de sommer au nombre d'uniques après le basculement.
    """
    readings = [BUS, TRUCK, TRUCK, CAR, TRUCK, TRUCK, BUS, TRUCK, TRUCK, TRUCK, TRUCK, TRUCK]
    path = _descending(900.0, steps=len(readings))
    return [
        [track_path(1, class_id, [point])[0]]
        for class_id, point in zip(readings, path, strict=True)
    ]
