"""Machine à états, annulation, échec et purge — au niveau du gestionnaire.

Ces chemins sont difficiles à provoquer de façon fiable à travers HTTP : une
analyse factice se termine en quelques millisecondes, donc « annuler pendant que
ça tourne » y est une course. Ici le moteur est piloté image par image, et le
scénario devient déterministe.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from tests.support.builders import CAR, compose, straight_line, track_path
from tests.support.engine import FakeEngine
from traffic_analysis.core.errors import ConflictError, JobNotFoundError
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    CountingLineDef,
    Point,
)
from traffic_analysis.features.jobs.application.job_manager import JobManager
from traffic_analysis.features.jobs.application.progress_hub import ProgressHub
from traffic_analysis.features.jobs.domain.status import (
    InvalidJobTransition,
    can_transition,
    ensure_transition,
    is_terminal,
)
from traffic_analysis.features.jobs.infrastructure.memory_repository import InMemoryJobRepository
from traffic_analysis.features.jobs.infrastructure.result_store import FileResultStore

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.core.clock import FrozenClock

LINE = CountingLineDef(id="l1", name="Nord", a=Point(0.0, 500.0), b=Point(1920.0, 500.0))
CONFIG = AnalysisJobConfig(model_id="yolov8n", lines=(LINE,))


class SlowEngine(FakeEngine):
    """Moteur qui laisse la boucle respirer entre deux images.

    Sans cette pause, l'analyse factice se termine avant que le test ait pu
    demander l'annulation, et le scénario ne teste plus rien.
    """

    def __init__(self, frames: Any, *, delay_s: float = 0.02) -> None:  # noqa: ANN401
        super().__init__(frames)
        self._delay_s = delay_s

    def iter_video(self, video_path: Path, spec: Any) -> Any:  # noqa: ANN401
        import time

        for frame in super().iter_video(video_path, spec):
            time.sleep(self._delay_s)
            yield frame


def _frames(steps: int = 40) -> list[list[Any]]:
    return compose(track_path(1, CAR, straight_line((900.0, 250.0), (900.0, 800.0), steps=steps)))


async def _manager(
    tmp_path: Path,
    clock: FrozenClock,
    *,
    engine: FakeEngine | None = None,
) -> tuple[JobManager, InMemoryJobRepository, FileResultStore]:
    repository = InMemoryJobRepository(clock)
    store = FileResultStore(tmp_path / "data")
    manager = JobManager(
        repository=repository,
        result_store=store,
        analysis=AnalysisService(engine or FakeEngine(_frames())),
        hub=ProgressHub(),
        clock=clock,
        max_concurrent_jobs=1,
    )
    manager.bind_loop(asyncio.get_running_loop())
    return manager, repository, store


async def _submit(manager: JobManager, tmp_path: Path, job_id: str = "job-1") -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 16)
    await manager.submit(
        job_id,
        video,
        CONFIG,
        file_name="clip.mp4",
        file_size_bytes=16,
        config_json={"modelId": "yolov8n"},
    )


async def _await_status(manager: JobManager, job_id: str, *, timeout_s: float = 5.0) -> str:
    async with asyncio.timeout(timeout_s):
        while True:
            record = await manager.get(job_id)
            if is_terminal(record.status):
                return record.status
            await asyncio.sleep(0.005)


class TestMachineAEtats:
    def test_les_transitions_legitimes_sont_acceptees(self) -> None:
        assert can_transition("queued", "running")
        assert can_transition("running", "done")
        assert can_transition("queued", "cancelled")

    def test_un_statut_qui_saute_une_etape_leve(self) -> None:
        """Une transition refusée est un bug d'orchestration.

        L'ignorer laisserait un job éternellement `running` sans que rien ne le
        signale — c'est le pire des deux mondes.
        """
        with pytest.raises(InvalidJobTransition):
            ensure_transition("queued", "done")

    def test_un_job_terminal_est_immuable(self) -> None:
        """Relancer une analyse crée un **nouveau** job, ce qui rend les
        comparaisons possibles et empêche un historique de se réécrire."""
        for target in ("running", "queued", "done", "error"):
            with pytest.raises(InvalidJobTransition):
                ensure_transition("done", target)  # type: ignore[arg-type]

    def test_les_trois_statuts_terminaux(self) -> None:
        assert is_terminal("done")
        assert is_terminal("error")
        assert is_terminal("cancelled")
        assert not is_terminal("queued")
        assert not is_terminal("running")


class TestExecution:
    async def test_un_job_passe_par_running_puis_done(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)

        assert await _await_status(manager, "job-1") == "done"
        record = await manager.get("job-1")
        assert record.started_at is not None
        assert record.finished_at is not None
        assert record.progress == 1.0
        assert store.path_for("job-1") is not None

    async def test_les_agregats_sont_denormalises_pour_l_historique(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Trier l'historique ne doit pas obliger à ouvrir chaque `json.gz`."""
        manager, _, _ = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")

        record = await manager.get("job-1")
        assert record.unique_vehicles == 1
        assert record.crossings_total == 1
        assert record.stats_json is not None
        assert record.result_path == "jobs/job-1/result.json.gz"

    async def test_un_moteur_en_echec_termine_le_job_en_erreur_sans_fuir(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Le message stocké est destiné à l'utilisateur, jamais une trace."""
        engine = FakeEngine(_frames(), fail_with=RuntimeError("chemin /srv/prive/poids.pt"))
        manager, _, _ = await _manager(tmp_path, clock, engine=engine)
        await _submit(manager, tmp_path)

        assert await _await_status(manager, "job-1") == "error"
        record = await manager.get("job-1")
        assert record.error is not None
        assert "/srv/prive" not in record.error
        assert "RuntimeError" not in record.error


class TestAnnulation:
    async def test_annuler_un_job_en_cours_le_termine_en_cancelled(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """L'annulation est **coopérative** : l'analyse s'arrête entre deux images.

        C'est ce qui laisse le bail du modèle se rendre proprement, alors qu'un
        `task.cancel()` l'immobiliserait jusqu'au redémarrage du service.
        """
        manager, _, _ = await _manager(tmp_path, clock, engine=SlowEngine(_frames()))
        await _submit(manager, tmp_path)

        # Laisser l'analyse démarrer réellement avant de demander l'arrêt.
        async with asyncio.timeout(2.0):
            while (await manager.get("job-1")).status != "running":
                await asyncio.sleep(0.005)

        await manager.cancel_or_purge("job-1")

        assert await _await_status(manager, "job-1") == "cancelled"

    async def test_annuler_un_job_encore_en_file_le_termine_aussi(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Un job `queued` n'a pas de worker pour observer l'événement d'arrêt.

        Sans traitement explicite, il resterait en attente indéfiniment — et le
        sémaphore le lancerait bien plus tard, à la surprise de l'utilisateur.
        """
        manager, _, _ = await _manager(tmp_path, clock, engine=SlowEngine(_frames()))
        await _submit(manager, tmp_path, job_id="occupant")
        await _submit(manager, tmp_path, job_id="en-file")

        async with asyncio.timeout(2.0):
            while (await manager.get("en-file")).status != "queued":
                await asyncio.sleep(0.005)
        await manager.cancel_or_purge("en-file")

        assert (await manager.get("en-file")).status == "cancelled"
        await manager.shutdown()

    async def test_supprimer_un_job_termine_purge_le_fichier(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        assert store.path_for("job-1") is not None

        await manager.cancel_or_purge("job-1")

        assert store.path_for("job-1") is None
        with pytest.raises(JobNotFoundError):
            await manager.get("job-1")


class TestResultat:
    async def test_le_resultat_d_un_job_non_termine_est_refuse(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        manager, _, _ = await _manager(tmp_path, clock, engine=SlowEngine(_frames()))
        await _submit(manager, tmp_path)

        with pytest.raises(ConflictError) as excinfo:
            await manager.result_path("job-1")

        assert excinfo.value.code == "job_not_finished"
        await manager.shutdown()

    async def test_un_resultat_purge_a_son_propre_code_d_erreur(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """« Attendre » et « relancer » sont deux actions différentes : le client
        doit pouvoir les distinguer sans lire le message."""
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        store.delete("job-1")

        with pytest.raises(ConflictError) as excinfo:
            await manager.result_path("job-1")

        assert excinfo.value.code == "result_missing"


class TestPurgeTtl:
    async def test_seuls_les_jobs_terminaux_perimes_sont_purges(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Purger un job en cours détruirait une analyse que quelqu'un attend."""
        manager, _, _ = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")

        assert await manager.purge_expired(older_than_minutes=60) == 0

        clock.advance(2 * 3600)
        assert await manager.purge_expired(older_than_minutes=60) == 1
        with pytest.raises(JobNotFoundError):
            await manager.get("job-1")

    async def test_la_purge_est_idempotente(self, tmp_path: Path, clock: FrozenClock) -> None:
        """Un incident partiel ne doit pas bloquer la purge pour toujours."""
        manager, _, _ = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        clock.advance(2 * 3600)

        assert await manager.purge_expired(60) == 1
        assert await manager.purge_expired(60) == 0
