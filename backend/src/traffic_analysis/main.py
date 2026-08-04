"""Point d'entrée ASGI.

    uv run uvicorn traffic_analysis.main:app --reload --port 8000

Ce module ne contient **que** l'instanciation : toute la composition vit dans
`app_factory.create_app()`, de sorte qu'un test n'ait jamais à importer `main`
(ce qui déclencherait la lecture de l'environnement réel).
"""

from __future__ import annotations

from traffic_analysis.app_factory import create_app

app = create_app()
