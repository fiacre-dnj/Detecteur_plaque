"""Types de colonnes personnalisés.

`UtcDateTime` existe pour une raison précise et coûteuse : **SQLite ne stocke pas
de fuseau horaire**. Une colonne `DateTime(timezone=True)` y accepte un datetime
conscient et le relit **naïf**, si bien que le comparer à `datetime.now(UTC)` lève
`TypeError` — ou, pire, réussit ailleurs dans le code en comparant deux naïfs dont
l'un était en heure locale. La purge TTL ne purge alors rien, ou purge trop, et
rien ne le signale.

L'adaptateur datetime par défaut de `sqlite3` est par ailleurs **déprécié depuis
Python 3.12** : convertir explicitement règle les deux problèmes d'un coup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, TypeDecorator

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect

# ISO-8601 : triable en tant que texte, donc `ORDER BY` et les comparaisons
# fonctionnent directement en SQL, sans conversion ni index fonctionnel.
_LENGTH = 32


class UtcDateTime(TypeDecorator[datetime]):
    """Datetime stocké en ISO-8601 UTC, relu **toujours** conscient."""

    impl = String(_LENGTH)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:  # noqa: ARG002
        """Écrit en UTC, en refusant un datetime naïf.

        Refuser plutôt que supposer : un datetime naïf peut être en heure locale
        comme en UTC, et deviner produirait un décalage silencieux de deux heures
        en été.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            message = (
                "Un datetime naïf ne peut pas être persisté : son fuseau est "
                "ambigu. Utilisez datetime.now(UTC)."
            )
            raise ValueError(message)
        return value.astimezone(UTC).isoformat()

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:  # noqa: ARG002
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        # Filet : une valeur écrite avant l'introduction de ce type serait naïve.
        # La supposer UTC est le seul choix cohérent avec le reste du service.
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
