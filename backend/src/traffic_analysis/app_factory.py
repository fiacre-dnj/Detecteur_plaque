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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from traffic_analysis import __version__
from traffic_analysis.api.router import api_router
from traffic_analysis.container import build_container
from traffic_analysis.core.db.migrations import run_migrations
from traffic_analysis.core.error_handlers import register_error_handlers
from traffic_analysis.core.logging import configure_logging, get_logger
from traffic_analysis.core.middleware.access_log import AccessLogMiddleware
from traffic_analysis.core.middleware.body_size_limit import BodySizeLimitMiddleware
from traffic_analysis.core.middleware.request_id import HEADER_NAME, RequestIdMiddleware
from traffic_analysis.core.middleware.security_headers import SecurityHeadersMiddleware
from traffic_analysis.core.openapi import custom_openapi
from traffic_analysis.core.settings import Settings, get_settings

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.core.clock import Clock
    from traffic_analysis.features.benchmark.application.ports import InferenceProbe
    from traffic_analysis.features.counting.application.ports import (
        DetectionTrackingEngine,
        PlateDetector,
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
    """
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, production=settings.is_production)
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

    background: set[asyncio.Task[None]] = set()
    cleanup = asyncio.create_task(_cleanup_loop(app), name="cleanup")
    background.add(cleanup)
    cleanup.add_done_callback(background.discard)

    logger.info(
        "service démarré",
        version=__version__,
        environment=settings.env,
        docs=settings.docs_enabled,
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


async def _cleanup_loop(app: FastAPI) -> None:
    """Purge périodique des jobs terminaux périmés.

    Réveil toutes les 60 s plutôt qu'un déclenchement à chaque requête : la purge
    doit avoir lieu même sur un service inactif, où les artefacts s'accumulent
    justement le plus longtemps.
    """
    container = app.state.container
    settings = container.settings
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_S)
        try:
            await container.job_manager.purge_expired(settings.job_ttl_minutes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("purge en échec", error=str(exc))
