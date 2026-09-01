"""Une géométrie enregistrée, et sa résolution d'origine.

**Les dimensions source font partie du preset, et c'est la décision qui justifie ce
module.** Une géométrie n'a aucun sens sans la résolution pour laquelle elle a été
tracée : une ligne à `y = 400` traverse le milieu d'une image de 720 px de haut et
sort du cadre d'une image de 360. Stocker les coordonnées seules donnerait un preset
qui « ne marche pas » sur une autre vidéo, sans que rien n'explique pourquoi.

Avec les dimensions, le frontend peut proposer une mise à l'échelle proportionnelle
**en le disant** — et c'est cette phrase, plus que le calcul, qui rend la
fonctionnalité utilisable : l'utilisateur sait que ses lignes ont été déplacées et
peut les vérifier.

Module de domaine : aucun `pydantic`, aucun `sqlalchemy`. Des dataclasses et de
l'arithmétique.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from traffic_analysis.features.counting.application.dto import DirectionRole


@dataclass(frozen=True, slots=True)
class PresetPoint:
    """Un sommet, en pixels de la résolution d'origine du preset."""

    x: float
    y: float

    def scaled(self, factor_x: float, factor_y: float) -> PresetPoint:
        return PresetPoint(x=self.x * factor_x, y=self.y * factor_y)


@dataclass(frozen=True, slots=True)
class PresetLine:
    """Une ligne de comptage enregistrée.

    `color` et `name` sont conservés pour que le rechargement soit fidèle : un preset
    qui rendrait des lignes grises et anonymes obligerait à tout renommer.

    **Les quatre champs de sens sont conservés pour une raison plus forte que la
    fidélité : sans eux, un preset rechargé ne compte plus rien de lisible.** Depuis
    ADR 0021 le rôle d'un sens est obligatoire et **est** le libellé affiché ; c'est
    lui qui range un passage en entrée ou en sortie. Une ligne rechargée sans rôle
    retombe sur `neutral`, et tout l'aval se tait d'un coup — « Passages en entrée »
    affiche « — », les cartes par ligne perdent entrées et sorties, les comparatifs
    de Statistique rendent `null`, le registre n'a plus d'heure d'entrée ni de sortie
    et fait apparaître sa colonne « Hors rôle », la chronologie retombe sur son
    libellé « sens ↑ ». Les compteurs, eux, restent justes : c'est exactement la
    panne silencieuse que ce dépôt documente le plus.

    Le type vient de `counting.application.dto`, le contrat publié de la feature
    `counting` — jamais de son domaine. Il n'introduit aucune dépendance
    d'infrastructure : `DirectionRole` est un `Literal`, et la chaîne d'imports qui y
    mène est libre de `pydantic` comme du reste.
    """

    id: str
    name: str
    color: str
    zone_id: str | None
    a: PresetPoint
    b: PresetPoint
    #: Nom du sens A→B. `""` demande à l'interface de poser son défaut géométrique,
    #: recalculé quand la ligne bouge — même convention que `LineSchema`.
    positive_name: str = ""
    negative_name: str = ""
    positive_role: DirectionRole = "neutral"
    negative_role: DirectionRole = "neutral"
    #: Classes autorisées à franchir la ligne — `None` = aucune restriction.
    #:
    #: Conservée pour la même raison que les rôles : c'est une **règle**, pas une
    #: décoration. Un preset de voie de bus rechargé sans elle cesserait de signaler
    #: la moindre infraction, sans que rien ne l'explique.
    allowed_class_ids: tuple[int, ...] | None = None

    def scaled(self, factor_x: float, factor_y: float) -> PresetLine:
        return replace(
            self, a=self.a.scaled(factor_x, factor_y), b=self.b.scaled(factor_x, factor_y)
        )


@dataclass(frozen=True, slots=True)
class PresetZone:
    """Une zone enregistrée. L'ordre des sommets porte l'orientation du polygone."""

    id: str
    name: str
    color: str
    points: tuple[PresetPoint, ...]

    def scaled(self, factor_x: float, factor_y: float) -> PresetZone:
        return replace(
            self, points=tuple(point.scaled(factor_x, factor_y) for point in self.points)
        )


@dataclass(frozen=True, slots=True)
class Preset:
    """Une géométrie enregistrée, avec la résolution pour laquelle elle a été tracée."""

    id: str
    name: str
    description: str
    source_width: int
    source_height: int
    mask_outside_zones: bool
    lines: tuple[PresetLine, ...] = ()
    zones: tuple[PresetZone, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def scaled_to(self, width: int, height: int) -> Preset:
        """Le même preset, mis à l'échelle d'une autre résolution.

        **Deux facteurs indépendants et non un seul.** Passer d'un 16/9 à un 4/3 ne se
        fait pas par une homothétie : une ligne mise à l'échelle uniformément
        déborderait horizontalement ou laisserait une bande morte. Chaque axe suit sa
        propre dimension, ce qui déforme la géométrie — c'est le comportement correct,
        parce que l'image elle-même est déformée de la même façon.

        Rend l'objet inchangé quand les dimensions coïncident : cela évite de recréer
        des milliers de points pour rien, et rend le cas courant gratuit.
        """
        if width == self.source_width and height == self.source_height:
            return self
        if self.source_width <= 0 or self.source_height <= 0:
            # Un preset sans dimensions d'origine ne peut pas être mis à l'échelle.
            # Le rendre tel quel est plus honnête que de deviner un facteur.
            return self

        factor_x = width / self.source_width
        factor_y = height / self.source_height
        return replace(
            self,
            source_width=width,
            source_height=height,
            lines=tuple(line.scaled(factor_x, factor_y) for line in self.lines),
            zones=tuple(zone.scaled(factor_x, factor_y) for zone in self.zones),
        )

    def needs_scaling_for(self, width: int, height: int) -> bool:
        """Faut-il avertir l'utilisateur avant de charger ce preset ?

        La question que l'interface pose avant de toucher à quoi que ce soit. Vrai
        dès qu'une dimension diffère : un écart d'un seul pixel déplace déjà les
        lignes, et prétendre que « c'est la même chose » serait faux.
        """
        return width != self.source_width or height != self.source_height


@dataclass(frozen=True, slots=True)
class PresetDraft:
    """Ce qu'un appelant fournit pour créer ou mettre à jour un preset.

    Distinct de `Preset` parce que l'identifiant et les horodatages sont décidés par
    le service, jamais par le client : accepter un `id` fourni laisserait écraser un
    preset existant par un `POST`, ce qui n'est pas ce que `POST` veut dire.
    """

    name: str
    description: str
    source_width: int
    source_height: int
    mask_outside_zones: bool
    lines: tuple[PresetLine, ...] = field(default_factory=tuple)
    zones: tuple[PresetZone, ...] = field(default_factory=tuple)
