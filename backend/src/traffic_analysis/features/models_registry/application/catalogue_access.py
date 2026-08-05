"""Contrat publié du catalogue, pour les autres features.

`jobs` a besoin de valider un `modelId` ; `benchmark` a besoin de la liste des
identifiants. Ni l'un ni l'autre n'a de raison de fouiller dans
`models_registry/domain/` — ce module est leur porte d'entrée, et le test
d'architecture l'exige.
"""

from __future__ import annotations

from traffic_analysis.features.models_registry.domain.catalogue import find, known_ids


def is_known_model(model_id: str) -> bool:
    return find(model_id) is not None


def known_model_ids() -> tuple[str, ...]:
    return known_ids()
