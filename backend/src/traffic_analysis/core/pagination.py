"""Pagination générique, partagée par toutes les routes qui listent.

Une seule forme de page dans tout le contrat : le client écrit un composant de
pagination et le réutilise partout, au lieu d'en deviner la forme route par route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Query
from pydantic import Field

from traffic_analysis.core.schemas import CamelModel

DEFAULT_LIMIT = 50
# Borne haute : une page de dix mille lignes n'est utile à personne et fait
# tenir tout le résultat en mémoire côté serveur comme côté navigateur.
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class PageParams:
    """Fenêtre demandée, en `limit`/`offset`.

    Limit/offset plutôt qu'un curseur : l'historique est trié par date de création
    décroissante et se parcourt par pages numérotées, ce que l'interface affiche.
    Un curseur serait plus robuste sur un flux à insertion continue — ce n'est pas
    le cas ici.
    """

    limit: int = DEFAULT_LIMIT
    offset: int = 0


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Taille de page.")] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Décalage depuis le début.")] = 0,
) -> PageParams:
    """Dépendance FastAPI qui valide et construit la fenêtre."""
    return PageParams(limit=limit, offset=offset)


class Page[T](CamelModel):
    """Une page de résultats et de quoi en calculer les suivantes."""

    items: list[T] = Field(description="Les éléments de cette page.")
    total: int = Field(description="Nombre total d'éléments, tous filtres appliqués.")
    limit: int = Field(description="Taille de page demandée.")
    offset: int = Field(description="Décalage de cette page.")

    @classmethod
    def of(cls, items: list[T], total: int, params: PageParams) -> Page[T]:
        return cls(items=items, total=total, limit=params.limit, offset=params.offset)
