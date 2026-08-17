"""L'échelle pixels/mètre **là où le véhicule se trouve**, et non pour l'image entière.

**Pourquoi une échelle unique ne peut pas suffire.** Une caméra de trafic regarde
la chaussée en biais. Sur le plan du sol, un mètre vaut donc quelques pixels au
fond de l'image et quelques dizaines au premier plan — couramment un facteur 3 à
4 entre le haut et le bas du champ. Un réglage `pixels_per_meter` unique est
juste à une profondeur et faux partout ailleurs, et l'erreur se transporte
telle quelle dans les km/h du registre.

**Ce que ce module utilise à la place.** Chaque ligne de comptage peut porter sa
longueur réelle (`length_m`). Le rapport `longueur en pixels / longueur en
mètres` donne une échelle **mesurée**, valable à la profondeur où ce trait est
posé — c'est-à-dire là où les véhicules le franchissent, donc exactement là où
leur vitesse nous intéresse. Plusieurs lignes calibrées à des profondeurs
différentes échantillonnent le gradient de perspective sans qu'on ait à
modéliser quoi que ce soit.

**La règle de choix est « la ligne la plus proche », et rien de plus subtil.**
Interpoler entre deux lignes produirait, entre elles, une échelle que personne
n'a mesurée — et ce dépôt préfère taire une valeur qu'en inventer une. La
distance est mesurée au **segment**, pas à sa droite support : une ligne dont on
s'est éloigné le long de son prolongement n'est pas « proche ».

**Repli complet sur l'ancien comportement.** Sans aucune ligne calibrée, le champ
rend l'échelle globale du réglage — donc une configuration existante produit
exactement les mêmes chiffres qu'avant. C'est ce qui rend cette fonctionnalité
purement additive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.geometry import Point, point_segment_distance

if TYPE_CHECKING:
    from collections.abc import Sequence

    from traffic_analysis.features.counting.domain.models import CountingLineDef


class ScaleField:
    """Échelle px/m locale, échantillonnée sur les lignes calibrées.

    Immuable et sans état : construit une fois par session, interrogé à chaque
    déplacement observé.
    """

    __slots__ = ("_global", "_samples")

    def __init__(
        self,
        lines: Sequence[CountingLineDef],
        global_px_per_meter: float | None = None,
    ) -> None:
        # Une ligne non calibrée n'échantillonne rien : elle est absente d'ici,
        # elle ne « vote » pas pour une échelle qu'elle ne connaît pas.
        self._samples: tuple[tuple[CountingLineDef, float], ...] = tuple(
            (line, scale) for line in lines if (scale := line.px_per_meter()) is not None
        )
        self._global = (
            global_px_per_meter
            if global_px_per_meter is not None and global_px_per_meter > 0.0
            else None
        )

    @property
    def is_calibrated(self) -> bool:
        """Au moins une ligne porte-t-elle une longueur réelle ?"""
        return bool(self._samples)

    def px_per_meter_at(self, point: Point) -> float | None:
        """Échelle à cet endroit, ou `None` si rien ne permet de la connaître.

        L'ordre est délibéré : une mesure locale l'emporte toujours sur l'échelle
        globale, qui n'est qu'un repli. L'inverse ferait qu'ajouter une
        calibration précise ne changerait rien tant que le curseur global est posé.
        """
        if not self._samples:
            return self._global

        nearest, scale = min(
            self._samples,
            key=lambda sample: point_segment_distance(point, sample[0].a, sample[0].b),
        )
        del nearest
        return scale

    def metres_between(self, start: Point, end: Point, travelled_px: float) -> float | None:
        """Convertit un déplacement en mètres, à l'échelle du **milieu du trajet**.

        Le milieu et non l'une des extrémités : sur un segment qui change de
        profondeur, c'est le point le plus représentatif des deux, et il ne
        privilégie aucun sens de circulation. Un véhicule qui descend vers la
        caméra et un autre qui s'en éloigne obtiennent ainsi la même échelle sur
        le même bout de route.
        """
        midpoint = Point((start.x + end.x) / 2.0, (start.y + end.y) / 2.0)
        scale = self.px_per_meter_at(midpoint)
        if scale is None or scale <= 0.0:
            return None
        return travelled_px / scale
