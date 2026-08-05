"""Composition racine : le seul endroit qui sait comment assembler le service.

Le conteneur est construit une fois au démarrage et posé sur `app.state`. Les
routes ne le lisent **jamais** directement : elles passent par les dépendances
typées de `core/deps.py` et `features/*/api/deps.py`, ce qui permet à un test de
remplacer une pièce avec `app.dependency_overrides`.

Ce n'est pas un Service Locator : personne ne *cherche* une dépendance ici. Le
conteneur est un enregistrement de valeurs déjà construites, injectées vers le bas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from traffic_analysis.core.clock import Clock, SystemClock
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.jobs.application.job_manager import JobManager
from traffic_analysis.features.jobs.application.progress_hub import ProgressHub
from traffic_analysis.features.jobs.infrastructure.memory_repository import InMemoryJobRepository
from traffic_analysis.features.jobs.infrastructure.result_store import FileResultStore

if TYPE_CHECKING:
    from traffic_analysis.core.settings import Settings
    from traffic_analysis.features.counting.application.ports import (
        DetectionTrackingEngine,
        PlateDetector,
    )
    from traffic_analysis.features.jobs.application.ports import JobRepository


@dataclass(slots=True)
class Container:
    """Les dépendances vivantes du service."""

    settings: Settings
    clock: Clock
    analysis_service: AnalysisService
    job_repository: JobRepository
    result_store: FileResultStore
    progress_hub: ProgressHub
    job_manager: JobManager


def build_container(
    settings: Settings,
    *,
    clock: Clock | None = None,
    engine: DetectionTrackingEngine | None = None,
    plate_detector: PlateDetector | None = None,
    job_repository: JobRepository | None = None,
) -> Container:
    """Assemble le conteneur.

    Les paramètres nommés optionnels sont les points de substitution des tests :
    ils reçoivent une valeur réelle en production, une doublure en test. C'est
    volontairement explicite — pas de découverte automatique, pas de registre
    global.

    `engine` est obligatoire **à l'usage** mais optionnel ici : le service doit
    pouvoir démarrer et répondre à `/health` même si le moteur de vision n'est pas
    encore disponible, plutôt que de refuser de booter.
    """
    resolved_clock = clock or SystemClock()
    resolved_engine = engine or _missing_engine()

    analysis_service = AnalysisService(resolved_engine, plate_detector)
    result_store = FileResultStore(settings.data_dir)
    repository = job_repository or InMemoryJobRepository(resolved_clock)
    hub = ProgressHub()

    return Container(
        settings=settings,
        clock=resolved_clock,
        analysis_service=analysis_service,
        job_repository=repository,
        result_store=result_store,
        progress_hub=hub,
        job_manager=JobManager(
            repository=repository,
            result_store=result_store,
            analysis=analysis_service,
            hub=hub,
            clock=resolved_clock,
            max_concurrent_jobs=settings.max_concurrent_jobs,
        ),
    )


def _missing_engine() -> DetectionTrackingEngine:
    """Moteur qui échoue à l'usage, avec un message qui dit quoi faire.

    Préférable à un `None` qui produirait une `AttributeError` opaque au milieu
    d'une analyse : ici l'erreur arrive au premier usage réel, elle est explicite,
    et `/health` reste joignable en attendant.
    """
    from traffic_analysis.features.counting.infrastructure.unavailable_engine import (
        UnavailableEngine,
    )

    return UnavailableEngine()
