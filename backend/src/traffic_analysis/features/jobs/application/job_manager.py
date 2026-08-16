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
import time
from time import perf_counter
from typing import TYPE_CHECKING, Any

import anyio.to_thread

from traffic_analysis.core.errors import AppError, ConflictError, JobNotFoundError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.counting.application.dto import (
    AnalysisCancelled,
    Progress,
    VideoInfo,
)
from traffic_analysis.features.counting.application.serializers import (
    serialise_crossing,
    serialise_result,
    serialise_stats,
    serialise_track,
    serialise_zone_event,
)
from traffic_analysis.features.jobs.application.progress_hub import ProgressEvent, ProgressHub
from traffic_analysis.features.jobs.domain.records import JobRecord, VideoMetadata
from traffic_analysis.features.jobs.domain.status import JobStatus, ensure_transition, is_terminal

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.core.clock import Clock
    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.counting.application.analysis_service import AnalysisService
    from traffic_analysis.features.counting.application.dto import (
        AnalysisJobConfig,
        PreviewSample,
    )
    from traffic_analysis.features.jobs.application.ports import (
        JobFilters,
        JobRepository,
        ModelPreparer,
        ResultStore,
    )

logger = get_logger("traffic_analysis.jobs")

# Intervalle de persistance de la progression. La valeur vivante est en mémoire
# dans le hub ; la base n'est écrite que de loin en loin, parce que SQLite n'a
# qu'un écrivain (piège 27 de prompt/13).
PROGRESS_PERSIST_INTERVAL_S = 2.0

#: Pas de sondage de la barrière de pause, dans le thread worker.
#:
#: Assez court pour qu'une reprise paraisse immédiate, assez long pour qu'une
#: pause d'une heure ne coûte rien. À 50 ms, une heure suspendue représente
#: 72 000 réveils d'un thread qui n'a rien à faire — mesurable, et pour rien.
PAUSE_POLL_INTERVAL_S = 0.1


class JobManager:
    """Accepte, exécute, suit et annule les analyses différées."""

    __slots__ = (
        "_analysis",
        "_cancellations",
        "_clock",
        "_hub",
        "_max_concurrent",
        "_pauses",
        "_preparer",
        "_preview_interval_paced_s",
        "_preview_interval_s",
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
        preparer: ModelPreparer | None = None,
        max_concurrent_jobs: int = 1,
        preview_interval_ms: int = 200,
        preview_interval_paced_ms: int = 100,
    ) -> None:
        self._repository = repository
        self._result_store = result_store
        self._analysis = analysis
        self._hub = hub
        self._clock = clock
        # `None` est légitime : les tests de cycle de vie injectent un moteur
        # factice dont le modèle n'a rien à préparer, et la préparation est alors
        # simplement sautée. Ce n'est pas une dégradation silencieuse — sans
        # registre, il n'y a aucun poids à télécharger.
        self._preparer = preparer
        self._max_concurrent = max_concurrent_jobs
        # En millisecondes dans la configuration, en secondes ici : `0` désactive
        # l'aperçu, et la conversion est faite une fois plutôt qu'à chaque job.
        self._preview_interval_s = preview_interval_ms / 1000.0 if preview_interval_ms > 0 else None
        # L'intervalle des analyses bridées. Il ne décide **pas** si l'aperçu existe
        # — c'est `_preview_interval_s` seul qui le fait, à zéro — il ne fait que le
        # resserrer quand la cadence est bornée. `run_video` retient le minimum des
        # deux, donc un déploiement ne peut pas desserrer l'aperçu par ce champ.
        self._preview_interval_paced_s = preview_interval_paced_ms / 1000.0
        self._semaphore: asyncio.Semaphore | None = None
        self._cancellations: dict[str, threading.Event] = {}
        # Un événement **posé** signifie « suspendu ». Comme pour l'annulation, la
        # boucle asyncio le pose et le thread worker l'observe entre deux images :
        # c'est le seul point de rendez-vous sûr entre les deux.
        self._pauses: dict[str, threading.Event] = {}
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

    async def input_video_path(self, job_id: str) -> Path:
        """Chemin de la vidéo analysée, ou une erreur qui dit **pourquoi** elle manque.

        Sert à rejouer une analyse depuis l'historique. Les compteurs, le registre et
        l'histogramme se rejouent depuis le seul `result.json.gz` ; l'incrustation
        des boîtes et le déplacement dans la timeline ont besoin de la vidéo.

        **Le refus est distinct de celui du résultat**, et ce n'est pas du zèle : une
        vidéo purgée n'appelle pas « relancez l'analyse » — le résultat, lui, est
        intact et parfaitement affichable. Elle appelle « redéposez le fichier ».
        Réutiliser `result_missing` enverrait l'utilisateur refaire un calcul qui n'a
        pas besoin d'être refait.
        """
        record = await self.get(job_id)
        if record.status != "done":
            raise ConflictError(
                f"La vidéo n'est pas disponible : le job est « {record.status} ».",
                code="job_not_finished",
            )
        path = self._result_store.input_path_for(job_id)
        if path is None:
            raise ConflictError(
                "La vidéo analysée a été purgée — elle est effacée plus tôt que le "
                "résultat. Les chiffres restent affichables ; redéposez le fichier "
                "pour revoir les boîtes sur l'image.",
                code="input_missing",
            )
        return path

    # ── Suspension et reprise ────────────────────────────────────────────────

    async def pause(self, job_id: str) -> JobRecord:
        """Suspend une analyse en cours, entre deux images.

        Ce que la pause **garde** : la position du décodeur, l'état du suivi, la
        galerie d'identités, les compteurs. C'est ce qui distingue une reprise
        d'une relance — reprendre continue la même analyse, relancer en commence
        une autre, avec d'autres identités et d'autres totaux.

        Ce que la pause **coûte** : la place de calcul et le bail du modèle
        restent pris. Un job suspendu occupe le serveur, et un job en file
        d'attente continue d'attendre. L'interface doit le dire — c'est le prix
        d'une reprise exacte, et il se paie même quand personne ne regarde.
        """
        record = await self.get(job_id)
        if record.status != "running":
            raise ConflictError(
                "Seule une analyse en cours peut être suspendue : "
                f"celle-ci est « {record.status} ».",
                code="job_not_running",
            )
        event = self._pauses.get(job_id)
        if event is not None:
            event.set()
        await self._transition(job_id, "paused")
        logger.info("analyse suspendue", job_id=job_id, processed=record.processed_frames)
        return await self.get(job_id)

    async def resume(self, job_id: str) -> JobRecord:
        """Reprend une analyse suspendue, là où elle s'était arrêtée."""
        record = await self.get(job_id)
        if record.status != "paused":
            raise ConflictError(
                f"Seule une analyse suspendue peut reprendre : celle-ci est « {record.status} ».",
                code="job_not_paused",
            )
        # Le statut **avant** de libérer la barrière : le worker se réveille et
        # publie aussitôt de la progression, et une frame annonçant « en pause »
        # après la reprise ferait clignoter l'interface entre deux états.
        await self._transition(job_id, "running")
        event = self._pauses.get(job_id)
        if event is not None:
            event.clear()
        logger.info("analyse reprise", job_id=job_id, processed=record.processed_frames)
        return await self.get(job_id)

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
        # Libérer la barrière de pause, sinon annuler un job suspendu ne prendrait
        # effet qu'à sa reprise — c'est-à-dire jamais, puisqu'on vient de renoncer.
        paused = self._pauses.get(job_id)
        if paused is not None:
            paused.clear()
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
        pause = threading.Event()
        self._pauses[job_id] = pause
        try:
            async with semaphore:
                # L'annulation peut être arrivée pendant l'attente en file.
                if cancellation.is_set():
                    await self._finish(job_id, "cancelled")
                    return
                await self._execute(job_id, video_path, config, cancellation, pause)
        except AnalysisCancelled:
            # Une annulation n'est **pas** une erreur : l'utilisateur sait ce
            # qu'il a fait, lui afficher « échec » serait faux.
            await self._finish(job_id, "cancelled")
        except AppError as exc:
            # **Une `AppError` a été levée délibérément, avec un message rédigé
            # pour un humain.** « Le modèle « yolo11x » n'a pas pu être chargé »
            # dit quoi faire ; « consultez les journaux du serveur » ne dit rien
            # à quelqu'un qui n'a pas accès aux journaux. Le `code` accompagne le
            # message pour que l'interface puisse proposer l'action qui va avec.
            #
            # La frontière est exactement là : seul ce qui a été construit pour
            # être lu traverse. Voir la branche suivante.
            logger.warning("analyse en échec", job_id=job_id, code=exc.code, detail=exc.detail)
            await self._finish(job_id, "error", error=exc.detail, error_code=exc.code)
        except Exception as exc:
            # Tout le reste — `RuntimeError`, `OSError`, une erreur d'une
            # bibliothèque tierce — porte un message écrit pour un développeur :
            # chemins de fichiers du serveur, noms de classes, parfois un extrait
            # de configuration. Le laisser traverser serait une fuite.
            logger.exception("analyse en échec", job_id=job_id, exc_info=exc)
            await self._finish(
                job_id,
                "error",
                error="L'analyse a échoué. Consultez les journaux du serveur.",
            )
        finally:
            self._cancellations.pop(job_id, None)
            self._pauses.pop(job_id, None)

    async def _execute(
        self,
        job_id: str,
        video_path: Path,
        config: AnalysisJobConfig,
        cancellation: threading.Event,
        pause: threading.Event,
    ) -> None:
        await self._prepare_model(job_id, config.model_id)
        await self._transition(job_id, "running", started=True)

        loop = asyncio.get_running_loop()
        last_persist = loop.time()

        def wait_while_paused() -> float:
            """Barrière de pause, **exécutée dans le thread worker**.

            Un sondage plutôt qu'un `Event.wait()` sur la reprise : il faut se
            réveiller aussi bien sur une reprise que sur une annulation, et
            attendre deux événements à la fois demanderait une condition
            partagée pour un gain nul à ce pas de temps.
            """
            if not pause.is_set():
                return 0.0
            waited_from = perf_counter()
            while pause.is_set() and not cancellation.is_set():
                time.sleep(PAUSE_POLL_INTERVAL_S)
            return perf_counter() - waited_from

        def on_progress(progress: Progress) -> None:
            """Appelé **depuis le thread worker**."""
            # Le statut est **relu** de la barrière, jamais supposé « running » :
            # l'image en cours au moment de la suspension publierait sinon un
            # « analyse en cours » juste après le passage en pause, et l'interface
            # clignoterait entre deux états avant de se figer sur le mauvais.
            status: JobStatus = "paused" if pause.is_set() else "running"
            self._hub.publish_threadsafe(
                ProgressEvent(job_id, self._progress_payload(job_id, status, progress))
            )
            nonlocal last_persist
            now = loop.time()
            if now - last_persist >= PROGRESS_PERSIST_INTERVAL_S:
                last_persist = now
                # `run_coroutine_threadsafe` et non `await` : on est hors boucle.
                asyncio.run_coroutine_threadsafe(
                    self._repository.update_progress(job_id, progress), loop
                )

        def on_preview(sample: PreviewSample) -> None:
            """Appelé **depuis le thread worker**, comme `on_progress`.

            Rien n'est persisté : un aperçu est une image de passage, et l'écrire
            ferait des dizaines d'écritures par seconde dans une base qui n'a
            qu'un écrivain.
            """
            self._hub.publish_threadsafe(
                ProgressEvent(job_id, self._preview_payload(job_id, sample), kind="preview")
            )

        interval = self._preview_interval_s
        result = await anyio.to_thread.run_sync(
            lambda: self._analysis.run_video(
                job_id,
                video_path,
                config,
                on_progress=on_progress,
                on_preview=None if interval is None else on_preview,
                preview_interval_s=interval or 0.0,
                paced_preview_interval_s=self._preview_interval_paced_s,
                is_cancelled=cancellation.is_set,
                wait_while_paused=wait_while_paused,
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

    async def _prepare_model(self, job_id: str, model_id: str) -> None:
        """Rend le modèle utilisable **avant** de prétendre travailler.

        Le mode de panne supprimé : le téléchargement d'un poids absent n'avait
        lieu qu'à la première itération d'`iter_video`, donc **après** le passage
        en « en cours ». Le catalogue annonce vingt modèles et le disque en porte
        trois : dix-sept choix sur vingt affichaient donc une analyse « en cours »
        bloquée à 0 % pendant une à deux minutes, et un échec de téléchargement s'y
        lisait comme un service planté.

        En préparant ici, un modèle impréparable fait échouer le job **sans jamais
        passer par `running`**, avec le message du registre — que le lot 1 fait
        maintenant traverser jusqu'à l'écran.

        L'événement de préparation est publié mais **jamais persisté** : c'est un
        état de passage, et non un statut. En faire un `JobStatus` toucherait la
        machine à états, `is_terminal`, les libellés et tous leurs tests, pour un
        état qui ne dure que le temps d'un chargement.
        """
        if self._preparer is None:
            return
        record = await self.get(job_id)
        self._hub.publish(ProgressEvent(job_id, {**self.describe(record), "preparing": True}))
        await self._preparer.prepare(model_id)

    async def _transition(self, job_id: str, status: JobStatus, *, started: bool = False) -> None:
        record = await self.get(job_id)
        ensure_transition(record.status, status)
        await self._repository.set_status(job_id, status)
        if started:
            logger.info("analyse démarrée", job_id=job_id, model_id=record.model_id)
        self._publish(await self.get(job_id))

    async def _finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        record = await self._repository.get(job_id)
        if record is None or is_terminal(record.status):
            # Le job a pu être purgé pendant l'analyse. Ce n'est pas une erreur.
            return
        await self._repository.set_status(job_id, status, error=error, error_code=error_code)
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
            # Présents et neutres, jamais absents : `describe` et cette charge
            # utile sont **la même forme**, et un client qui lit `errorCode` ou
            # `preparing` sur une trame de progression ne doit pas trouver un champ
            # manquant. Une trame de progression signifie par construction que la
            # préparation est finie — les images défilent déjà.
            "errorCode": None,
            "preparing": False,
        }

    @staticmethod
    def _preview_payload(job_id: str, sample: PreviewSample) -> dict[str, Any]:
        """Un aperçu tel que le client le reçoit.

        **Même forme que le `frameResult` du temps réel**, et par les mêmes
        sérialiseurs. Ce n'est pas une coïncidence entretenue à la main : c'est ce
        qui permet au navigateur de dessiner les deux modes avec un seul chemin de
        rendu, donc de ne pas avoir deux overlays qui divergent.
        """
        return {
            "jobId": job_id,
            "frameIndex": sample.frame_index,
            "timestampMs": sample.timestamp_ms,
            "frameWidth": sample.frame_width,
            "frameHeight": sample.frame_height,
            "tracks": [serialise_track(track) for track in sample.tracks],
            "crossings": [serialise_crossing(event) for event in sample.crossings],
            "zoneEvents": [serialise_zone_event(event) for event in sample.zone_events],
            "stats": serialise_stats(sample.stats),
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
            # Le code **machine** à côté du message humain. C'est lui qui permet à
            # l'interface de proposer l'action qui va avec l'échec — précharger le
            # modèle absent — au lieu de se contenter d'afficher la phrase.
            "errorCode": record.error_code,
            # Faux ici **par construction** : `describe` décrit un état persisté, et
            # la préparation n'est jamais persistée. Seul `_prepare_model` publie
            # `True`, en surchargeant ce champ sur la trame qu'il émet.
            "preparing": False,
            "modelId": record.model_id,
            "fileName": record.file_name,
            "createdAt": record.created_at.isoformat(),
            "finishedAt": record.finished_at.isoformat() if record.finished_at else None,
            # Les agrégats dénormalisés, pour que l'historique dise ce qu'une analyse
            # a trouvé sans ouvrir son `result.json.gz`. Zéro tant qu'elle tourne :
            # ils sont écrits en une fois à la fin.
            "trackedVehicles": record.tracked_vehicles,
            "crossingsTotal": record.crossings_total,
        }

    @staticmethod
    def aggregates_of(result: Any) -> dict[str, Any]:  # noqa: ANN401
        """Bloc `stats` dénormalisé, pour l'historique."""
        return serialise_stats(result.stats) if result.stats else {}
