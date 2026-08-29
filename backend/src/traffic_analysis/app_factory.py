"""Fabrique de l'application FastAPI.

Une factory plutôt qu'une application construite à l'import : les tests
construisent une application isolée, avec son propre répertoire temporaire et ses
propres doublures, sans toucher à une variable globale. C'est ce qui permet à
plusieurs tests de coexister dans le même processus.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from traffic_analysis import __version__
from traffic_analysis.api.router import API_V1_PREFIX, api_router
from traffic_analysis.container import build_container
from traffic_analysis.core.db.migrations import run_migrations
from traffic_analysis.core.error_handlers import register_error_handlers
from traffic_analysis.core.logging import configure_logging, get_logger
from traffic_analysis.core.middleware.access_log import AccessLogMiddleware
from traffic_analysis.core.middleware.body_size_limit import BodySizeLimitMiddleware
from traffic_analysis.core.middleware.rate_limit import RateLimitMiddleware, Rule
from traffic_analysis.core.middleware.request_id import HEADER_NAME, RequestIdMiddleware
from traffic_analysis.core.middleware.security_headers import SecurityHeadersMiddleware
from traffic_analysis.core.openapi import custom_openapi
from traffic_analysis.core.settings import Settings, get_settings

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.container import Container
    from traffic_analysis.core.clock import Clock
    from traffic_analysis.features.benchmark.application.ports import InferenceProbe
    from traffic_analysis.features.counting.application.ports import (
        DetectionTrackingEngine,
        PlateDetector,
        PlateReader,
    )
    from traffic_analysis.features.jobs.application.ports import JobRepository

logger = get_logger("traffic_analysis.app")

# Réveil de la purge. Assez court pour qu'un TTL de quelques minutes soit
# respecté, assez long pour ne pas réveiller le processus sans arrêt.
CLEANUP_INTERVAL_S = 60.0

SUMMARY = "Comptage de véhicules par vision : détection, suivi, ré-identification, ANPR."

DESCRIPTION_MARKDOWN = """
Service d'analyse vidéo qui **compte des véhicules** : détection, suivi
multi-objets, ré-identification longue durée, franchissement de lignes, présence
en zone, et lecture de plaques en option.

## Le modèle mental

Deux modes, tous les deux côté serveur :

**Différé** — `POST /api/v1/jobs` dépose une vidéo, un flux SSE rapporte la
progression, `GET /api/v1/jobs/{id}/result` rend une timeline horodatée, les
événements et le registre des véhicules.

**Direct** — le WebSocket `/api/v1/realtime` reçoit des frames JPEG et renvoie un
résultat par frame.

Le navigateur ne calcule **jamais** de détection. En différé il rejoue la
timeline sur la vidéo locale ; en direct il capture des frames JPEG et affiche ce
qui revient.

## Deux conventions à connaître avant de lire un chiffre

**Le temps est du temps de scène.** Tout horodatage métier est
`frameIndex / fps × 1000` millisecondes sur la timeline du média, jamais l'heure
de l'horloge. Les débits, les vitesses et la ré-identification en dépendent.

**Le sens d'un franchissement est le signe du côté d'arrivée** par rapport à la
ligne orientée A→B : `+1` ou `-1`. Un aller-retour réel compte **une fois dans
chaque sens** ; une boîte qui tremble sur la ligne compte **une fois**.

## Un aller-retour complet

```bash
# 1. Déposer une vidéo avec sa configuration
curl -X POST http://127.0.0.1:8000/api/v1/jobs \\
  -F 'file=@carrefour.mp4' \\
  -F 'request={"modelId":"yolov8n","lines":[{"id":"l1","name":"Nord",
       "a":{"x":0,"y":700},"b":{"x":1920,"y":700}}]};type=application/json'
# → 202 {"jobId":"9f2c…","status":"queued"}

# 2. Suivre la progression
curl -N http://127.0.0.1:8000/api/v1/jobs/9f2c…/events

# 3. Récupérer le résultat (409 tant que le job n'est pas terminé)
curl --compressed http://127.0.0.1:8000/api/v1/jobs/9f2c…/result
```

## Erreurs

Toutes les erreurs sont des **Problem Details (RFC 9457)**, servies en
`application/problem+json`. Le champ `code` est stable et destiné aux machines ;
`detail` est un message français destiné aux humains ; `requestId` corrèle la
réponse aux journaux du serveur.

## Licence

Ce service utilise **Ultralytics**, sous licence **AGPL-3.0**. La licence se
propage à tout service qui l'expose sur un réseau.
"""

OPENAPI_TAGS = [
    {"name": "health", "description": "Vivacité, préparation, diagnostic du service."},
    {
        "name": "jobs",
        "description": (
            "Analyse différée d'un fichier : dépôt, progression (SSE), résultat, historique."
        ),
    },
    {
        "name": "models",
        "description": "Catalogue des détecteurs, état de résidence, préchargement.",
    },
    {
        "name": "benchmark",
        "description": (
            "Mesure des modèles **sur cette machine**, sur une image de référence "
            "unique : chauffe écartée, médiane et p95, seuils de la requête, "
            "libération après chaque mesure."
        ),
    },
    {
        "name": "presets",
        "description": (
            "Géométries de comptage enregistrées. Chaque preset porte **la résolution "
            "pour laquelle il a été tracé** : sans elle, le recharger sur une autre "
            "vidéo placerait les lignes au mauvais endroit sans aucune erreur."
        ),
    },
    {
        "name": "realtime",
        "description": (
            "Comptage en direct sur un flux de frames JPEG (WebSocket). Le message "
            "`ready` renvoie les dimensions **réellement reçues** : c'est le filet "
            "contre une géométrie mal mise à l'échelle."
        ),
    },
]


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    engine: DetectionTrackingEngine | None = None,
    plate_detector: PlateDetector | None = None,
    plate_reader: PlateReader | None = None,
    job_repository: JobRepository | None = None,
    benchmark_probe: InferenceProbe | None = None,
) -> FastAPI:
    """Construit une application prête à servir.

    Les paramètres nommés sont les points de substitution des tests. Ils sont
    explicites plutôt que découverts : lire la signature suffit pour savoir ce
    qu'un test peut remplacer.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)

    app = FastAPI(
        title="Traffic Analysis API",
        summary=SUMMARY,
        description=DESCRIPTION_MARKDOWN,
        version=__version__,
        openapi_tags=OPENAPI_TAGS,
        license_info={
            "name": "AGPL-3.0",
            "url": "https://www.gnu.org/licenses/agpl-3.0.html",
        },
        docs_url="/api/docs" if resolved.docs_enabled else None,
        redoc_url="/api/redoc" if resolved.docs_enabled else None,
        openapi_url="/api/openapi.json" if resolved.docs_enabled else None,
        swagger_ui_parameters={
            "docExpansion": "none",  # quarante routes dépliées est illisible
            "defaultModelsExpandDepth": 2,
            "displayRequestDuration": True,
            "filter": True,
            "persistAuthorization": True,
            "tryItOutEnabled": True,
            "syntaxHighlight.theme": "obsidian",
        },
        lifespan=_lifespan,
    )

    app.state.container = build_container(
        resolved,
        clock=clock,
        engine=engine,
        plate_detector=plate_detector,
        plate_reader=plate_reader,
        job_repository=job_repository,
        benchmark_probe=benchmark_probe,
    )

    _add_middlewares(app, resolved)
    register_error_handlers(app)
    app.include_router(api_router)

    if resolved.static_dir is not None:
        _mount_static(app, resolved.static_dir)

    # `app.openapi` est remplacée plutôt qu'appelée : FastAPI l'invoque
    # lui-même, et lui rendre un schéma déjà enrichi évite de dupliquer la
    # personnalisation à chaque point d'entrée de documentation.
    app.openapi = lambda: custom_openapi(app)  # type: ignore[method-assign]

    return app


def _mount_static(app: FastAPI, static_dir: Path) -> None:
    """Sert le build du frontend depuis le backend, en production.

    Un seul origin : aucun CORS à ouvrir pour l'usage normal, et le SSE comme le
    WebSocket traversent sans réglage.

    `html=True` active le repli sur `index.html`, indispensable pour une SPA à
    routage côté client — sans lui, rafraîchir `/historique` rendrait un 404.
    Le montage est **après** le routeur d'API, donc `/api/**` gagne toujours.
    """
    from fastapi.staticfiles import StaticFiles

    if not static_dir.is_dir():
        logger.warning("TRAFFIC_STATIC_DIR introuvable — rien n'est servi", path=str(static_dir))
        return
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def _add_middlewares(app: FastAPI, settings: Settings) -> None:
    """Pile de middlewares — **l'ordre compte, et il n'est pas intuitif**.

    Starlette exécute les middlewares dans l'ordre inverse de leur ajout pour la
    réponse : le **premier ajouté est le plus externe**.

    Deux positions sont des décisions, pas des préférences :

    - **`RequestIdMiddleware` est le plus externe.** Tout ce qui se journalise
      ensuite doit pouvoir citer l'identifiant, y compris un journal d'accès qui
      rapporte une exception.
    - **CORS est le plus interne.** S'il est trop externe, une exception non gérée
      sort *sans* en-têtes CORS et le navigateur annonce « erreur CORS » à la
      place de la vraie erreur — des heures perdues garanties (piège 43 de
      prompt/13). En étant interne, il voit aussi les réponses d'erreur.

    - **La limite de corps est en amont de tout traitement.** Refuser 800 Mo
      après les avoir lus ne protège de rien.
    - **La limite de débit est juste au-dessus** — donc plus externe. Un client
      qui dépasse son quota est refusé avant même que le corps ne soit examiné :
      c'est tout l'intérêt, puisque le coût d'un dépôt est dans son écriture. Elle
      reste sous les en-têtes de sécurité et le journal d'accès, pour qu'un 429
      porte les mêmes en-têtes que le reste et apparaisse dans les journaux.
    """
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, production=settings.is_production)
    app.add_middleware(RateLimitMiddleware, rules=_rate_limit_rules(settings))
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes)
    # GZip ne compresse pas les réponses en streaming, donc le SSE lui échappe —
    # ce qui est indispensable : un flux compressé est un flux tamponné, et la
    # barre de progression paraîtrait figée.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", HEADER_NAME, "If-None-Match", "Accept"],
        # Sans `expose_headers`, le JavaScript ne voit pas ces en-têtes même
        # quand le serveur les envoie : le nom du CSV téléchargé et
        # l'identifiant de corrélation d'une erreur seraient perdus.
        expose_headers=[HEADER_NAME, "Content-Disposition", "X-Total-Count", "Retry-After", "ETag"],
        # 600 s évite un préflight par requête. Pas 86 400 : un changement de
        # politique resterait en cache une journée entière.
        max_age=600,
    )


def _rate_limit_rules(settings: Settings) -> list[Rule]:
    """Les limites de débit, de la plus large à la plus stricte.

    Trois routes ont leur propre limite parce que leur coût n'a rien à voir avec
    celui d'un `GET /health` :

    - **`POST /jobs`** écrit plusieurs centaines de mégaoctets sur le disque
      *avant* que la borne de concurrence n'entre en jeu. Le sémaphore protège le
      GPU ; il ne protège pas le volume, et un client qui dépose cent vidéos en
      rafale le remplit sans jamais lancer deux analyses simultanées.
    - **`POST /benchmark`** mesure jusqu'à vingt modèles et les télécharge au
      besoin : c'est l'opération la plus coûteuse du service.
    - **le handshake WebSocket** n'est vu par aucun autre garde-fou — le
      middleware CORS ne voit jamais passer un handshake.

    La limite **globale**, elle, exempte les lectures d'un job précis
    (`GET /jobs/{id}...`) — voir ADR 0027. Mesuré : rouvrir une seule analyse
    archivée déclenche une vingtaine de requêtes en quelques secondes, dont une
    quinzaine rien que pour la vidéo, que le navigateur charge par plages. Sans
    l'exemption, l'action même que l'historique promet — revoir un résultat —
    épuisait le quota prévu pour l'ingestion, et laissait le studio bloqué sur un
    écran vide sans le moindre message. L'exemption ne porte que sur `GET` :
    déposer, annuler, suspendre ou reprendre un job restent comptés.

    Une limite à `0` est **omise** plutôt que posée à zéro : une règle à zéro
    refuserait tout, ce qui est l'inverse de « désactivée ».
    """
    rules: list[Rule] = []
    if settings.rate_limit_per_minute > 0:
        rules.append(
            Rule(
                settings.rate_limit_per_minute,
                60.0,
                exempt_get_prefixes=(f"{API_V1_PREFIX}/jobs/",),
            )
        )
    if settings.rate_limit_jobs_per_minute > 0:
        rules.append(
            Rule(
                settings.rate_limit_jobs_per_minute,
                60.0,
                prefixes=(f"{API_V1_PREFIX}/jobs",),
                # `POST` seul : lister l'historique ou sonder la progression sont
                # des lectures bon marché, et les brider à dix par minute
                # casserait le sondage de l'interface (toutes les 3 s).
                methods=("POST",),
            )
        )
    if settings.rate_limit_benchmark_per_hour > 0:
        rules.append(
            Rule(
                settings.rate_limit_benchmark_per_hour,
                3600.0,
                prefixes=(f"{API_V1_PREFIX}/benchmark",),
                methods=("POST",),
            )
        )
    if settings.rate_limit_realtime_per_minute > 0:
        rules.append(
            Rule(
                settings.rate_limit_realtime_per_minute,
                60.0,
                prefixes=(f"{API_V1_PREFIX}/realtime",),
            )
        )
    return rules


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Démarrage et arrêt du service.

    Les tâches de fond sont créées ici et **gardées dans un ensemble** : une tâche
    asyncio sans référence forte peut être ramassée par le ramasse-miettes en
    pleine exécution, et la purge s'arrêterait alors sans le moindre message.
    """
    container = app.state.container
    settings = container.settings

    loop = asyncio.get_running_loop()
    container.job_manager.bind_loop(loop)
    if container.benchmark_service is not None:
        # Le sémaphore « un seul benchmark à la fois » doit être créé **dans** la
        # boucle qui l'utilisera : construit ailleurs, il s'attacherait à une autre
        # boucle et bloquerait pour de bon au premier run.
        container.benchmark_service.bind_loop(loop)

    # Migrations au démarrage en développement et en test uniquement. **Jamais
    # en production** : une commande de déploiement explicite évite que trois
    # répliques migrent la même base en parallèle (prompt/07 §5).
    if container.db_engine is not None and not settings.is_production:
        await run_migrations(container.db_engine)

    # **Avant le préchauffage**, qui est la première inférence du processus : un
    # pool de threads déjà dimensionné se redimensionne mal. `0` ne fait rien, donc
    # aucun coût pour qui n'a pas posé le réglage — l'import de torch lui-même est
    # évité dans ce cas, ce qui préserve les tests à moteur factice.
    #
    # La garde porte sur **les deux** réglages. N'appeler que sur
    # `inference_threads` laisserait `TRAFFIC_OPENCV_THREADS` annoncé et sans effet
    # dès qu'il est posé seul — le pire état d'un réglage, et celui que ce dépôt a
    # déjà payé plusieurs fois.
    if settings.inference_threads > 0 or settings.opencv_threads > 0:
        await anyio.to_thread.run_sync(
            container.model_registry.apply_thread_budget,
            settings.inference_threads,
            settings.opencv_threads,
        )

    # Même fenêtre et même raison que le budget de threads : avant la première
    # inférence. Sans GPU, l'appel rend la main sans importer torch — le moteur
    # factice des tests n'est donc pas touché.
    #
    # **Désactivé par défaut depuis ADR 0033**, et sous condition pour la même raison
    # que le budget de threads : qui n'a pas posé le réglage ne doit pas payer un
    # import de torch. L'autotune réétalonne cuDNN à chaque **nouvelle forme**
    # d'entrée, et le détecteur de plaques lui en présente une par recadrage — d'où des
    # pauses d'une seconde qui pesaient 73 % de son étage.
    if settings.inference_cudnn_autotune:
        await anyio.to_thread.run_sync(container.model_registry.enable_cudnn_autotune)

    background: set[asyncio.Task[None]] = set()
    cleanup = asyncio.create_task(_cleanup_loop(app), name="cleanup")
    background.add(cleanup)
    cleanup.add_done_callback(background.discard)

    if settings.warmup:
        warm = asyncio.create_task(_warmup(container), name="warmup")
        background.add(warm)
        warm.add_done_callback(background.discard)

    logger.info(
        "service démarré",
        version=__version__,
        environment=settings.env,
        docs=settings.docs_enabled,
        # Les deux chemins **résolus**, dès la première ligne du journal.
        #
        # Ils ne dépendent plus du répertoire de lancement, mais les voir reste
        # nécessaire : un « modèle de plaques absent » avec le bon fichier au bon
        # endroit se diagnostique en une seconde quand le journal dit où le
        # service a regardé, et en une heure sinon.
        weights_dir=str(settings.weights_dir),
        data_dir=str(settings.data_dir),
    )
    try:
        yield
    finally:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup
        # Demander l'arrêt plutôt qu'annuler : un `track()` interrompu de force
        # laisserait le bail de son modèle non rendu. La même raison vaut pour une
        # inférence de benchmark en cours.
        await container.job_manager.shutdown()
        if container.benchmark_service is not None:
            await container.benchmark_service.shutdown()
        await container.dispose()
        logger.info("service arrêté")


async def _warmup(container: Container) -> None:
    """Préchauffe le modèle par défaut, **s'il est déjà téléchargé**.

    Le premier appel d'un modèle inclut son chargement et sa fusion de couches :
    sans préchauffage, il se lit comme un blocage de plusieurs dizaines de secondes
    au milieu de la première analyse (piège 31 de prompt/13).

    Trois précautions, et chacune évite une panne concrète :

    - **Rien si le poids est absent.** Préchauffer déclencherait un téléchargement
      de 137 Mo au démarrage : le conteneur paraîtrait bloqué et son healthcheck
      échouerait. Le service ne dépend jamais du réseau pour démarrer.
    - **En tâche de fond**, jamais dans le `lifespan` lui-même. Le chargement d'un
      modèle prend plusieurs secondes ; le faire bloquer le démarrage retarderait
      d'autant la première réponse à `/health/live`.
    - **Dans un thread worker.** Charger un modèle et lancer une inférence sont des
      opérations bloquantes ; les exécuter sur la boucle asyncio la figerait, et
      tout le service avec (invariant 11).

    Ce réglage a été **déclaré et jamais lu** pendant tout le projet : `warmup: bool
    = True` existait, était documenté dans `.env.example`, et aucune ligne ne le
    consultait. La première analyse réelle payait donc toujours le chargement.
    """
    # L'auto-test des plaques d'abord, et non après : c'est le moins coûteux des deux
    # (un modèle nano contre le détecteur de véhicules) et c'est celui dont le verdict
    # est attendu par `/health`. Il ne lève jamais — `probe()` avale tout.
    await _probe_plates(container)
    # Puis l'encodeur de ressemblance, pour la même raison et au même coût : une
    # inférence sur une image noire. Après les plaques parce que son absence est le cas
    # courant — la recherche par image est une option installée à part.
    await _probe_reid(container)

    registry = container.model_registry
    if registry is None:
        return

    model_id = container.settings.default_model_id
    if not registry.is_downloaded(model_id):
        logger.info("préchauffage ignoré : poids absent", model_id=model_id)
        return

    try:
        await anyio.to_thread.run_sync(registry.warmup, model_id)
    except Exception as exc:  # pragma: no cover — `warmup` avale déjà ses erreurs
        logger.warning("préchauffage en échec", model_id=model_id, error=str(exc))


async def _probe_plates(container: Container) -> None:
    """Vérifie que le détecteur de plaques se charge **vraiment**, une fois.

    `plateAvailable` ne teste qu'une présence de fichier, délibérément : l'interface
    interroge `/health` en permanence et charger un modèle à chaque appel serait
    absurde. Mais ce projet a payé trois fois le mode de panne que cette économie
    laisse passer — un `.env` commenté, un dictionnaire d'OCR décalé d'un cran, un
    suffixe de fichier qui trompe le choix de backend d'Ultralytics. Chaque fois : un
    drapeau vert, aucune exception, et zéro plaque à chaque image.

    Une inférence sur une image noire au démarrage tranche entre les deux, et le
    verdict remonte dans `/health` sous `plateLoadable`.
    """
    service = container.model_service
    if service is None:
        return
    verdict = await service.probe_plates()
    if verdict is False:
        # `error` et non `warning` : les poids sont là, l'utilisateur croit donc que
        # l'ANPR marche. C'est le seul état de ce démarrage qui mérite d'être criard.
        logger.error("auto-test du détecteur de plaques en échec — ANPR muette")


async def _probe_reid(container: Container) -> None:
    """Vérifie que l'encodeur de ressemblance se charge **vraiment**, une fois.

    Même raison d'être que `_probe_plates`, et même mode de panne visé : `reidAvailable`
    ne teste qu'une présence de fichier, et le suffixe `.onnx` fait partie du contrat —
    `onnxruntime` ne lit que cela. Un `.pt` renommé, un fichier tronqué, un graphe dont
    la sortie n'a pas 512 dimensions : tout cela passe `available` et ne rend jamais un
    vecteur.
    """
    service = container.model_service
    if service is None:
        return
    verdict = await service.probe_reid()
    if verdict is False:
        # `error` et non `warning`, même arbitrage que pour les plaques : les poids sont
        # là, donc l'utilisateur croit que la recherche par image marche.
        logger.error(
            "auto-test de l'encodeur de ressemblance en échec — recherche par image muette"
        )


async def _cleanup_loop(app: FastAPI) -> None:
    """Purge périodique — **deux échéances distinctes**, et c'est délibéré.

    Réveil toutes les 60 s plutôt qu'un déclenchement à chaque requête : la purge
    doit avoir lieu même sur un service inactif, où les artefacts s'accumulent
    justement le plus longtemps.

    Les vidéos déposées partent **avant** les jobs, à `input_ttl_minutes` contre
    `job_ttl_minutes` (une heure contre vingt-quatre par défaut). La raison n'est pas
    la place disque : une scène de trafic contient des plaques réelles et des
    visages, alors qu'un résultat ne contient que des boîtes et des compteurs. La
    donnée sensible doit avoir la durée de vie la plus courte que l'usage permet —
    et l'usage n'en a plus besoin dès que le résultat existe.
    """
    container = app.state.container
    settings = container.settings
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_S)
        try:
            # Les vidéos d'abord : si la purge des jobs échoue, les images
            # sensibles auront quand même disparu.
            await container.job_manager.purge_expired_inputs(settings.input_ttl_minutes)
            await container.job_manager.purge_expired(settings.job_ttl_minutes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("purge en échec", error=str(exc))
