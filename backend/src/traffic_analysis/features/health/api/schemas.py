"""Schéma de diagnostic du service.

Il grandira avec le registre de modèles (`device`, `ultralyticsVersion`,
`loadedModels`, `plateAvailable`). Les champs sont ajoutés quand ils peuvent être
renseignés honnêtement : un `device: "unknown"` obligerait l'interface à une
branche conditionnelle pour un champ qui ne veut rien dire.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from traffic_analysis.core.schemas import CamelModel


class HealthSchema(CamelModel):
    """Ce que le badge d'état du frontend affiche en permanence.

    Le badge est visible sur tous les écrans : ces champs doivent tous être
    calculables **sans charger de modèle** ni interroger la base, sinon consulter
    l'état du service coûterait plus cher que de l'utiliser.
    """

    status: Literal["ok"] = Field(description="Le service répond.")
    version: str = Field(description="Version du service (SemVer).", examples=["0.1.0"])
    environment: str = Field(
        description="Environnement d'exécution déclaré.",
        examples=["development"],
    )
    device: str = Field(
        description="Device d'inférence résolu : « cpu », « 0 », « cuda:0 »…",
        examples=["cpu"],
    )
    half: bool = Field(
        description=(
            "Inférence en demi-précision. Toujours faux hors GPU : "
            "en fp16 sur CPU, l'inférence ralentit."
        ),
    )
    ultralytics_version: str = Field(
        description="Version d'Ultralytics, ou « indisponible ».", examples=["8.4.115"]
    )
    loaded_models: list[str] = Field(
        description="Modèles actuellement résidents en mémoire.", examples=[["yolov8n"]]
    )
    max_loaded_models: int = Field(description="Plafond de résidence mémoire.")
    plate_available: bool = Field(
        description=(
            "Le modèle de plaques est présent. Faux ⇒ l'option ANPR est "
            "désactivée dans l'interface, et le service fonctionne normalement."
        )
    )
    default_model_id: str = Field(description="Modèle proposé par défaut.")
