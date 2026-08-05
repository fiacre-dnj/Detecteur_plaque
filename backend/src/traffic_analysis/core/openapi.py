"""Personnalisation du schéma OpenAPI.

Trois ajouts que FastAPI ne peut pas deviner :

1. **Les schémas de sécurité**, déclarés bien qu'aucune authentification ne soit
   branchée. C'est le point d'extension documenté : le jour où une clé d'API
   arrive, le contrat ne change pas, seule son application change.
2. **Le schéma du résultat d'analyse**, servi en fichier donc invisible pour
   FastAPI. Sans lui, la route la plus importante du service n'aurait aucune
   documentation de sa réponse.
3. **Des exemples `curl`** sur les routes principales : une documentation qu'on
   peut copier-coller se lit deux fois plus vite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi.openapi.utils import get_openapi

if TYPE_CHECKING:
    from fastapi import FastAPI

# Schémas prêts à l'emploi. Déclarés, non appliqués : aucune route ne les exige
# aujourd'hui, et les inventer le jour venu ferait un contrat qui change.
SECURITY_SCHEMES: dict[str, Any] = {
    "ApiKeyAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Point d'extension : aucune route ne l'exige aujourd'hui.",
    },
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Point d'extension : aucune route ne l'exige aujourd'hui.",
    },
}

ANALYSIS_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Résultat complet d'une analyse, servi depuis un fichier `json.gz`. "
        "Il n'est pas revalidé à la sortie : une timeline de 54 000 lignes "
        "doublerait la mémoire pour rien."
    ),
    "properties": {
        "jobId": {"type": "string"},
        "modelId": {"type": "string"},
        "processingFps": {"type": "number"},
        "video": {"type": "object", "description": "Dimensions, cadence, durée."},
        "timeline": {
            "type": "array",
            "description": (
                "Une entrée par image analysée, avec les pistes **figées** à cet "
                "instant. C'est ce que le client rejoue sur la vidéo locale."
            ),
            "items": {"type": "object"},
        },
        "crossings": {"type": "array", "items": {"type": "object"}},
        "zoneEvents": {"type": "array", "items": {"type": "object"}},
        "vehicles": {
            "type": "array",
            "description": "Le registre : une entrée par identité.",
            "items": {"type": "object"},
        },
        "stats": {"type": "object", "description": "Le bloc affiché par les cartes."},
    },
}

CURL_SAMPLES: dict[str, str] = {
    "createAnalysisJob": (
        "curl -X POST http://127.0.0.1:8000/api/v1/jobs \\\n"
        "  -F 'file=@carrefour.mp4' \\\n"
        '  -F \'request={"modelId":"yolov8n","lines":[{"id":"l1",'
        '"a":{"x":0,"y":700},"b":{"x":1920,"y":700}}]}\''
    ),
    "streamAnalysisJobEvents": "curl -N http://127.0.0.1:8000/api/v1/jobs/<id>/events",
    "getAnalysisResult": "curl --compressed http://127.0.0.1:8000/api/v1/jobs/<id>/result",
}


def custom_openapi(app: FastAPI) -> dict[str, Any]:
    """Construit le schéma une fois puis le sert depuis le cache.

    Le cache n'est pas une micro-optimisation : la génération parcourt toutes les
    routes et tous les modèles, et Swagger UI la déclencherait à chaque
    rafraîchissement de la page.
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        license_info=app.license_info,
        servers=[
            {"url": "/", "description": "Origine courante"},
            {"url": "http://127.0.0.1:8000", "description": "Développement local"},
        ],
    )

    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {}).update(SECURITY_SCHEMES)
    components.setdefault("schemas", {})["AnalysisResult"] = ANALYSIS_RESULT_SCHEMA

    _attach_result_schema(schema)
    _attach_curl_samples(schema)

    app.openapi_schema = schema
    return schema


def _attach_result_schema(schema: dict[str, Any]) -> None:
    """Branche le schéma manuel sur la route qui sert le fichier."""
    operation = _find_operation(schema, "getAnalysisResult")
    if operation is None:
        return
    operation.setdefault("responses", {}).setdefault("200", {}).setdefault("content", {})[
        "application/json"
    ] = {"schema": {"$ref": "#/components/schemas/AnalysisResult"}}


def _attach_curl_samples(schema: dict[str, Any]) -> None:
    for operation_id, sample in CURL_SAMPLES.items():
        operation = _find_operation(schema, operation_id)
        if operation is not None:
            operation["x-codeSamples"] = [{"lang": "curl", "source": sample}]


def _find_operation(schema: dict[str, Any], operation_id: str) -> dict[str, Any] | None:
    for methods in schema.get("paths", {}).values():
        for operation in methods.values():
            if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                return operation
    return None
