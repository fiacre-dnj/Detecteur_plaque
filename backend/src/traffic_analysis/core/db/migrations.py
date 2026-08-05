"""Application programmatique des migrations Alembic.

Les migrations sont exécutées **par Alembic et non par `Base.metadata.create_all`**,
y compris dans les tests. La raison tient en une phrase : une migration cassée
doit être vue par les tests, et c'est la moitié de leur intérêt. Avec
`create_all`, les tests valident un schéma que la production n'aura jamais.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from traffic_analysis.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = get_logger("traffic_analysis.db")

# `backend/` : le répertoire qui contient `alembic.ini` et `migrations/`.
# Chemin de ce fichier : backend/src/traffic_analysis/core/db/migrations.py —
# donc cinq niveaux au-dessus.
BACKEND_ROOT = Path(__file__).resolve().parents[4]


def alembic_config(database_url: str) -> Config:
    """Configuration Alembic pointée sur une base donnée.

    L'URL est passée explicitement plutôt que lue depuis l'environnement : les
    tests migrent une base temporaire, et un `alembic.ini` qui déciderait tout
    seul les ferait tomber sur la base de développement.
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _upgrade(connection: Any, config: Config) -> None:  # noqa: ANN401
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def run_migrations(engine: AsyncEngine) -> None:
    """Amène la base au dernier schéma, si elle n'y est pas déjà.

    La vérification préalable n'est pas une optimisation : `command.upgrade`
    ouvre sa propre connexion, et l'appeler sur une base déjà à jour prend un
    verrou d'écriture pour rien — ce qui, sur SQLite, bloque un autre processus.
    """
    url = engine.url.render_as_string(hide_password=False)
    config = alembic_config(url)

    async with engine.begin() as connection:
        current = await connection.run_sync(_current_revision)
    head = ScriptDirectory.from_config(config).get_current_head()

    if current == head:
        return

    logger.info("migration de la base", depuis=current or "vide", vers=head)
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade, config)


def _current_revision(connection: Any) -> str | None:  # noqa: ANN401
    return MigrationContext.configure(connection).get_current_revision()
