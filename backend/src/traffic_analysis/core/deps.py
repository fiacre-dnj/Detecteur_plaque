"""Dépendances FastAPI typées.

Une route testable est une route dont on peut remplacer les dépendances. Les
routes déclarent donc `SettingsDep` et non `request.app.state.container.settings` :
la première se substitue avec `app.dependency_overrides`, la seconde impose de
reconstruire une application entière pour changer une valeur.

**Les types annotés ici sont importés à l'exécution, jamais sous `TYPE_CHECKING`.**
FastAPI résout les annotations au moment où il construit la route : un type
seulement visible du vérificateur reste une chaîne, FastAPI ne sait pas
l'interpréter, et il prend alors le paramètre pour un champ de requête. Le
symptôme est un **422 sur une route qui n'a pourtant aucun paramètre**, avec le
nom de la dépendance dans `errors[]` — parfaitement déroutant.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from traffic_analysis.container import Container
from traffic_analysis.core.clock import Clock
from traffic_analysis.core.settings import Settings


def get_container(request: Request) -> Container:
    """Conteneur posé par `create_app()`.

    Unique fonction autorisée à toucher `app.state` : tout le reste part de
    celle-ci, ce qui laisse un seul endroit à modifier si le stockage change.
    """
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_settings_dep(container: ContainerDep) -> Settings:
    return container.settings


def get_clock(container: ContainerDep) -> Clock:
    return container.clock


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClockDep = Annotated[Clock, Depends(get_clock)]
