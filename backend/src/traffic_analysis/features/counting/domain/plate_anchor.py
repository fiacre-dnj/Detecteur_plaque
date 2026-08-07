"""L'ancre de plaque — ce qui rend l'étranglement du détecteur invisible.

**L'objection levée.** `plate_policy` posait qu'on n'étrangle jamais le
détecteur, parce que ses boîtes sont dessinées à l'écran et que les produire une
image sur trois ferait clignoter des rectangles — un défaut que l'utilisateur lit
comme un défaut de détection. L'objection est exacte **tant qu'on se contente de
ne rien produire les images sautées**. Elle tombe si l'on produit à la place une
estimation continue.

**Pourquoi une ancre relative marche.** Une plaque est solidaire de son véhicule
dans le plan image : sur deux ou trois images consécutives, un véhicule subit une
translation et un changement d'échelle à peu près uniformes, et rien d'autre.
Mémoriser la plaque en coordonnées **relatives à la boîte du véhicule** suit donc
exactement ce mouvement. Une position absolue mémorisée, elle, décrocherait dès la
première image — c'est le véhicule qui bouge.

**Ce qu'une ancre n'est pas.** Ce n'est pas une mesure : c'est une extrapolation.
D'où la règle sans exception qui l'accompagne — **l'OCR ne lit jamais une boîte
reprojetée**. Faire voter une extrapolation fabriquerait de la confiance à partir
de rien, et le texte publié cesserait d'être un vote sur des observations. Le
`stale` du contrat existe pour que cette distinction survive jusqu'au client.

Module **pur** : aucun `cv2`, aucun `pydantic`, aucune horloge. L'âge se compte en
images analysées, comme partout ailleurs dans le domaine.
"""

from __future__ import annotations

from dataclasses import dataclass

from traffic_analysis.features.counting.domain.models import BoundingBox


@dataclass(frozen=True, slots=True)
class PlateAnchor:
    """Une plaque mémorisée **en fractions de la boîte de son véhicule**.

    `rx`/`ry` sont l'origine de la plaque en fraction de la largeur et de la
    hauteur du véhicule ; `rw`/`rh` ses dimensions dans les mêmes unités. Les
    quatre sont sans dimension, ce qui est exactement ce qui rend la reprojection
    insensible au déplacement et au grossissement du véhicule.
    """

    rx: float
    ry: float
    rw: float
    rh: float
    #: Le score de la **détection réelle** dont l'ancre est issue. Reproduit tel
    #: quel : abaisser le score d'une reprojection laisserait croire que le modèle
    #: hésite, alors qu'il n'a rien mesuré du tout. C'est `stale` qui porte
    #: l'information « ceci n'est pas une mesure », pas une confiance rabotée.
    score: float
    #: Nombre d'images analysées écoulées depuis la détection réelle. `0` sur
    #: l'image même de la mesure.
    age: int = 0

    def project(self, vehicle: BoundingBox) -> BoundingBox:
        """Reprojette l'ancre sur la boîte courante du véhicule."""
        return BoundingBox(
            x=vehicle.x + self.rx * vehicle.width,
            y=vehicle.y + self.ry * vehicle.height,
            width=self.rw * vehicle.width,
            height=self.rh * vehicle.height,
        )

    def aged(self) -> PlateAnchor:
        """L'ancre, une image analysée plus tard."""
        return PlateAnchor(self.rx, self.ry, self.rw, self.rh, self.score, self.age + 1)


def anchor_from(vehicle: BoundingBox, plate: BoundingBox, score: float) -> PlateAnchor | None:
    """Mémorise une plaque **mesurée** en coordonnées relatives à son véhicule.

    Rend `None` quand la mémorisation n'aurait pas de sens :

    - un véhicule de largeur ou de hauteur nulle ne définit aucun repère ;
    - une plaque hors de son véhicule vient d'un désalignement, et la reprojeter
      promènerait un rectangle à côté de la voiture pendant `max_anchor_age`
      images. Mieux vaut ne rien dessiner que dessiner faux.

    La borne est volontairement lâche (10 % de débordement toléré) : une boîte de
    véhicule est elle-même approximative, et refuser un dépassement d'un pixel
    perdrait des ancres parfaitement utiles.
    """
    if vehicle.width <= 0.0 or vehicle.height <= 0.0:
        return None
    if plate.width <= 0.0 or plate.height <= 0.0:
        return None

    rx = (plate.x - vehicle.x) / vehicle.width
    ry = (plate.y - vehicle.y) / vehicle.height
    rw = plate.width / vehicle.width
    rh = plate.height / vehicle.height

    tolerance = 0.1
    if not (-tolerance <= rx and -tolerance <= ry):
        return None
    if rx + rw > 1.0 + tolerance or ry + rh > 1.0 + tolerance:
        return None
    return PlateAnchor(rx=rx, ry=ry, rw=rw, rh=rh, score=score)
