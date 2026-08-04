"""Journalisation structurée : structlog, console en développement, JSON en production.

Chaque enregistrement porte le `request_id` de la requête en cours. C'est ce qui
rend un rapport d'incident exploitable : l'utilisateur cite l'identifiant affiché
par l'interface, et une seule recherche remonte toute la chaîne.

Le `request_id` circule par un `contextvars.ContextVar`, pas par un paramètre
passé de fonction en fonction : il traverse `await`, il est isolé par tâche
asyncio, et il ne pollue pas la signature de chaque service.

Ne **jamais** journaliser le contenu d'une frame, ni un chemin d'upload complet
en production.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, TextIO

import structlog

if TYPE_CHECKING:
    from traffic_analysis.core.settings import Settings

# Vide hors d'une requête (tâches de fond, démarrage) : le champ est alors absent
# du journal plutôt que renseigné d'une valeur factice.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def current_request_id() -> str | None:
    return request_id_var.get()


def _add_request_id(
    _logger: object, _name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Injecte le `request_id` courant s'il existe."""
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(settings: Settings, *, stream: TextIO | None = None) -> None:
    """Configure structlog et la bibliothèque standard d'un seul coup.

    Les deux sont configurées ensemble parce que uvicorn, SQLAlchemy et
    Ultralytics passent par `logging` : sans passerelle, la moitié des messages
    du service sortirait dans un autre format, et un `grep` sur les journaux
    manquerait exactement ce qu'on cherche.

    `stream` sert aux tests qui vérifient la **sortie rendue** (le `request_id`
    est-il bien dans la ligne ?). Sans cette couture, le flux est insaisissable :
    le handler retient l'objet `sys.stderr` de l'instant où il est construit, et
    la capture de pytest le remplace à un autre moment. Vérifier la configuration
    au lieu du résultat ne prouverait rien — elle a déjà changé une fois sans que
    la sortie suive.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    destination = stream if stream is not None else sys.stderr

    renderer: structlog.types.Processor
    if settings.log_format == "json":
        # `format_exc_info` n'est utile qu'en JSON : le rendu console de
        # structlog produit déjà une trace lisible et colorée lui-même.
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        # Les couleurs sont des séquences d'échappement : utiles dans un
        # terminal, du bruit dans un fichier ou dans une assertion de test.
        colorize = hasattr(destination, "isatty") and destination.isatty()
        renderer = structlog.dev.ConsoleRenderer(colors=colorize)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler(destination)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Remplacer les handlers plutôt que d'en ajouter : `configure_logging` est
    # appelée par chaque application créée, et les tests en créent beaucoup.
    # Sans cela, chaque ligne finirait dupliquée autant de fois qu'il y a eu
    # d'applications dans le processus.
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    # uvicorn installe ses propres handlers colorés : les retirer pour que tout
    # passe par la racine, sinon les logs d'accès sortent dans un autre format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # uvicorn.access journalise déjà chaque requête dans son propre format ; le
    # middleware d'accès de ce projet le fait en structuré, avec le request_id.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str, **initial: Any) -> structlog.stdlib.BoundLogger:  # noqa: ANN401
    """Journal nommé, éventuellement pré-lié à des champs constants."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger.bind(**initial) if initial else logger
