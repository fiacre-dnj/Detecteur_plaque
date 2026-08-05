"""Schémas d'entrée et de sortie du benchmark.

Le miroir TypeScript de `frontend/src/shared/api/contracts.ts` reprend ces noms
**exactement** : c'est un contrat, pas une coïncidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from traffic_analysis.core.schemas import CamelModel
from traffic_analysis.features.benchmark.application.service import DEFAULT_FRAMES
from traffic_analysis.features.models_registry.application.catalogue_access import (
    is_known_model,
    known_model_ids,
)

# Borne haute du nombre de mesures. Vingt modèles × 20 mesures × plusieurs
# centaines de millisecondes sur CPU dépassent le quart d'heure : au-delà, la
# précision gagnée ne vaut plus l'attente.
MAX_FRAMES = 20


class BenchmarkRequestSchema(CamelModel):
    """Ce que le client demande à mesurer.

    Tous les champs sont optionnels : `POST /benchmark` avec un corps vide mesure
    tout le catalogue sur l'échantillon embarqué, avec les seuils par défaut. C'est
    le geste le plus courant, et il ne doit pas exiger de remplir un formulaire.
    """

    model_ids: list[str] | None = Field(
        default=None,
        description="Modèles à mesurer. Absent ou vide = tout le catalogue.",
        examples=[["yolov8n", "yolo11n"]],
    )
    frames: int = Field(
        DEFAULT_FRAMES,
        ge=1,
        le=MAX_FRAMES,
        description=(
            "Nombre de mesures retenues par modèle, **run de chauffe non compris** "
            "— celui-ci est toujours exécuté puis écarté."
        ),
    )
    image_source: Literal["sample", "job"] = Field(
        "sample",
        description=(
            "Image de référence : l'échantillon embarqué, ou une frame extraite de "
            "la vidéo d'un job existant. La **même** image sert à tous les modèles.\n\n"
            "L'échantillon est une scène **synthétique** : les temps qu'il produit "
            "sont valables, mais il ne contient aucun véhicule, donc `detections` y "
            "vaut 0 pour tous les modèles. Pour comparer aussi les détections, "
            "mesurer sur une vraie scène avec `imageSource=job`."
        ),
    )
    job_id: str | None = Field(
        default=None,
        max_length=32,
        description="Job dont extraire la frame. Obligatoire si `imageSource=job`.",
    )
    # Les seuils **de la requête** : c'est la règle 4 du protocole. Mesurer avec
    # ceux du catalogue ferait que la colonne « détections » contredirait ce que
    # l'utilisateur voit à l'écran avec ses propres réglages.
    confidence_threshold: float = Field(0.35, ge=0.01, le=0.99)
    iou_threshold: float = Field(0.45, ge=0.05, le=0.95)

    @field_validator("model_ids")
    @classmethod
    def _known_models(cls, value: list[str] | None) -> list[str] | None:
        """Refuse ici plutôt qu'au chargement, et **sans dédoublonner en silence**.

        Un identifiant inconnu accepté produirait un run qui échoue au milieu, sans
        que l'utilisateur sache lequel de ses choix est en cause. Le doublon est
        refusé plutôt que corrigé : mesurer deux fois le même modèle est presque
        toujours une faute de frappe, et le corriger en douce cacherait l'erreur.
        """
        if value is None:
            return None
        unknown = [model_id for model_id in value if not is_known_model(model_id)]
        if unknown:
            msg = (
                f"Modèles inconnus au catalogue : {', '.join(unknown)}. "
                f"Modèles valides : {', '.join(known_model_ids())}."
            )
            raise ValueError(msg)
        if len(set(value)) != len(value):
            msg = "La liste de modèles contient des doublons."
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _job_required_for_job_source(self) -> BenchmarkRequestSchema:
        """`imageSource=job` sans `jobId` ne désigne aucune image.

        Refusé au lieu d'un repli sur l'échantillon : l'utilisateur croirait
        mesurer sur sa propre scène, et comparerait des chiffres qui ne portent pas
        sur ce qu'il pense.
        """
        if self.image_source == "job" and not self.job_id:
            msg = "« imageSource=job » exige un « jobId »."
            raise ValueError(msg)
        return self


class BenchmarkCreatedSchema(CamelModel):
    """Réponse à un dépôt : le run est accepté, la mesure est asynchrone."""

    run_id: str = Field(examples=["7d1e0c4a9b2f4e6d"])
    status: Literal["queued"] = "queued"


class BenchmarkEntrySchema(CamelModel):
    """Une ligne du tableau — un modèle mesuré, ou un modèle en échec."""

    model_id: str
    label: str
    tier: str
    load_ms: float = Field(
        description="Durée du chargement. **0 si le modèle était déjà résident.**"
    )
    median_ms: float = Field(description="Médiane des mesures retenues — la valeur à lire.")
    p95_ms: float = Field(description="Centile 95 : ce que la médiane a écarté reste visible ici.")
    min_ms: float
    max_ms: float
    fps: float = Field(description="Cadence déduite de la médiane, jamais mesurée à part.")
    preprocess_ms: float | None = Field(
        description="`null` si le moteur ne l'expose pas — et non 0, qui se lirait « instantané »."
    )
    postprocess_ms: float | None
    detections: int = Field(description="Détections retenues avec les seuils **de la requête**.")
    frames: int = Field(description="Mesures retenues, chauffe exclue.")
    was_loaded: bool = Field(description="Le modèle était déjà résident avant la mesure.")
    released: bool = Field(
        description=(
            "L'instance a été libérée après sa mesure. `false` signifie qu'elle "
            "était occupée par une analyse en cours — le registre refuse alors de "
            "la décharger, ce qui est le comportement voulu."
        )
    )
    error: str | None = Field(description="Message français si ce modèle n'a pas pu être mesuré.")


class BenchmarkRunSchema(CamelModel):
    """Un run complet, avec le contexte matériel qui lui donne un sens."""

    run_id: str
    status: Literal["queued", "running", "done", "error", "cancelled"]
    progress: float = Field(ge=0.0, le=1.0)
    completed: int
    total: int
    error: str | None
    device: str = Field(description="Device de la mesure : « cpu », « 0 »…")
    half: bool
    ultralytics_version: str
    frames: int
    image_source: Literal["sample", "job"]
    image_hash: str = Field(
        description=(
            "`sha256` de l'image de référence. Deux runs ne sont comparables que "
            "s'ils portent le même hash."
        )
    )
    image_width: int
    image_height: int
    job_id: str | None
    confidence_threshold: float
    iou_threshold: float
    fastest_model_id: str | None = Field(
        description="Modèle à la médiane la plus basse, parmi les lignes réussies."
    )
    entries: list[BenchmarkEntrySchema]
