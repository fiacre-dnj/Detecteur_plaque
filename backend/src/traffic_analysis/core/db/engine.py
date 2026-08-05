"""Moteur SQLAlchemy async et PRAGMA SQLite.

Trois pièges SQLite sont réglés ici, et chacun coûte cher à diagnostiquer :

1. **`PRAGMA foreign_keys` est désactivé par défaut.** Sans lui, les cascades ne
   s'appliquent pas et les orphelins s'accumulent **silencieusement** : on
   supprime un job, ses cinq mille franchissements restent.
2. **Un seul écrivain à la fois.** WAL rend les lectures concurrentes possibles,
   mais deux écritures se sérialisent — d'où les inserts en lot et la progression
   qui ne va pas en base à chaque image.
3. **`expire_on_commit=False` est obligatoire en async.** Sans lui, lire un
   attribut après un commit déclenche un rechargement qui lève `MissingGreenlet`,
   avec un message qui ne dit rien de la cause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from traffic_analysis.core.settings import Settings

# Attente du verrou d'écriture. 30 s est large : une insertion en lot de plusieurs
# milliers de lignes doit pouvoir attendre qu'une purge se termine plutôt que
# d'échouer sur « database is locked ».
LOCK_TIMEOUT_S = 30
BUSY_TIMEOUT_MS = 30_000


def create_engine(settings: Settings) -> AsyncEngine:
    """Crée le moteur et installe les PRAGMA sur chaque connexion.

    Sur chaque connexion et non une fois : SQLite applique les PRAGMA **par
    connexion**, et le pool en ouvre plusieurs. Les poser au démarrage seulement
    laisserait la moitié des connexions sans clés étrangères.
    """
    is_sqlite = settings.database_url.startswith("sqlite")
    if is_sqlite:
        _ensure_parent_directory(settings.database_url)
    connect_args: dict[str, Any] = {"timeout": LOCK_TIMEOUT_S} if is_sqlite else {}

    engine = create_async_engine(
        settings.database_url,
        echo=settings.env == "development" and settings.log_level == "DEBUG",
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    if is_sqlite:
        _install_sqlite_pragmas(engine)
    return engine


def _ensure_parent_directory(database_url: str) -> None:
    """Crée le répertoire du fichier de base s'il manque.

    Sans cela, un premier démarrage sur une machine neuve échoue sur
    « unable to open database file » — un message qui ne dit ni quel fichier ni
    quoi faire. Le répertoire de données est git-ignoré par construction, donc son
    absence est le cas **normal** au premier lancement, pas une anomalie.
    """
    from pathlib import Path
    from urllib.parse import urlsplit

    # `sqlite+aiosqlite:///./data/traffic.db` → `./data/traffic.db`
    location = urlsplit(database_url).path.lstrip("/")
    if not location or location == ":memory:":
        return
    Path(location).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:  # noqa: ANN401
        cursor = dbapi_connection.cursor()
        # WAL : les lecteurs ne bloquent plus pendant une écriture. Sans lui,
        # consulter l'historique pendant une analyse fait attendre l'un des deux.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Désactivé par défaut — c'est LE piège SQLite (piège 47 de prompt/13).
        cursor.execute("PRAGMA foreign_keys=ON")
        # NORMAL avec WAL : bon compromis. FULL synchronise à chaque commit et
        # divise par dix le débit d'insertion, pour une garantie dont on n'a pas
        # besoin sur des résultats reproductibles.
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fabrique de sessions.

    `expire_on_commit=False` : voir l'entête du module — sans lui, lire un
    attribut après commit lève `MissingGreenlet`.

    `autoflush=False` : un flush implicite au milieu d'une lecture réordonne les
    écritures et rend l'ordre des insertions imprévisible, ce qui compte pour des
    événements que la relecture parcourt par horodatage croissant.
    """
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
