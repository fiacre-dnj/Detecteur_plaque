"""Schémas d'entrée et de sortie de la feature `jobs`.

Le miroir TypeScript de `frontend/src/shared/api/contracts.ts` reprend ces noms
**exactement** : c'est un contrat, pas une coïncidence.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from traffic_analysis.core.schemas import CamelModel

# Les schémas d'entrée vivent dans `counting/application` : ils sont partagés avec le
# mode temps réel, et le test d'architecture interdit à une feature de fouiller dans
# l'`api` d'une autre. Réexportés ici parce que c'est de cette route qu'ils sont
# documentés dans OpenAPI.
from traffic_analysis.features.counting.application.request_schema import (
    AnalysisRequestSchema,
    LineSchema,
    PointSchema,
    ZoneSchema,
)

__all__ = [
    "AnalysisRequestSchema",
    "JobCreatedSchema",
    "JobDetailSchema",
    "JobSchema",
    "LineSchema",
    "PointSchema",
    "ZoneSchema",
]


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
    # `paused` est un état **vivant** : le worker existe toujours et attend entre
    # deux images. Il n'entre donc pas dans les statuts terminaux du client.
    status: Literal["queued", "running", "paused", "done", "error", "cancelled"]
    progress: float = Field(ge=0.0, le=1.0)
    processed_frames: int
    total_frames: int
    processing_fps: float
    error: str | None
    # Le code **stable** de l'échec, à côté du message français.
    #
    # C'est ce qui permet à l'interface de proposer l'action correspondante —
    # « précharger « X » puis relancer » sur `model_unavailable` — sans faire de
    # correspondance sur du texte, qui casserait à la première reformulation.
    error_code: str | None = None
    #: Le modèle se charge — **état de passage, jamais persisté**.
    #:
    #: Pas un `JobStatus` : en faire un toucherait la machine à états,
    #: `is_terminal`, les libellés et tous leurs tests, pour un état qui ne dure
    #: que le temps d'un chargement. Il n'est vrai que sur l'unique trame publiée
    #: avant le passage en « en cours », et c'est cette trame qui permet à
    #: l'interface d'écrire « Préparation : chargement du modèle » au lieu de
    #: « 0 / 0 images · 0.0 img/s ».
    preparing: bool = False
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
