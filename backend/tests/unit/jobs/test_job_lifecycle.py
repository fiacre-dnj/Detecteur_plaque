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
from traffic_analysis.core.errors import ConflictError, JobNotFoundError, UnavailableError
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


class FakePreparer:
    """Un `ModelPreparer` qui journalise ses appels, et peut refuser.

    `prepare_error` rend testable le scénario réel de 2.1 : un modèle absent du
    disque et intéléchargeable. Sans doublure, ce chemin ne serait traversé que par
    le vrai registre, donc jamais par la CI.
    """

    def __init__(self, *, fails_with: Exception | None = None) -> None:
        self.calls: list[str] = []
        self._fails_with = fails_with

    async def prepare(self, model_id: str) -> None:
        self.calls.append(model_id)
        if self._fails_with is not None:
            raise self._fails_with


async def _manager(
    tmp_path: Path,
    clock: FrozenClock,
    *,
    engine: FakeEngine | None = None,
    hub: ProgressHub | None = None,
    preview_interval_ms: int = 0,
    preparer: FakePreparer | None = None,
) -> tuple[JobManager, InMemoryJobRepository, FileResultStore]:
    """Gestionnaire de test. **Aperçu désactivé par défaut** : les scénarios de
    cycle de vie n'en veulent pas, et publier des images à chaque frame y
    ajouterait du bruit sans rien vérifier de plus."""
    repository = InMemoryJobRepository(clock)
    store = FileResultStore(tmp_path / "data")
    manager = JobManager(
        repository=repository,
        result_store=store,
        analysis=AnalysisService(engine or FakeEngine(_frames())),
        hub=hub or ProgressHub(),
        clock=clock,
        preparer=preparer,
        max_concurrent_jobs=1,
        preview_interval_ms=preview_interval_ms,
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


async def _await_running(manager: JobManager, job_id: str, *, timeout_s: float = 5.0) -> None:
    """Attend que l'analyse tourne **réellement**.

    Bornée par une échéance et non par un nombre d'itérations : un verdict qui
    dépend de la vitesse de la machine ne prouve rien.
    """
    async with asyncio.timeout(timeout_s):
        while (await manager.get(job_id)).status != "running":
            await asyncio.sleep(0.005)


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
        # Aucun code : personne n'a rédigé cet échec pour être lu, donc l'interface
        # n'a aucune action particulière à proposer.
        assert record.error_code is None

    async def test_une_app_error_fait_traverser_son_message_et_son_code(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Le pendant exact du test précédent — **les deux tracent la frontière**.

        Une `AppError` a été levée délibérément, avec un message écrit pour un
        humain et un code stable pour la machine. « Le modèle « yolo11x » n'a pas
        pu être chargé » dit quoi faire ; « consultez les journaux du serveur » ne
        dit rien à quelqu'un qui n'a pas accès aux journaux.

        Ce que le test d'à côté garantit reste vrai : un `RuntimeError` n'est pas
        une `AppError`, donc il tombe dans la branche générique et ne fuit rien.
        """
        engine = FakeEngine(
            _frames(),
            fail_with=UnavailableError(
                "Le modèle « yolo11x » n'a pas pu être chargé : téléchargement impossible.",
                code="model_unavailable",
            ),
        )
        manager, _, _ = await _manager(tmp_path, clock, engine=engine)
        await _submit(manager, tmp_path)

        assert await _await_status(manager, "job-1") == "error"
        record = await manager.get("job-1")
        assert record.error == (
            "Le modèle « yolo11x » n'a pas pu être chargé : téléchargement impossible."
        )
        assert record.error_code == "model_unavailable"
        # `describe` est le contrat publié : le code doit y figurer, sinon
        # l'interface ne peut pas brancher son bouton de préchargement dessus.
        assert JobManager.describe(record)["errorCode"] == "model_unavailable"


class TestPreparationDuModele:
    """Le modèle est chargé **avant** que le job prétende travailler.

    Le mode de panne supprimé : le téléchargement d'un poids absent n'avait lieu
    qu'à la première itération d'`iter_video`, donc après le passage en
    « en cours ». Un modèle intéléchargeable produisait une analyse « en cours »
    figée à 0 %, que rien ne distinguait d'un service planté.
    """

    async def test_le_modele_est_prepare_avant_le_passage_en_cours(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        preparer = FakePreparer()
        manager, _, _ = await _manager(tmp_path, clock, preparer=preparer)
        await _submit(manager, tmp_path)

        assert await _await_status(manager, "job-1") == "done"
        assert preparer.calls == ["yolov8n"]

    async def test_un_modele_impreparable_echoue_sans_jamais_passer_running(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """**Le cœur de 2.1.** Le job ne prétend jamais travailler.

        `started_at` est le témoin le plus sûr : il n'est posé que par la
        transition vers `running`. Le trouver nul prouve que le job n'y est jamais
        passé — y compris fugitivement, ce qu'un sondage de statut pourrait rater.
        """
        preparer = FakePreparer(
            fails_with=UnavailableError(
                "Le modèle « yolo11x » n'a pas pu être chargé : téléchargement impossible.",
                code="model_unavailable",
            )
        )
        manager, _, _ = await _manager(tmp_path, clock, preparer=preparer)
        await _submit(manager, tmp_path)

        assert await _await_status(manager, "job-1") == "error"
        record = await manager.get("job-1")
        assert record.started_at is None
        # Le message du registre traverse, et son code avec — c'est le lot 1 qui
        # rend cette préparation utile plutôt que muette.
        assert record.error is not None
        assert "yolo11x" in record.error
        assert record.error_code == "model_unavailable"

    async def test_la_preparation_est_annoncee_puis_retombee(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """`preparing` est publié **vrai une fois**, et n'est jamais persisté.

        C'est ce qui permet à la barre d'écrire « Préparation : chargement du
        modèle » au lieu de « 0 / 0 images · 0.0 img/s », sans ajouter un statut à
        la machine à états pour un état de passage.
        """
        hub = ProgressHub()
        preparer = FakePreparer()
        manager, _, _ = await _manager(tmp_path, clock, hub=hub, preparer=preparer)
        received: list[Any] = []

        async def collect() -> None:
            async for event in hub.subscribe("job-1"):
                received.append(event)

        collector = asyncio.create_task(collect())
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        async with asyncio.timeout(2.0):
            await collector

        assert any(event.payload.get("preparing") is True for event in received)
        # Jamais persisté : l'état relu de la base ne porte aucune préparation.
        assert JobManager.describe(await manager.get("job-1"))["preparing"] is False


class TestApercu:
    """L'aperçu publié pendant l'analyse — et ce qu'il ne doit pas perturber."""

    async def test_l_analyse_publie_des_apercus_a_cote_de_la_progression(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        hub = ProgressHub()
        manager, _, _ = await _manager(tmp_path, clock, hub=hub, preview_interval_ms=1)
        received: list[Any] = []

        async def collect() -> None:
            async for event in hub.subscribe("job-1"):
                received.append(event)

        collector = asyncio.create_task(collect())
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        # La tâche s'arrête d'elle-même sur l'événement terminal ; on lui laisse
        # le tour de boucle qu'il lui faut pour le consommer.
        async with asyncio.timeout(2.0):
            await collector

        kinds = [event.kind for event in received]
        assert "preview" in kinds
        assert "progress" in kinds
        payload = next(event.payload for event in received if event.kind == "preview")
        assert set(payload) == {
            "jobId",
            "frameIndex",
            "timestampMs",
            "frameWidth",
            "frameHeight",
            "tracks",
            "crossings",
            "zoneEvents",
            "stats",
        }

    async def test_un_apercu_n_est_jamais_le_dernier_etat_connu_du_job(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Sinon un client qui se reconnecte recevrait une image en guise de statut.

        Le hub sert son dernier événement aux nouveaux abonnés : y laisser entrer
        un aperçu ferait lire « progression inconnue » à une interface qui demande
        où en est l'analyse.
        """
        hub = ProgressHub()
        manager, _, _ = await _manager(tmp_path, clock, hub=hub, preview_interval_ms=1)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")

        last = hub.last_event("job-1")
        assert last is not None
        assert last.kind == "progress"
        assert last.payload["status"] == "done"

    async def test_un_intervalle_nul_desactive_l_apercu(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Le flux redevient exactement ce qu'il était avant que l'aperçu existe."""
        hub = ProgressHub()
        manager, _, _ = await _manager(tmp_path, clock, hub=hub, preview_interval_ms=0)
        received: list[Any] = []

        async def collect() -> None:
            async for event in hub.subscribe("job-1"):
                received.append(event)

        collector = asyncio.create_task(collect())
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        async with asyncio.timeout(2.0):
            await collector

        assert all(event.kind == "progress" for event in received)


class TestSuspensionEtReprise:
    """Suspendre, reprendre, et ce que la pause garde.

    Ce que ces tests protègent, au-delà du statut : une analyse reprise doit
    **continuer** la précédente. Si la reprise repartait de zéro, ou perdait les
    identités, les totaux finaux seraient faux sans que rien ne le signale — et
    c'est exactement le mode de défaillance que le projet combat partout ailleurs.
    """

    async def test_suspendre_puis_reprendre_mene_le_job_a_done(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        manager, _, store = await _manager(tmp_path, clock, engine=SlowEngine(_frames()))
        await _submit(manager, tmp_path)
        await _await_running(manager, "job-1")

        paused = await manager.pause("job-1")
        assert paused.status == "paused"

        # La preuve que l'analyse est bien arrêtée : la progression ne bouge plus.
        frozen = (await manager.get("job-1")).processed_frames
        await asyncio.sleep(0.2)
        assert (await manager.get("job-1")).processed_frames == frozen

        assert (await manager.resume("job-1")).status == "running"
        assert await _await_status(manager, "job-1") == "done"
        assert store.path_for("job-1") is not None

    async def test_une_analyse_reprise_continue_la_precedente(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Le résultat est celui d'une analyse entière, pas d'un morceau.

        Le véhicule du scénario franchit la ligne **après** la suspension : si la
        reprise repartait d'une session neuve, il serait compté comme un second
        véhicule, ou pas compté du tout.
        """
        manager, _, _ = await _manager(tmp_path, clock, engine=SlowEngine(_frames()))
        await _submit(manager, tmp_path)
        await _await_running(manager, "job-1")

        await manager.pause("job-1")
        await manager.resume("job-1")
        await _await_status(manager, "job-1")

        record = await manager.get("job-1")
        assert record.unique_vehicles == 1
        assert record.crossings_total == 1

    async def test_annuler_un_job_suspendu_le_termine_sans_le_reprendre(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Sinon l'annulation n'aurait lieu qu'à la reprise — c'est-à-dire jamais.

        Le worker est bloqué dans la barrière de pause : si l'annulation ne la
        libérait pas, le thread attendrait indéfiniment un ordre de reprise que
        l'utilisateur ne donnera plus, en gardant le bail du modèle.
        """
        manager, _, _ = await _manager(tmp_path, clock, engine=SlowEngine(_frames()))
        await _submit(manager, tmp_path)
        await _await_running(manager, "job-1")
        await manager.pause("job-1")

        await manager.cancel_or_purge("job-1")

        assert await _await_status(manager, "job-1") == "cancelled"

    async def test_suspendre_un_job_qui_ne_tourne_pas_est_refuse(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Le code d'erreur porte la cause : « attendre » et « c'est fini » sont
        deux situations différentes, et le client doit pouvoir les distinguer sans
        lire le message."""
        manager, _, _ = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")

        with pytest.raises(ConflictError) as excinfo:
            await manager.pause("job-1")

        assert excinfo.value.code == "job_not_running"

    async def test_reprendre_un_job_qui_n_est_pas_suspendu_est_refuse(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        manager, _, _ = await _manager(tmp_path, clock, engine=SlowEngine(_frames()))
        await _submit(manager, tmp_path)
        await _await_running(manager, "job-1")

        with pytest.raises(ConflictError) as excinfo:
            await manager.resume("job-1")

        assert excinfo.value.code == "job_not_paused"
        await manager.cancel_or_purge("job-1")
        await _await_status(manager, "job-1")

    async def test_la_progression_publiee_pendant_la_pause_annonce_la_pause(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """L'image en vol au moment de la suspension ne doit pas dire « en cours ».

        Elle arrive **après** le passage en pause et serait le dernier mot du flux :
        l'interface afficherait « analyse en cours » sur une analyse arrêtée, et
        resterait ainsi jusqu'à la reprise.
        """
        hub = ProgressHub()
        manager, _, _ = await _manager(tmp_path, clock, hub=hub, engine=SlowEngine(_frames()))
        received: list[Any] = []

        async def collect() -> None:
            async for event in hub.subscribe("job-1"):
                received.append(event)

        collector = asyncio.create_task(collect())
        await _submit(manager, tmp_path)
        await _await_running(manager, "job-1")
        await manager.pause("job-1")
        await asyncio.sleep(0.15)

        assert received
        assert received[-1].payload["status"] == "paused"

        await manager.cancel_or_purge("job-1")
        await _await_status(manager, "job-1")
        async with asyncio.timeout(2.0):
            await collector


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

    async def test_la_purge_efface_reellement_le_repertoire_du_job(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        """Sur le **disque**, pas seulement en base.

        Les tests précédents comptaient les jobs purgés. Aucun ne regardait le
        système de fichiers — et c'est exactement l'angle mort qui a laissé
        `input_ttl_minutes` inerte pendant tout le projet.
        """
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        directory = store.directory_for("job-1")
        assert directory.is_dir()

        clock.advance(2 * 3600)
        await manager.purge_expired(60)

        assert not directory.exists()


class TestPurgeDesVideosDeposees:
    """Le TTL propre aux vidéos — plus court que celui des jobs.

    Ce n'est pas une question de place disque : une scène de trafic contient des
    plaques réelles et des visages, alors qu'un résultat ne contient que des boîtes
    et des compteurs. La donnée sensible doit avoir la durée de vie la plus courte
    que l'usage permet.
    """

    async def test_la_video_est_supprimee_et_le_resultat_conserve(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        video = store.input_path("job-1", ".mp4")
        video.write_bytes(b"\x00" * 32)
        assert store.path_for("job-1") is not None

        clock.advance(2 * 3600)
        assert await manager.purge_expired_inputs(60) == 1

        assert not video.exists()
        # Le résultat survit : c'est tout l'intérêt d'un TTL séparé.
        assert store.path_for("job-1") is not None

    async def test_le_job_reste_consultable_apres_la_purge_de_sa_video(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        # L'utilisateur doit pouvoir relire ses chiffres longtemps après que les
        # images ont disparu — sinon la purge détruirait le travail avec la donnée.
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        store.input_path("job-1", ".mp4").write_bytes(b"\x00")
        clock.advance(2 * 3600)

        await manager.purge_expired_inputs(60)

        assert (await manager.get("job-1")).status == "done"

    async def test_une_video_encore_fraiche_n_est_pas_touchee(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        video = store.input_path("job-1", ".mp4")
        video.write_bytes(b"\x00")

        assert await manager.purge_expired_inputs(60) == 0
        assert video.exists()

    async def test_la_purge_des_videos_est_idempotente(
        self, tmp_path: Path, clock: FrozenClock
    ) -> None:
        # Le second passage rend 0 : sans cela la boucle de nettoyage annoncerait
        # « 40 vidéos purgées » toutes les minutes sur les mêmes 40 jobs déjà
        # nettoyés, et le journal deviendrait inutilisable.
        manager, _, store = await _manager(tmp_path, clock)
        await _submit(manager, tmp_path)
        await _await_status(manager, "job-1")
        store.input_path("job-1", ".mp4").write_bytes(b"\x00")
        clock.advance(2 * 3600)

        assert await manager.purge_expired_inputs(60) == 1
        assert await manager.purge_expired_inputs(60) == 0
