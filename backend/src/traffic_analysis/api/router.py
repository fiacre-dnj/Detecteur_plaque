"""Routeur racine `/api/v1`.

Le préfixe `/api` n'est pas décoratif : c'est lui qui permet au proxy Vite de
distinguer l'API du repli SPA. Sans lui, une route inconnue recevrait
`index.html` en **HTTP 200** et serait parsée comme un JSON cassé.

Le versionnage `/v1` est là dès le premier jour : ajouter un préfixe de version à
une API déjà consommée casse tous ses clients.
"""

from __future__ import annotations

from fastapi import APIRouter

from traffic_analysis.features.health.api.routes_health import router as health_router

API_V1_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_V1_PREFIX)

# Chaque feature monte son routeur ici, et nulle part ailleurs : la liste des
# capacités exposées se lit d'un seul coup d'œil.
api_router.include_router(health_router)
