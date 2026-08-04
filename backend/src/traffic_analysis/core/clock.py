"""Horloge injectable.

Un test qui dépend de `time.time()` est un test instable : il passe le matin et
échoue quand la machine est chargée. Les services qui datent quelque chose
reçoivent donc une `Clock`.

**Attention à ne pas confondre deux temps.** Cette horloge est l'horloge murale,
et son seul usage légitime est la *mesure de performance* (durée d'un job, FPS de
traitement) et l'horodatage d'un enregistrement en base. Tout horodatage
**métier** est du temps de scène — `frame_index / fps × 1000` — et ne passe
jamais par ici. Mélanger les deux casse d'un coup les débits, les vitesses et les
gates de ré-identification (piège 19 de prompt/13).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Source de temps murale."""

    def now(self) -> datetime:
        """Instant courant, **timezone-aware en UTC**.

        SQLite stocke des chaînes : mélanger des datetimes naïfs et conscients
        produit des comparaisons silencieusement fausses (piège 5 de prompt/07).
        """
        ...

    def monotonic(self) -> float:
        """Compteur monotone en secondes, pour mesurer une durée.

        Distinct de `now()` volontairement : une durée mesurée avec l'heure
        murale devient négative quand l'horloge du système est ajustée.
        """
        ...


class SystemClock:
    """Implémentation de production."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class FrozenClock:
    """Horloge de test, avançable à la main.

    Elle vit dans le code de production et non dans `tests/` parce qu'elle est
    l'autre implémentation qui justifie l'existence du protocole : une
    abstraction à implémentation unique n'a pas lieu d'être.
    """

    def __init__(self, start: datetime, *, monotonic_start: float = 0.0) -> None:
        self._now = start
        self._monotonic = monotonic_start

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds
