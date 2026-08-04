"""Middlewares transverses.

L'ordre d'ajout compte et il est décidé dans `app_factory.create_app()`, pas ici :
Starlette exécute les middlewares dans l'ordre **inverse** de leur ajout pour la
réponse, et la raison de chaque position mérite d'être lisible en un seul endroit.
"""

from __future__ import annotations
