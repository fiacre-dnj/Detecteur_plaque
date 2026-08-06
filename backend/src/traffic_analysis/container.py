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
from traffic_analysis.core.db.engine import create_engine, create_session_factory
from traffic_analysis.features.benchmark.application.service import BenchmarkService
from traffic_analysis.features.benchmark.infrastructure.reference_image import VideoFrameProvider
from traffic_analysis.features.benchmark.infrastructure.sqlalchemy_repository import (
    SqlAlchemyBenchmarkRepository,
)
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.jobs.application.job_manager import JobManager
from traffic_analysis.features.jobs.application.progress_hub import ProgressHub
from traffic_analysis.features.jobs.infrastructure.result_store import FileResultStore
from traffic_analysis.features.jobs.infrastructure.sqlalchemy_repository import (
    SqlAlchemyJobRepository,
)
from traffic_analysis.features.models_registry.application.model_service import ModelService
from traffic_analysis.features.models_registry.infrastructure.inference_probe import (
    RegistryInferenceProbe,
)
from traffic_analysis.features.models_registry.infrastructure.plate_detector import (
    OnnxPlateDetector,
)
from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    UltralyticsEngine,
)
from traffic_analysis.features.presets.application.service import PresetService
from traffic_analysis.features.presets.infrastructure.sqlalchemy_repository import (
    SqlAlchemyPresetRepository,
)
from traffic_analysis.features.realtime.application.session_service import RealtimeSessionService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from traffic_analysis.core.settings import Settings
    from traffic_analysis.features.benchmark.application.ports import InferenceProbe
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
    model_service: ModelService | None = None
    model_registry: ModelRegistry | None = None
    # `None` quand la persistance est désactivée : un run de benchmark est écrit
    # ligne par ligne et rechargé à l'ouverture de la page, donc il n'a aucun sens
    # sans base. La route répond alors 503 avec la raison.
    benchmark_service: BenchmarkService | None = None
    # `None` quand la persistance est désactivée. Un preset stocké en mémoire
    # disparaîtrait au redémarrage, ce qui est le contraire de ce qu'un
    # enregistrement promet : mieux vaut un 503 explicite.
    preset_service: PresetService | None = None
    # Toujours présent : le temps réel ne dépend d'aucune persistance, seulement
    # d'un moteur de suivi.
    realtime_service: RealtimeSessionService | None = None
    # `None` quand la persistance est désactivée (base injoignable, dépôt en
    # mémoire injecté par un test). Le service reste alors utilisable : seules
    # les routes d'agrégats répondent une erreur explicite.
    db_engine: AsyncEngine | None = None

    async def dispose(self) -> None:
        """Ferme les ressources longues à l'arrêt du service.

        Sans `dispose()`, les connexions SQLite restent ouvertes et le fichier
        `-wal` n'est pas replié : la base grossit et un test suivant qui ouvre le
        même fichier temporaire échoue sous Windows, où un fichier ouvert ne peut
        pas être supprimé.
        """
        if self.db_engine is not None:
            await self.db_engine.dispose()


def build_container(
    settings: Settings,
    *,
    clock: Clock | None = None,
    engine: DetectionTrackingEngine | None = None,
    plate_detector: PlateDetector | None = None,
    job_repository: JobRepository | None = None,
    benchmark_probe: InferenceProbe | None = None,
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

    # Le registre existe toujours : il sert le catalogue et l'état mémoire, même
    # quand un test injecte un moteur factice à sa place pour l'inférence.
    registry = ModelRegistry(
        settings.weights_dir,
        max_loaded=settings.max_loaded_models,
        device=settings.device,
        half=settings.half,
    )
    resolved_engine = engine or UltralyticsEngine(registry)
    resolved_plates = plate_detector or OnnxPlateDetector(
        settings.resolved_plate_model_path, settings.plate_confidence
    )
    model_service = ModelService(
        registry,
        default_model_id=settings.default_model_id,
        plate_detector=resolved_plates,
    )

    analysis_service = AnalysisService(resolved_engine, resolved_plates)
    realtime_service = RealtimeSessionService(
        resolved_engine, max_sessions=settings.max_realtime_sessions
    )
    result_store = FileResultStore(settings.data_dir)
    hub = ProgressHub()

    db_engine: AsyncEngine | None = None
    benchmark_service: BenchmarkService | None = None
    preset_service: PresetService | None = None
    if job_repository is not None:
        repository = job_repository
    else:
        # La base est la source de vérité de l'état : un job doit survivre à un
        # redémarrage. Le dépôt en mémoire ne sert qu'aux tests qui l'injectent
        # explicitement, où la persistance n'est pas le sujet.
        db_engine = create_engine(settings)
        session_factory = create_session_factory(db_engine)
        repository = SqlAlchemyJobRepository(session_factory)
        benchmark_service = BenchmarkService(
            SqlAlchemyBenchmarkRepository(session_factory),
            # La sonde passe par le **registre**, pas par le moteur d'analyse : le
            # benchmark mesure une inférence sur une image fixe, sans suivi. Un
            # tracker garderait un état entre les appels, et la deuxième mesure ne
            # serait plus comparable à la première.
            benchmark_probe or RegistryInferenceProbe(registry),
            VideoFrameProvider(settings.data_dir),
            hub,
        )
        preset_service = PresetService(SqlAlchemyPresetRepository(session_factory))

    return Container(
        settings=settings,
        clock=resolved_clock,
        analysis_service=analysis_service,
        job_repository=repository,
        result_store=result_store,
        progress_hub=hub,
        model_service=model_service,
        model_registry=registry,
        benchmark_service=benchmark_service,
        preset_service=preset_service,
        realtime_service=realtime_service,
        db_engine=db_engine,
        job_manager=JobManager(
            repository=repository,
            result_store=result_store,
            analysis=analysis_service,
            hub=hub,
            clock=resolved_clock,
            max_concurrent_jobs=settings.max_concurrent_jobs,
        ),
    )
