"""Routeur racine `/api/v1`.

Le préfixe `/api` n'est pas décoratif : c'est lui qui permet au proxy Vite de
distinguer l'API du repli SPA. Sans lui, une route inconnue recevrait
`index.html` en **HTTP 200** et serait parsée comme un JSON cassé.

Le versionnage `/v1` est là dès le premier jour : ajouter un préfixe de version à
une API déjà consommée casse tous ses clients.
"""

from __future__ import annotations

from fastapi import APIRouter

from traffic_analysis.features.benchmark.api.routes_benchmark import router as benchmark_router
from traffic_analysis.features.benchmark.api.routes_benchmark_events import (
    router as benchmark_events_router,
)
from traffic_analysis.features.health.api.routes_health import router as health_router
from traffic_analysis.features.jobs.api.routes_job_data import router as job_data_router
from traffic_analysis.features.jobs.api.routes_job_events import router as job_events_router
from traffic_analysis.features.jobs.api.routes_jobs import router as jobs_router
from traffic_analysis.features.models_registry.api.routes_models import (
    router as models_router,
)
from traffic_analysis.features.presets.api.routes_presets import router as presets_router
from traffic_analysis.features.realtime.api.routes_realtime import router as realtime_router

API_V1_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_V1_PREFIX)

# Chaque feature monte son routeur ici, et nulle part ailleurs : la liste des
# capacités exposées se lit d'un seul coup d'œil.
api_router.include_router(health_router)
api_router.include_router(jobs_router)
# Le SSE est un routeur distinct bien qu'il partage le préfixe `/jobs` : son
# protocole n'a rien à voir avec celui des routes JSON, et le mélanger rendrait
# `routes_jobs.py` illisible.
api_router.include_router(job_events_router)
api_router.include_router(job_data_router)
api_router.include_router(models_router)
api_router.include_router(benchmark_router)
# Comme pour les jobs, le SSE est un routeur distinct bien qu'il partage le
# préfixe `/benchmark` : son protocole n'a rien à voir avec celui des routes JSON.
api_router.include_router(benchmark_events_router)
api_router.include_router(presets_router)
# Le WebSocket temps réel. Monté sur le même préfixe `/api/v1` que le reste :
# l'origine unique évite tout réglage CORS pour l'usage normal.
api_router.include_router(realtime_router)
