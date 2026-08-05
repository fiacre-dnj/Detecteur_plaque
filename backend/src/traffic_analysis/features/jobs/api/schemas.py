"""Schémas d'entrée et de sortie de la feature `jobs`.

Le miroir TypeScript de `frontend/src/shared/api/contracts.ts` reprend ces noms
**exactement** : c'est un contrat, pas une coïncidence.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from traffic_analysis.core.schemas import CamelModel
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    CountingLineDef,
    Point,
    ZoneDef,
)
from traffic_analysis.features.models_registry.application.catalogue_access import (
    is_known_model,
    known_model_ids,
)


class PointSchema(CamelModel):
    x: float
    y: float

    def to_domain(self) -> Point:
        return Point(self.x, self.y)


class LineSchema(CamelModel):
    """Une ligne de comptage telle que le client la dessine."""

    id: str = Field(min_length=1, max_length=64, examples=["l1"])
    name: str = Field(default="", max_length=120, examples=["Voie nord"])
    # La couleur appartient à l'interface : elle est acceptée pour que le client
    # puisse rejouer une configuration à l'identique, et n'est **jamais**
    # interprétée par le serveur.
    color: str = Field(default="", max_length=32)
    zone_id: str | None = Field(default=None, max_length=64)
    a: PointSchema
    b: PointSchema

    def to_domain(self) -> CountingLineDef:
        return CountingLineDef(
            id=self.id,
            name=self.name,
            a=self.a.to_domain(),
            b=self.b.to_domain(),
            zone_id=self.zone_id,
        )


class ZoneSchema(CamelModel):
    id: str = Field(min_length=1, max_length=64, examples=["z1"])
    name: str = Field(default="", max_length=120)
    color: str = Field(default="", max_length=32)
    points: list[PointSchema] = Field(min_length=3)

    def to_domain(self) -> ZoneDef:
        return ZoneDef(
            id=self.id, name=self.name, points=tuple(point.to_domain() for point in self.points)
        )


class AnalysisRequestSchema(CamelModel):
    """Configuration d'une analyse. Envoyée en JSON dans le champ `request`."""

    model_id: str = Field(examples=["yolov8n"])
    confidence_threshold: float = Field(0.35, ge=0.01, le=0.99)
    iou_threshold: float = Field(0.45, ge=0.05, le=0.95)
    min_hits: int = Field(2, ge=1, le=10)
    max_lost_ms: float = Field(2500, ge=200, le=15000)
    reid_min_similarity: float = Field(0.80, ge=0.50, le=0.99)
    mask_outside_zones: bool = False
    frame_stride: int = Field(1, ge=1, le=10)
    detect_plates: bool = False
    plate_confidence: float | None = Field(None, ge=0.05, le=0.95)
    pixels_per_meter: float | None = Field(
        None,
        gt=0,
        description="Échelle de la scène. Sans elle, les vitesses restent en px/s.",
        examples=[12.5],
    )
    lines: list[LineSchema] = Field(default_factory=list)
    zones: list[ZoneSchema] = Field(default_factory=list)

    @field_validator("model_id")
    @classmethod
    def _known_model(cls, value: str) -> str:
        """Refuser ici plutôt qu'au chargement.

        Un identifiant inconnu accepté produirait un job qui échoue trente
        secondes plus tard, sans que l'utilisateur sache lequel de ses réglages
        est en cause. Le message liste les identifiants valides.
        """
        if not is_known_model(value):
            msg = (
                f"Le modèle « {value} » n'existe pas au catalogue. "
                f"Modèles valides : {', '.join(known_model_ids())}."
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _check_geometry(self) -> AnalysisRequestSchema:
        """Quatre refus, chacun évitant une analyse dont le résultat serait vide.

        Refuser tôt et clairement vaut mieux que rendre des compteurs à zéro : un
        écran de zéros ressemble à une panne, et l'utilisateur cherche le bug au
        mauvais endroit.
        """
        line_ids = [line.id for line in self.lines]
        zone_ids = [zone.id for zone in self.zones]

        if len(set(line_ids)) != len(line_ids):
            msg = "Deux lignes portent le même identifiant."
            raise ValueError(msg)
        if len(set(zone_ids)) != len(zone_ids):
            msg = "Deux zones portent le même identifiant."
            raise ValueError(msg)

        known_zones = set(zone_ids)
        for line in self.lines:
            if line.zone_id is not None and line.zone_id not in known_zones:
                msg = (
                    f"La ligne « {line.id} » référence la zone « {line.zone_id} », "
                    "qui n'existe pas."
                )
                raise ValueError(msg)
            if line.a.x == line.b.x and line.a.y == line.b.y:
                msg = (
                    f"La ligne « {line.id} » est de longueur nulle : "
                    "elle ne compterait jamais rien."
                )
                raise ValueError(msg)

        if not self.lines and not self.zones:
            msg = (
                "Une analyse sans ligne ni zone ne produirait aucun compteur. "
                "Ajoutez au moins une ligne de comptage."
            )
            raise ValueError(msg)
        return self

    def to_config(self) -> AnalysisJobConfig:
        return AnalysisJobConfig(
            model_id=self.model_id,
            confidence_threshold=self.confidence_threshold,
            iou_threshold=self.iou_threshold,
            min_hits=self.min_hits,
            mask_outside_zones=self.mask_outside_zones,
            frame_stride=self.frame_stride,
            detect_plates=self.detect_plates,
            plate_confidence=self.plate_confidence,
            pixels_per_meter=self.pixels_per_meter,
            reid_min_similarity=self.reid_min_similarity,
            max_lost_ms=self.max_lost_ms,
            lines=tuple(line.to_domain() for line in self.lines),
            zones=tuple(zone.to_domain() for zone in self.zones),
        )


class JobCreatedSchema(CamelModel):
    """Réponse à un dépôt : le job est accepté, l'analyse est asynchrone."""

    job_id: str = Field(examples=["9f2c4a1b8d3e4f5a"])
    status: Literal["queued"] = "queued"


class JobSchema(CamelModel):
    """État courant d'un job. Même forme que les événements SSE.

    **Volontairement sans `configJson`.** Ce schéma est celui de chaque trame de
    progression SSE : y ajouter la configuration complète — géométrie comprise —
    la ferait voyager plusieurs fois par seconde pendant toute l'analyse, pour une
    valeur qui ne change jamais. La configuration vit dans `JobDetailSchema`.
    """

    job_id: str
    status: Literal["queued", "running", "done", "error", "cancelled"]
    progress: float = Field(ge=0.0, le=1.0)
    processed_frames: int
    total_frames: int
    processing_fps: float
    error: str | None
    model_id: str
    file_name: str
    created_at: str
    finished_at: str | None


class JobDetailSchema(JobSchema):
    """Un job **et la configuration qui l'a produit**.

    `configJson` est la requête telle qu'elle a été reçue. Elle existe pour deux
    gestes de l'interface, et sans elle aucun des deux n'est possible :

    - **ouvrir** une analyse de l'historique en rechargeant sa géométrie dans le
      studio — sinon les lignes tracées seraient perdues et les chiffres du
      résultat ne correspondraient à aucun tracé visible ;
    - **relancer** avec les mêmes réglages, ce qui crée un **nouveau** job et ne
      mute jamais l'ancien : un job muté perdrait ses chiffres d'origine, et on ne
      pourrait plus comparer « avant » et « après » un changement de réglage.
    """

    config_json: dict[str, Any] = Field(
        default_factory=dict,
        description="La requête d'analyse telle qu'elle a été reçue.",
    )
