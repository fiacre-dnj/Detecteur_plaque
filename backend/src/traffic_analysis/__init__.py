"""Service d'analyse vidéo : comptage de véhicules par détection, suivi et
ré-identification.

Toute l'inférence vit ici — le navigateur ne calcule aucune détection
(voir docs/adr/0003-analyse-100-pourcent-backend.md).
"""

from __future__ import annotations

# Source unique de la version : lue par FastAPI pour OpenAPI, exposée par
# /api/v1/health, et affichée dans l'interface. Un second endroit divergerait.
__version__ = "0.1.0"

__all__ = ["__version__"]
