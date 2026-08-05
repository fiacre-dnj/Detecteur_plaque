"""Composition racine : le seul endroit qui sait comment assembler le service.

Le conteneur est construit une fois au démarrage et posé sur `app.state`. Les
routes ne le lisent **jamais** directement : elles passent par les dépendances
typées de `core/deps.py`, ce qui permet à un test de remplacer une pièce avec
`app.dependency_overrides`.

Ce n'est pas un Service Locator : personne ne *cherche* une dépendance ici. Le
conteneur est un enregistrement de valeurs déjà construites, injectées vers le bas.

Il grandit lot par lot — `model_service`, `job_manager` et `benchmark_service`
apparaîtront quand ils existeront. Un champ déclaré avant son implémentation
serait une abstraction sans utilisateur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from traffic_analysis.core.clock import Clock, SystemClock

if TYPE_CHECKING:
    from traffic_analysis.core.settings import Settings


@dataclass(slots=True)
class Container:
    """Les dépendances vivantes du service."""

    settings: Settings
    clock: Clock


def build_container(settings: Settings, *, clock: Clock | None = None) -> Container:
    """Assemble le conteneur.

    Les paramètres nommés optionnels sont les points de substitution des tests :
    ils reçoivent une valeur réelle en production, une doublure en test. C'est
    volontairement explicite — pas de découverte automatique, pas de registre
    global.
    """
    return Container(
        settings=settings,
        clock=clock or SystemClock(),
    )
