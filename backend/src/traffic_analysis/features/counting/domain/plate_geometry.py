"""Ce qu'une boîte doit vérifier pour être la plaque d'un véhicule donné.

**Pourquoi ce module est dans le domaine et pas dans l'adaptateur.** Le filtre
vivait dans `OnnxPlateDetector`, donc derrière `ultralytics`, donc **jamais
traversé par la CI** — qui tourne sans GPU, sans poids et sans ultralytics. La
conséquence était concrète : aucun test ne pouvait prouver qu'une boîte
« véhicule entier » n'atteint pas l'OCR, alors que c'est exactement le défaut qui
a motivé l'ADR 0008. Ici, il se vérifie sur des tuples, sans un seul pixel.

**Ce que le filtre a évité, mesuré.** Sur 538 détections de vraie circulation,
112 étaient la boîte du véhicule entier — un pare-chocs, une paire de phares, un
bloc de feux arrière — dont certaines à 0,87 de confiance, c'est-à-dire
au-dessus de tout seuil raisonnable. Aucun réglage de confiance ne les attrape ;
seule la géométrie les distingue. Les 426 boîtes retenues étaient toutes de
vraies plaques. La séparation est nette : une plaque occupe 11 à 25 % de la
largeur de son véhicule, une fausse détection 98 à 100 %.

**Un filtre ne peut que retirer des détections**, jamais en inventer : à modèle
inchangé, il ne peut donc pas dégrader le rappel des boîtes correctes. Chaque
borne est volontairement large — on écarte l'absurde, pas l'inhabituel.

Pur au sens du projet : aucun `cv2`, aucun `ultralytics`, aucun `pydantic`. Les
coordonnées sont celles du **recadrage du véhicule**, ce qui fait que le recadrage
vaut le véhicule et que les fractions se lisent directement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from traffic_analysis.features.counting.domain.models import BoundingBox

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class PlateGeometry:
    """Les bornes du filtre de plausibilité.

    Sans ce filtre, la sortie brute du modèle est publiée telle quelle : le
    `max_det` par défaut d'Ultralytics vaut 300, donc un seul véhicule peut porter
    des dizaines de rectangles à l'écran, et chacun d'eux part en OCR.
    """

    #: Une plaque est plus large que haute. En dessous de 1,1 c'est un logo, un
    #: phare ou un reflet. Les plaques de moto (~1,4:1) passent.
    min_aspect: float = 1.1
    #: Au-delà, c'est une bande de calandre ou un bandeau de concessionnaire.
    max_aspect: float = 9.0
    #: Fraction de la largeur du véhicule. Une plaque qui occupe plus de 90 % de la
    #: largeur du véhicule est le véhicule lui-même.
    max_relative_width: float = 0.9
    #: En dessous, la boîte est trop petite pour être une plaque de ce véhicule —
    #: typiquement un écusson.
    min_relative_width: float = 0.03
    #: Fraction de la hauteur du véhicule. Une plaque n'est jamais un demi-véhicule.
    max_relative_height: float = 0.5
    #: Le centre de la plaque, en fraction de la hauteur du véhicule depuis le haut.
    #: Écarte les reflets de pare-brise et les feux de toit ; 0,12 reste très
    #: permissif, y compris pour un plan plongeant sur un camion.
    #:
    #: **Gardé large délibérément** : le resserrer gagnerait un peu de précision et
    #: perdrait les motos et les camions vus en plongée. Un recadrage de la moitié
    #: basse du véhicule l'obligerait — c'est à mesurer, pas à adopter par défaut.
    min_vertical_centre: float = 0.12
    #: Combien de plaques au plus par véhicule. Un véhicule a **une** plaque
    #: visible ; en garder plusieurs multiplie les rectangles à l'écran et le coût
    #: d'OCR, et laisse le vote d'identité arbitrer entre deux lectures d'objets
    #: différents.
    max_per_vehicle: int = 1


def is_plausible(
    box: BoundingBox,
    crop_width: float,
    crop_height: float,
    geometry: PlateGeometry,
) -> bool:
    """La boîte peut-elle être la plaque du véhicule qui occupe ce recadrage ?

    `box` est en coordonnées du **recadrage**, donc le recadrage vaut le véhicule
    et les fractions se lisent directement. Comparer dans le repère de l'image
    complète obligerait à soustraire l'origine à chaque borne, c'est-à-dire à
    écrire deux fois le même changement de repère — et une seule des deux serait
    relue.
    """
    if box.width <= 0.0 or box.height <= 0.0 or crop_width <= 0.0 or crop_height <= 0.0:
        return False

    aspect = box.width / box.height
    if not geometry.min_aspect <= aspect <= geometry.max_aspect:
        return False
    if not (
        geometry.min_relative_width * crop_width
        <= box.width
        <= geometry.max_relative_width * crop_width
    ):
        return False
    if box.height > geometry.max_relative_height * crop_height:
        return False
    return (box.y + box.height / 2.0) / crop_height >= geometry.min_vertical_centre


def select_best(
    candidates: Sequence[tuple[BoundingBox, float]],
    geometry: PlateGeometry,
) -> tuple[tuple[BoundingBox, float], ...]:
    """Les `max_per_vehicle` meilleures candidates, la plus sûre d'abord.

    Le tri est **stable sur le score décroissant** : deux boîtes de score égal
    gardent leur ordre d'arrivée, donc deux exécutions du même clip retiennent la
    même plaque. Un tri instable ferait publier une plaque différente d'une
    relecture à l'autre, ce que l'invariant 4 existe pour empêcher.
    """
    ranked = sorted(candidates, key=lambda candidate: -candidate[1])
    return tuple(ranked[: geometry.max_per_vehicle])
