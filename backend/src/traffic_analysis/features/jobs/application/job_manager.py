"""Cycle de vie d'une analyse différée.

Trois règles de concurrence gouvernent ce module, et chacune évite un gel ou un
chiffre faux :

1. **L'inférence part dans un thread worker** (`anyio.to_thread.run_sync`). Elle
   est bloquante et longue ; la laisser dans la boucle asyncio figerait tout le
   service, y compris la sonde de vivacité.
2. **L'annulation passe par un `threading.Event`**, pas par `task.cancel()`. On
   n'interrompt pas un `track()` en cours : on lui demande de s'arrêter entre deux
   images, ce qui laisse le bail du modèle se rendre proprement.
3. **Un sémaphore borne les analyses simultanées.** Un GPU = une analyse à la
   fois. Le job est tout de même **accepté** (202, statut `queued`) : l'utilisateur
   doit voir « en file d'attente », pas un 503.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

import anyio.to_thread

from traffic_analysis.core.errors import ConflictError, JobNotFoundError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import (
    AnalysisCancelled,
    Progress,
    VideoInfo,
)
from traffic_analysis.features.counting.application.serializers import (
    serialise_result,
    serialise_stats,
)
from traffic_analysis.features.jobs.application.progress_hub import ProgressEvent, ProgressHub
from traffic_analysis.features.jobs.domain.records import JobRecord, VideoMetadata
from traffic_analysis.features.jobs.domain.status import JobStatus, ensure_transition, is_terminal

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.core.clock import Clock
    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.counting.application.analysis_service import AnalysisService
    from traffic_analysis.features.counting.application.dto import AnalysisJobConfig
    from traffic_analysis.features.jobs.application.ports import (
        JobFilters,
        JobRepository,
        ResultStore,
    )

logger = get_logger("traffic_analysis.jobs")

# Intervalle de persistance de la progression. La valeur vivante est en mémoire
# dans le hub ; la base n'est écrite que de loin en loin, parce que SQLite n'a
# qu'un écrivain (piège 27 de prompt/13).
PROGRESS_PERSIST_INTERVAL_S = 2.0


class JobManager:
    """Accepte, exécute, suit et annule les analyses différées."""

    __slots__ = (
        "_analysis",
        "_cancellations",
        "_clock",
        "_hub",
        "_max_concurrent",
        "_repository",
        "_result_store",
        "_semaphore",
        "_tasks",
    )

    def __init__(
        self,
        repository: JobRepository,
        result_store: ResultStore,
        analysis: AnalysisService,
        hub: ProgressHub,
        clock: Clock,
        *,
        max_concurrent_jobs: int = 1,
    ) -> None:
        self._repository = repository
        self._result_store = result_store
        self._analysis = analysis
        self._hub = hub
        self._clock = clock
        self._max_concurrent = max_concurrent_jobs
        self._semaphore: asyncio.Semaphore | None = None
        self._cancellations: dict[str, threading.Event] = {}
        # Les tâches de fond sont gardées dans un ensemble : une tâche asyncio
        # sans référence forte peut être ramassée par le GC **en pleine
        # exécution**, et l'analyse s'arrête alors sans aucun message.
        self._tasks: set[asyncio.Task[None]] = set()

    # ── Cycle de vie du gestionnaire ─────────────────────────────────────────

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attache le gestionnaire à la boucle du service, au démarrage."""
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._hub.bind_loop(loop)

    async def shutdown(self) -> None:
        """Demande l'arrêt de tout ce qui tourne, et attend.

        On demande plutôt qu'on annule : un `track()` interrompu laisserait le
        bail du modèle non rendu.
        """
        for event in self._cancellations.values():
            event.set()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    # ── Dépôt ────────────────────────────────────────────────────────────────

    async def submit(
        self,
        job_id: str,
        video_path: Path,
        config: AnalysisJobConfig,
        *,
        file_name: str,
        file_size_bytes: int,
        config_json: dict[str, Any],
    ) -> JobRecord:
        """Enregistre un job et lance son exécution en tâche de fond.

        Rend immédiatement, statut `queued` : c'est ce qui permet à la route de
        répondre 202 sans attendre la fin d'une analyse de plusieurs minutes.
        """
        record = JobRecord(
            id=job_id,
            status="queued",
            model_id=config.model_id,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            created_at=self._clock.now(),
            config_json=config_json,
        )
        await self._repository.add(record)
        self._publish(record)

        task = asyncio.create_task(self._run(job_id, video_path, config), name=f"job-{job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return record

    def probe_video(self, video_path: Path) -> VideoInfo:
        """Sonde une vidéo **avant** de créer le job.

        Synchrone et rapide (lecture d'entête), donc pas de thread worker : la
        route en a besoin pour refuser un fichier non décodable en 415 plutôt que
        de créer un job qui échouera trente secondes plus tard.
        """
        return self._analysis.probe(video_path)

    # ── Lectures ─────────────────────────────────────────────────────────────

    async def get(self, job_id: str) -> JobRecord:
        record = await self._repository.get(job_id)
        if record is None:
            raise JobNotFoundError(f"Le job « {job_id} » n'existe pas.")
        return record

    async def list(self, filters: JobFilters, page: PageParams) -> Page[JobRecord]:
        return await self._repository.list(filters, page)

    async def result_path(self, job_id: str) -> Path:
        """Chemin du résultat, ou une erreur qui dit **pourquoi** il manque.

        Trois refus distincts, parce qu'ils appellent trois actions différentes de
        la part de l'utilisateur : attendre, relancer, ou signaler un incident.
        """
        record = await self.get(job_id)
        if record.status != "done":
            raise ConflictError(
                f"Le résultat n'est pas disponible : le job est « {record.status} ».",
                code="job_not_finished",
            )
        path = self._result_store.path_for(job_id)
        if path is None:
            raise ConflictError(
                "Le fichier de résultat a été purgé. Relancez l'analyse pour le régénérer.",
                code="result_missing",
            )
        return path

    # ── Annulation et purge ──────────────────────────────────────────────────

    async def cancel_or_purge(self, job_id: str) -> JobRecord:
        """Annule un job actif, purge un job terminal.

        Une seule route pour les deux : du point de vue de l'utilisateur, le geste
        est le même — « je ne veux plus de ce job ».
        """
        record = await self.get(job_id)
        if is_terminal(record.status):
            await self._purge(job_id)
            return record.with_changes(status=record.status)

        event = self._cancellations.get(job_id)
        if event is not None:
            event.set()
        # Un job encore `queued` n'a pas de worker pour observer l'événement :
        # on le termine ici, sinon il resterait en attente indéfiniment.
        if record.status == "queued":
            await self._finish(job_id, "cancelled")
            return await self.get(job_id)
        return record

    async def purge_expired(self, older_than_minutes: int) -> int:
        """Supprime les jobs terminaux périmés. Idempotent, journalisé."""
        expired = await self._repository.list_expired(older_than_minutes)
        for record in expired:
            await self._purge(record.id)
        if expired:
            logger.info("purge TTL", removed=len(expired), ttl_minutes=older_than_minutes)
        return len(expired)

    async def purge_expired_inputs(self, older_than_minutes: int) -> int:
        """Supprime **les vidéos déposées** des jobs terminés, en gardant les résultats.

        La vidéo a son propre TTL, plus court que celui du job, et pour une raison
        qui n'est pas de la place disque : une scène de trafic contient des plaques
        réelles et des visages. Le résultat, lui, ne contient que des boîtes et des
        compteurs — il peut rester bien plus longtemps sans que cela pose la moindre
        question.

        Sans cette méthode, `input_ttl_minutes` était un réglage inerte : la
        configuration promettait une suppression au bout d'une heure, et la vidéo
        survivait jusqu'au TTL du job — vingt-quatre fois plus longtemps par défaut.
        Un écart entre une promesse de confidentialité et le comportement réel est
        plus grave qu'une promesse absente.

        Jobs **terminaux** seulement : supprimer l'entrée d'une analyse en cours la
        ferait échouer au milieu.
        """
        expired = await self._repository.list_expired(older_than_minutes)
        removed = 0
        for record in expired:
            if self._result_store.delete_input(record.id):
                removed += 1
        if removed:
            logger.info(
                "purge des vidéos déposées", removed=removed, ttl_minutes=older_than_minutes
            )
        return removed

    async def _purge(self, job_id: str) -> None:
        self._result_store.delete(job_id)
        await self._repository.delete(job_id)
        self._hub.forget(job_id)

    # ── Exécution ────────────────────────────────────────────────────────────

    async def _run(self, job_id: str, video_path: Path, config: AnalysisJobConfig) -> None:
        """Exécute une analyse, du sémaphore au statut terminal."""
        semaphore = self._semaphore
        if semaphore is None:  # pragma: no cover — bind_loop est appelé au démarrage
            message = "JobManager.bind_loop n'a pas été appelé."
            raise RuntimeError(message)

        cancellation = threading.Event()
        self._cancellations[job_id] = cancellation
        try:
            async with semaphore:
                # L'annulation peut être arrivée pendant l'attente en file.
                if cancellation.is_set():
                    await self._finish(job_id, "cancelled")
                    return
                await self._execute(job_id, video_path, config, cancellation)
        except AnalysisCancelled:
            # Une annulation n'est **pas** une erreur : l'utilisateur sait ce
            # qu'il a fait, lui afficher « échec » serait faux.
            await self._finish(job_id, "cancelled")
        except Exception as exc:
            logger.exception("analyse en échec", job_id=job_id, exc_info=exc)
            await self._finish(
                job_id,
                "error",
                error="L'analyse a échoué. Consultez les journaux du serveur.",
            )
        finally:
            self._cancellations.pop(job_id, None)

    async def _execute(
        self,
        job_id: str,
        video_path: Path,
        config: AnalysisJobConfig,
        cancellation: threading.Event,
    ) -> None:
        await self._transition(job_id, "running", started=True)

        loop = asyncio.get_running_loop()
        last_persist = loop.time()

        def on_progress(progress: Progress) -> None:
            """Appelé **depuis le thread worker**."""
            self._hub.publish_threadsafe(
                ProgressEvent(job_id, self._progress_payload(job_id, "running", progress))
            )
            nonlocal last_persist
            now = loop.time()
            if now - last_persist >= PROGRESS_PERSIST_INTERVAL_S:
                last_persist = now
                # `run_coroutine_threadsafe` et non `await` : on est hors boucle.
                asyncio.run_coroutine_threadsafe(
                    self._repository.update_progress(job_id, progress), loop
                )

        result = await anyio.to_thread.run_sync(
            lambda: self._analysis.run_video(
                job_id,
                video_path,
                config,
                on_progress=on_progress,
                is_cancelled=cancellation.is_set,
            )
        )

        await self._repository.set_video_metadata(
            job_id,
            VideoMetadata(
                width=result.video.width,
                height=result.video.height,
                fps=result.video.fps,
                frame_count=result.video.frame_count,
                duration_ms=result.video.duration_ms,
            ),
        )
        # L'écriture du fichier est du disque en volume : elle part aussi en
        # thread, sinon un résultat de 200 Mo bloque la boucle plusieurs secondes.
        await anyio.to_thread.run_sync(
            lambda: self._result_store.write(job_id, serialise_result(result))
        )
        await self._repository.save_result_aggregates(job_id, result)
        await self._finish(job_id, "done")

    async def _transition(self, job_id: str, status: JobStatus, *, started: bool = False) -> None:
        record = await self.get(job_id)
        ensure_transition(record.status, status)
        await self._repository.set_status(job_id, status)
        if started:
            logger.info("analyse démarrée", job_id=job_id, model_id=record.model_id)
        self._publish(await self.get(job_id))

    async def _finish(self, job_id: str, status: JobStatus, *, error: str | None = None) -> None:
        record = await self._repository.get(job_id)
        if record is None or is_terminal(record.status):
            # Le job a pu être purgé pendant l'analyse. Ce n'est pas une erreur.
            return
        await self._repository.set_status(job_id, status, error=error)
        final = await self.get(job_id)
        self._publish(final, terminal=True)

    # ── Publication ──────────────────────────────────────────────────────────

    def _publish(self, record: JobRecord, *, terminal: bool = False) -> None:
        self._hub.publish(
            ProgressEvent(
                record.id, self.describe(record), terminal=terminal or is_terminal(record.status)
            )
        )

    def _progress_payload(
        self, job_id: str, status: JobStatus, progress: Progress
    ) -> dict[str, Any]:
        return {
            "jobId": job_id,
            "status": status,
            "progress": round(progress.ratio, 4),
            "processedFrames": progress.processed_frames,
            "totalFrames": progress.total_frames,
            "processingFps": round(progress.processing_fps, 2),
            "error": None,
        }

    @staticmethod
    def describe(record: JobRecord) -> dict[str, Any]:
        """Le job tel que l'API l'expose. Une seule forme, statut comme SSE."""
        return {
            "jobId": record.id,
            "status": record.status,
            "progress": round(record.progress, 4),
            "processedFrames": record.processed_frames,
            "totalFrames": record.total_frames,
            "processingFps": round(record.processing_fps, 2),
            "error": record.error,
            "modelId": record.model_id,
            "fileName": record.file_name,
            "createdAt": record.created_at.isoformat(),
            "finishedAt": record.finished_at.isoformat() if record.finished_at else None,
        }

    @staticmethod
    def aggregates_of(result: Any) -> dict[str, Any]:  # noqa: ANN401
        """Bloc `stats` dénormalisé, pour l'historique."""
        return serialise_stats(result.stats) if result.stats else {}
