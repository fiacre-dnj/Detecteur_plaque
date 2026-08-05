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
    """Ce que le badge d'état du frontend affiche en permanence."""

    status: Literal["ok"] = Field(description="Le service répond.")
    version: str = Field(description="Version du service (SemVer).", examples=["0.1.0"])
    environment: str = Field(
        description="Environnement d'exécution déclaré.",
        examples=["development"],
    )
