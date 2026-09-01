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
from traffic_analysis.features.counting.application.dto import (
    PlateDetectOptions,
    PlateGeometry,
    PlateOcrOptions,
)
from traffic_analysis.features.counting.infrastructure.onnx_vehicle_embedder import (
    OnnxVehicleEmbedder,
)
from traffic_analysis.features.counting.infrastructure.opencv_snapshot_encoder import (
    OpenCvSnapshotEncoder,
)
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
    UltralyticsPlateDetector,
)
from traffic_analysis.features.models_registry.infrastructure.plate_reader import OnnxPlateReader
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
        PlateReader,
        VehicleEmbedder,
        VehicleSnapshotEncoder,
    )
    from traffic_analysis.features.jobs.application.ports import JobRepository


@dataclass(frozen=True, slots=True)
class CountingStack:
    """Le moteur, les deux étages de plaques, et le service qui les enchaîne.

    Elle existe pour que **le banc mesure ce que le service exécute**.
    `scripts/pipeline_bench.py` a besoin d'une `AnalysisService` réelle, ANPR et OCR
    comprises, mais pas d'une base de données ni d'un `JobManager` : sans ce point
    d'assemblage partagé, il recopierait le câblage de `build_container` — une
    quinzaine de réglages — et mesurerait au premier oubli un pipeline que personne ne
    fait tourner. C'est le mode de panne qu'ADR 0013 signale à propos du fichier de
    tracker : un rapport qui annonce autre chose que ce qui a tourné est pire qu'un
    rapport sans cette ligne.
    """

    engine: DetectionTrackingEngine
    plate_detector: PlateDetector
    plate_reader: PlateReader
    #: L'encodeur d'apparence. Présent même sans poids installé : c'est lui qui répond
    #: `available: False`, et `scripts/reid_bench.py` a besoin de l'objet pour mesurer.
    vehicle_embedder: VehicleEmbedder
    analysis: AnalysisService


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
    plate_reader: PlateReader | None = None,
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
    stack = build_counting_stack(
        settings,
        registry,
        engine=engine,
        plate_detector=plate_detector,
        plate_reader=plate_reader,
    )
    resolved_engine = stack.engine
    resolved_plates = stack.plate_detector
    resolved_plate_reader = stack.plate_reader
    analysis_service = stack.analysis

    model_service = ModelService(
        registry,
        default_model_id=settings.default_model_id,
        plate_detector=resolved_plates,
        plate_reader=resolved_plate_reader,
        vehicle_embedder=stack.vehicle_embedder,
    )
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
            # `ModelService` satisfait le port `ModelPreparer` par sa seule méthode
            # `prepare`. C'est lui qui fait échouer un job **avant** qu'il prétende
            # travailler, quand le poids est absent et intéléchargeable.
            #
            # **Seulement avec le moteur réel.** Un test qui injecte un moteur
            # factice n'utilise jamais le registre pour inférer : préparer y
            # déclencherait un vrai téléchargement Ultralytics de plusieurs
            # mégaoctets pour un modèle que rien n'appellera. C'est précisément ce
            # que l'architecture existe pour éviter — la CI tourne sans GPU, sans
            # poids et sans ultralytics.
            preparer=model_service if engine is None else None,
            max_concurrent_jobs=settings.max_concurrent_jobs,
            preview_interval_ms=settings.preview_interval_ms,
            preview_interval_paced_ms=settings.preview_interval_paced_ms,
            preview_vehicles_interval_ms=settings.preview_vehicles_interval_ms,
        ),
    )


def build_counting_stack(
    settings: Settings,
    registry: ModelRegistry,
    *,
    engine: DetectionTrackingEngine | None = None,
    plate_detector: PlateDetector | None = None,
    plate_reader: PlateReader | None = None,
    snapshot_encoder: VehicleSnapshotEncoder | None = None,
    vehicle_embedder: VehicleEmbedder | None = None,
) -> CountingStack:
    """Assemble le moteur, les deux étages de plaques et l'`AnalysisService`.

    Extrait de `build_container` **sans rien changer à son câblage** : c'est le seul
    endroit qui sait comment une analyse est composée, et il doit rester le seul —
    voir la docstring de `CountingStack` pour ce qu'un second exemplaire coûterait.

    Les paramètres nommés restent les points de substitution des tests, exactement
    comme dans `build_container`.
    """
    resolved_engine = engine or UltralyticsEngine(
        registry,
        gmc_method=settings.tracker_gmc,
        imgsz=settings.inference_imgsz,
        batch=settings.inference_batch,
        prefetch_batches=settings.inference_prefetch_batches,
    )
    resolved_plates = plate_detector or UltralyticsPlateDetector(
        settings.resolved_plate_model_path,
        settings.plate_confidence,
        iou=settings.plate_iou,
        mosaic_side=settings.plate_mosaic_side,
        net_size=settings.plate_net_size,
        geometry=PlateGeometry(max_per_vehicle=settings.plate_max_per_vehicle),
        # Le registre est l'autorité sur le matériel, pour le détecteur de plaques
        # comme pour celui des véhicules : une seule décision par machine, prise à
        # un seul endroit, testée une seule fois. Des appelables et non des valeurs
        # — le registre ne sonde le GPU qu'au premier besoin (ADR 0015).
        device_provider=registry.device,
        half_provider=registry.half,
    )
    resolved_plate_reader = plate_reader or OnnxPlateReader(
        settings.resolved_plate_ocr_model_path,
        settings.resolved_plate_ocr_charset_path,
        min_score=settings.plate_ocr_min_text_score,
        intra_op_threads=settings.resolved_plate_ocr_intra_op_threads,
        variants=settings.plate_ocr_variants,
        dynamic_width=settings.plate_ocr_dynamic_width,
        # `plate_ocr_variants` reste le commutateur maître : couper les variantes doit
        # tout couper, sinon « désactivé pour comparer » ne compare pas ce qu'on croit.
        left_insets=settings.plate_ocr_left_insets if settings.plate_ocr_variants else (),
    )
    resolved_embedder = vehicle_embedder or OnnxVehicleEmbedder(
        settings.resolved_reid_model_path,
        min_vehicle_width_px=settings.reid_min_vehicle_width_px,
        min_sharpness=settings.reid_min_sharpness,
        intra_op_threads=settings.resolved_reid_intra_op_threads,
    )
    analysis_service = AnalysisService(
        resolved_engine,
        resolved_plates,
        resolved_plate_reader,
        # Les seuils d'OCR viennent des réglages et aucun de la requête : ce sont des
        # arbitrages de déploiement — combien de cœurs, quelle cadence — que
        # l'utilisateur d'une analyse n'a pas à connaître. `plate_confidence` fait
        # exception et voyage bien par requête, parce qu'il répond à une question que
        # seul l'utilisateur peut trancher devant sa vidéo : « trop de rectangles, ou
        # pas assez ». Il descend jusqu'à l'adaptateur en argument de `detect_many`,
        # ce qui lève l'impasse où ADR 0007 le laissait mort.
        PlateOcrOptions(
            every_n_frames=settings.plate_ocr_every_n_frames,
            skip_above_iou=settings.plate_ocr_skip_iou,
            min_width_px=float(settings.plate_ocr_min_width_px),
            min_sharpness=settings.plate_ocr_min_sharpness,
            quality_improvement=settings.plate_ocr_quality_improvement,
        ),
        # L'étranglement du détecteur — **le vrai goulot**, 73 % du budget par image
        # sur une vue de circulation réelle (ADR 0032), à 17,5 ms par recadrage sur
        # GPU. Le « 702 ms contre 66 » qui vivait ici datait d'une mesure CPU
        # d'avant ADR 0015 et ADR 0030, et ADR 0030 l'a déclaré faux. Les trois champs
        # existaient et aucun n'était atteignable : seul `every_n_frames` était
        # passé, et il valait forcément celui de l'OCR. Le repli conserve ce
        # comportement (`resolved_plate_detect_every_n_frames`), mais il devient
        # un repli et non une fatalité.
        PlateDetectOptions(
            every_n_frames=settings.resolved_plate_detect_every_n_frames,
            min_vehicle_width_px=settings.plate_detect_min_vehicle_width_px,
            max_anchor_age=settings.plate_detect_max_anchor_age,
            max_consecutive_misses=settings.plate_detect_max_consecutive_misses,
            max_per_frame=settings.plate_detect_max_per_frame,
            readable_gate=settings.plate_detect_readable_gate,
            readable_min_samples=settings.plate_detect_readable_min_samples,
            readable_retry_every=settings.plate_detect_readable_retry_every,
        ),
        # La capture des véhicules. Aucun seuil de **confiance** : celui de
        # déclenchement est déjà celui de l'utilisateur — une plaque n'existe
        # qu'au-dessus de « Confiance plaques », un texte qu'au-dessus de « Confiance
        # lecture ». Un troisième seuil serait un réglage de plus, capable de
        # contredire les deux autres. Ses causes, elles, s'allument **ici** : voir
        # les quatre réglages passés plus bas.
        snapshot_encoder or OpenCvSnapshotEncoder(),
        # La recherche par image. Ses deux planchers sont des réglages de
        # **déploiement** et non de requête : ils arbitrent du coût d'inférence contre
        # une chance de ressemblance sur un véhicule lointain, c'est-à-dire un choix de
        # machine et de cadrage de caméra. Le seuil qui décide de ce qui s'affiche, lui,
        # vit côté client — voir ADR 0048 pour pourquoi il ne peut pas vivre ici.
        resolved_embedder,
        settings.reid_min_similarity,
        settings.reid_appearance_improvement,
        settings.reid_max_per_frame,
        # Les deux causes de capture d'ADR 0051 et leurs bornes. Le service les tient
        # éteintes par défaut, pour que tout appelant qui ne demande rien garde le
        # régime d'ADR 0042 : c'est ici, et seulement ici, qu'elles s'allument.
        snapshot_on_plate_box=settings.snapshot_on_plate_box,
        snapshot_on_appearance=settings.snapshot_on_appearance,
        snapshot_width_improvement=settings.snapshot_width_improvement,
        max_snapshots=settings.snapshot_max_vehicles,
    )
    return CountingStack(
        engine=resolved_engine,
        plate_detector=resolved_plates,
        plate_reader=resolved_plate_reader,
        vehicle_embedder=resolved_embedder,
        analysis=analysis_service,
    )
