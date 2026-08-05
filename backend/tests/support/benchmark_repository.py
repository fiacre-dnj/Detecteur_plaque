"""Dépôt de benchmark en mémoire — **une doublure de test, pas une variante réelle**.

La distinction avec `InMemoryJobRepository` est volontaire : celui-là est une
seconde implémentation réelle, qui permet au service de tourner sans base. Ici, il
n'y a pas d'équivalent — le benchmark exige la persistance (un run est rechargé à
l'ouverture de la page), et la dépendance FastAPI répond 503 quand la base manque.
Fournir un dépôt en mémoire côté production contredirait ce refus.

Il vit donc dans `tests/support/`, où il sert les tests du **protocole de mesure**,
qui n'ont rien à dire sur SQLite.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from traffic_analysis.core.pagination import Page

if TYPE_CHECKING:
    from traffic_analysis.core.pagination import PageParams
    from traffic_analysis.features.benchmark.domain.records import BenchmarkEntry, BenchmarkRun


class InMemoryBenchmarkRepository:
    """Runs conservés dans un dictionnaire, du plus récent au plus ancien."""

    __slots__ = ("_runs",)

    def __init__(self) -> None:
        self._runs: dict[str, BenchmarkRun] = {}

    async def add(self, run: BenchmarkRun) -> None:
        # Copie : le service mute son propre objet au fil du run, et un dépôt qui
        # partagerait l'instance ne testerait plus rien — tout ce qui est écrit
        # apparaîtrait « déjà là », y compris ce que le service a oublié d'écrire.
        self._runs[run.id] = replace(run, entries=list(run.entries))

    async def get(self, run_id: str) -> BenchmarkRun | None:
        stored = self._runs.get(run_id)
        return replace(stored, entries=list(stored.entries)) if stored else None

    async def latest(self) -> BenchmarkRun | None:
        if not self._runs:
            return None
        # Dernier inséré : les dictionnaires Python conservent l'ordre d'insertion,
        # ce qui suffit ici — un test ne crée pas deux runs dans la même
        # milliseconde comme le fait la base.
        run_id = next(reversed(self._runs))
        return await self.get(run_id)

    async def list(self, page: PageParams) -> Page[BenchmarkRun]:
        runs = [self._runs[run_id] for run_id in reversed(self._runs)]
        window = runs[page.offset : page.offset + page.limit]
        return Page.of(
            [replace(run, entries=list(run.entries)) for run in window],
            total=len(runs),
            params=page,
        )

    async def append_entry(self, run_id: str, entry: BenchmarkEntry) -> None:
        stored = self._runs.get(run_id)
        if stored is not None:
            stored.entries.append(entry)

    async def set_status(self, run_id: str, status: str, *, error: str | None = None) -> None:
        stored = self._runs.get(run_id)
        if stored is not None:
            stored.status = status  # type: ignore[assignment]
            stored.error = error

    async def delete(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
