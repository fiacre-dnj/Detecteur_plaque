"""Schémas d'entrée et de sortie des presets.

**Les lignes et les zones réutilisent `LineSchema`/`ZoneSchema` du comptage**, et ce
n'est pas de la paresse : un preset dont la géométrie serait validée plus
souplement que l'analyse produirait un enregistrement acceptable au moment de la
sauvegarde et refusé au moment de lancer — le pire moment pour l'apprendre, puisque
la géométrie a alors été perdue depuis longtemps. Les mêmes bornes des deux côtés,
c'est la garantie qu'un preset enregistré est un preset lançable.

Import légal au regard du test d'architecture : `counting.application` est le contrat
publié de la feature `counting`, contrairement à son `domain` ou son `api`.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from traffic_analysis.core.schemas import CamelModel
from traffic_analysis.features.counting.application.request_schema import (
    LineSchema,
    PointSchema,
    ZoneSchema,
)
from traffic_analysis.features.presets.domain.records import (
    PresetDraft,
    PresetLine,
    PresetPoint,
    PresetZone,
)

__all__ = ["PresetDraftSchema", "PresetSchema"]

#: Borne haute du nombre de formes dans un preset. Généreuse — personne ne trace
#: cinquante lignes — mais elle empêche qu'un client fautif écrive plusieurs
#: mégaoctets de JSON dans une colonne texte.
MAX_SHAPES = 50


class PresetDraftSchema(CamelModel):
    """Ce que le client envoie pour créer ou remplacer un preset."""

    name: str = Field(min_length=1, max_length=120, examples=["Carrefour nord — 720p"])
    description: str = Field(default="", max_length=500)
    #: Les dimensions **de la vidéo sur laquelle la géométrie a été tracée**. Sans
    #: elles, recharger le preset sur une autre résolution placerait les lignes au
    #: mauvais endroit sans que rien ne l'indique.
    source_width: int = Field(gt=0, le=16384, examples=[1280])
    source_height: int = Field(gt=0, le=16384, examples=[720])
    mask_outside_zones: bool = False
    lines: list[LineSchema] = Field(default_factory=list, max_length=MAX_SHAPES)
    zones: list[ZoneSchema] = Field(default_factory=list, max_length=MAX_SHAPES)

    @model_validator(mode="after")
    def _not_empty(self) -> PresetDraftSchema:
        """Un preset sans forme ne sert à rien.

        Le refuser à l'enregistrement plutôt que de le laisser créer : un preset vide
        dans la liste est un piège, on le charge en croyant récupérer une géométrie
        et on obtient un canvas nu.
        """
        if not self.lines and not self.zones:
            raise ValueError(
                "Un preset doit contenir au moins une ligne ou une zone. "
                "Tracez votre géométrie avant de l'enregistrer."
            )
        return self

    @model_validator(mode="after")
    def _zones_exist(self) -> PresetDraftSchema:
        """Une ligne ne peut être rattachée qu'à une zone du **même** preset.

        Sinon le preset serait rechargeable mais irrecevable par l'analyse, qui
        refuse un `zoneId` inconnu. L'utilisateur verrait un 422 en cliquant sur
        « Lancer », plusieurs minutes après l'erreur réelle.
        """
        known = {zone.id for zone in self.zones}
        orphans = [
            line.id for line in self.lines if line.zone_id is not None and line.zone_id not in known
        ]
        if orphans:
            raise ValueError(
                f"Ces lignes sont rattachées à une zone absente du preset : {', '.join(orphans)}."
            )
        return self

    def to_domain(self) -> PresetDraft:
        return PresetDraft(
            name=self.name,
            description=self.description,
            source_width=self.source_width,
            source_height=self.source_height,
            mask_outside_zones=self.mask_outside_zones,
            lines=tuple(_line_to_domain(line) for line in self.lines),
            zones=tuple(_zone_to_domain(zone) for zone in self.zones),
        )


class PresetSchema(CamelModel):
    """Un preset tel que l'API le rend.

    `scaled` est le champ qui fait la différence entre une fonctionnalité utile et un
    piège. Vrai, il dit que les coordonnées rendues **ne sont pas** celles qui ont été
    enregistrées : elles ont été converties vers la résolution demandée. L'interface
    l'affiche, et l'utilisateur sait qu'il doit vérifier ses lignes.
    """

    id: str
    name: str
    description: str
    #: Résolution dans laquelle les coordonnées rendues sont exprimées — celle
    #: demandée si une mise à l'échelle a eu lieu, celle d'origine sinon.
    source_width: int
    source_height: int
    #: Résolution pour laquelle le preset a été **enregistré**, toujours.
    original_width: int
    original_height: int
    scaled: bool
    mask_outside_zones: bool
    lines: list[LineSchema]
    zones: list[ZoneSchema]
    created_at: str | None
    updated_at: str | None


def _line_to_domain(line: LineSchema) -> PresetLine:
    return PresetLine(
        id=line.id,
        name=line.name,
        color=line.color,
        zone_id=line.zone_id,
        a=_point_to_domain(line.a),
        b=_point_to_domain(line.b),
    )


def _zone_to_domain(zone: ZoneSchema) -> PresetZone:
    return PresetZone(
        id=zone.id,
        name=zone.name,
        color=zone.color,
        points=tuple(_point_to_domain(point) for point in zone.points),
    )


def _point_to_domain(point: PointSchema) -> PresetPoint:
    return PresetPoint(x=point.x, y=point.y)
