"""Environnement Alembic, configuré en **async**.

Deux réglages sont indispensables sur SQLite et faciles à oublier :

- **`render_as_batch=True`.** SQLite ne sait pas `ALTER COLUMN` ; sans le mode
  batch, toute évolution de colonne échoue (piège 49 de prompt/13).
- **`compare_type=True`.** Sans lui, un changement de type de colonne passe
  inaperçu à l'autogénération, et la migration produite ne fait rien.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from traffic_analysis.core.db.base import Base
from traffic_analysis.core.settings import Settings

# Importer les modèles peuple `Base.metadata` : sans ces imports,
# l'autogénération croirait le schéma vide et produirait un `drop` de tout.
from traffic_analysis.features.jobs.infrastructure import orm  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL de la base, depuis `Settings` — une seule source de vérité.

    Une URL écrite dans `alembic.ini` finirait par diverger de celle du service,
    et on migrerait la mauvaise base sans s'en apercevoir.
    """
    override = config.get_main_option("sqlalchemy.url", None)
    if override:
        return override
    return Settings().database_url


def run_migrations_offline() -> None:
    """Génère le SQL sans se connecter — utile pour relire une migration."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Applique les migrations via un moteur async."""
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        # `NullPool` : une commande de migration est un processus court, garder un
        # pool ouvert l'empêcherait de se terminer proprement.
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run)
    await connectable.dispose()


# Quand Alembic est piloté depuis le code (démarrage du service, tests), une
# connexion est déjà ouverte et passée par `config.attributes`. La réutiliser est
# indispensable sur SQLite : une seconde connexion sur le même fichier attendrait
# le verrou d'écriture que la première détient — donc un interblocage.
_injected = config.attributes.get("connection")

if _injected is not None:
    _run(_injected)
elif context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
