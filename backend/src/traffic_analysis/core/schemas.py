"""Schémas de base du contrat HTTP.

Une seule règle traverse tout le contrat : **camelCase sur le fil, snake_case en
Python**. Le frontend porte un miroir TypeScript exact de ces noms — c'est un
contrat, pas une coïncidence (voir prompt/05 §10).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base de tous les schémas exposés par l'API.

    `populate_by_name=True` permet de construire l'objet côté Python avec les
    noms snake_case tout en le sérialisant en camelCase.

    `protected_namespaces=()` est nécessaire : `model_id` est un nom **métier**
    dans ce projet, et pydantic réserve par défaut le préfixe `model_`. Sans
    cela, chaque schéma portant `model_id` émet un avertissement à l'import.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        protected_namespaces=(),
        from_attributes=True,
    )


class ProblemDetails(CamelModel):
    """Corps d'erreur RFC 9457, servi en `application/problem+json`.

    Les noms de champs de la RFC sont déjà en minuscules sans séparateur : seuls
    `requestId` et les extensions passent par le générateur d'alias.
    """

    type: str = Field(
        default="about:blank",
        description="URI identifiant le type de problème.",
        examples=["about:blank"],
    )
    title: str = Field(description="Résumé stable du type de problème.")
    status: int = Field(description="Code de statut HTTP.", examples=[422])
    detail: str = Field(description="Explication de cette occurrence précise, en français.")
    code: str = Field(
        description="Code machine stable, sur lequel un client peut brancher.",
        examples=["validation_error"],
    )
    instance: str | None = Field(
        default=None,
        description="Chemin de la requête qui a produit l'erreur.",
        examples=["/api/v1/jobs/9f2c"],
    )
    request_id: str | None = Field(
        default=None,
        description="Identifiant de corrélation, à citer dans un rapport d'incident.",
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        protected_namespaces=(),
        json_schema_extra={
            "examples": [
                {
                    "type": "about:blank",
                    "title": "Requête non traitable",
                    "status": 422,
                    "detail": "Le modèle « yolo42x » n'existe pas au catalogue.",
                    "code": "unknown_model",
                    "instance": "/api/v1/jobs",
                    "requestId": "01JQ8Z3K7M4N5P6Q7R8S9T0V1W",
                }
            ]
        },
    )


class FieldError(CamelModel):
    """Un champ refusé et la raison de son refus."""

    field: str = Field(description="Chemin du champ, séparé par des points.")
    message: str = Field(description="Raison du refus, en français.")
    type: str = Field(description="Identifiant pydantic de la règle violée.")


class ValidationProblemDetails(ProblemDetails):
    """Problem Details enrichi du détail par champ pour une erreur de validation."""

    errors: list[FieldError] = Field(
        default_factory=list,
        description="Une entrée par champ refusé.",
    )


class LivenessSchema(CamelModel):
    """Réponse de `/health/live` — volontairement minimale.

    Une sonde de vivacité ne doit dépendre de rien : si elle interroge la base ou
    le catalogue, une base lente fait redémarrer un processus parfaitement sain.
    """

    status: Literal["ok"] = "ok"


class ReadinessSchema(CamelModel):
    """Réponse de `/health/ready` — dit si le service peut *travailler*."""

    status: Literal["ready", "degraded"]
    checks: dict[str, bool] = Field(
        description="Une entrée par dépendance vérifiée.",
        examples=[{"database": True, "catalogue": True}],
    )


ValidationProblemDetails.model_rebuild()
