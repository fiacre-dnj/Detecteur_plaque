"""Le protocole de mesure. C'est la partie du lot qui compte.

Un benchmark est facile à écrire et facile à rendre faux. Les six règles ci-dessous
sont chacune la différence entre un tableau exploitable et un tableau décoratif ;
elles viennent de `prompt/04-MODELES-YOLO-ET-BENCHMARK.md` §6, et la plupart ont
coûté une mesure fausse dans la version précédente.

1. **Une image de référence unique pour tous les modèles.** Elle est résolue une
   seule fois, au démarrage du run, et son `sha256` est persisté. Comparer des
   modèles sur des images différentes ne compare rien.
2. **`load_ms = 0` si le modèle était déjà résident.** La résidence est
   interrogée *avant* le chargement. Un zéro ici est la vérité — il n'y avait rien
   à charger — et non une mesure manquante déguisée.
3. **Un run de chauffe, écarté.** La première inférence d'un modèle inclut la
   fusion de ses couches et l'allocation de ses tampons : la retenir ferait
   apparaître chaque modèle deux à dix fois plus lent qu'il ne l'est.
4. **Les seuils sont ceux de la requête, pas ceux du catalogue.** Sinon la colonne
   « détections » contredit ce que l'utilisateur voit à l'écran avec ses réglages.
5. **Chaque modèle est libéré après sa mesure**, sauf s'il est occupé par une
   analyse en cours — et le fait d'avoir libéré (ou pas) est **dit** dans la
   réponse. Vingt modèles résidents épuisent la mémoire : c'est la leçon de la
   version précédente, et elle est la vraie raison d'être de ce module.
6. **Un échec est capturé par modèle.** La ligne porte son message, le run
   continue. Un benchmark qui s'arrête au troisième modèle parce qu'un poids ne se
   télécharge pas n'a mesuré rien du tout.

À quoi s'ajoute une contrainte de ressource : **un seul benchmark à la fois**
(`asyncio.Semaphore(1)`). Deux runs simultanés se mesureraient l'un l'autre.
"""

from __future__ import annotations

import asyncio
import builtins
import threading
from typing import TYPE_CHECKING, Any

import anyio.to_thread

from traffic_analysis.core.errors import ConflictError, NotFoundError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.benchmark.domain.records import (
    BenchmarkEntry,
    BenchmarkRun,
    BenchmarkStatus,
    is_terminal,
)
from traffic_analysis.features.jobs.application.progress_hub import ProgressEvent, ProgressHub

if TYPE_CHECKING:
    from traffic_analysis.core.pagination import Page, PageParams
    from traffic_analysis.features.benchmark.application.ports import (
        BenchmarkRepository,
        InferenceProbe,
        ProbeResult,
        ProbeSpec,
        ReferenceImage,
        ReferenceImageProvider,
    )

logger = get_logger("traffic_analysis.benchmark")

# Nombre de mesures retenues par défaut, run de chauffe **non compris**. Cinq est
# le compromis du cahier des charges : assez pour que la médiane ait un sens, assez
# peu pour que vingt modèles sur CPU restent tenables.
DEFAULT_FRAMES = 5

# Le run de chauffe. Un seul suffit : ce qu'il paie (fusion des couches,
# allocation des tampons) ne se paie qu'une fois.
WARMUP_RUNS = 1


class BenchmarkNotFoundError(NotFoundError):
    code = "benchmark_not_found"


class BenchmarkService:
    """Exécute, suit et annule un run de benchmark, un seul à la fois."""

    __slots__ = (
        "_cancellations",
        "_hub",
        "_images",
        "_probe",
        "_repository",
        "_semaphore",
        "_tasks",
    )

    def __init__(
        self,
        repository: BenchmarkRepository,
        probe: InferenceProbe,
        images: ReferenceImageProvider,
        hub: ProgressHub,
    ) -> None:
        self._repository = repository
        self._probe = probe
        self._images = images
        self._hub = hub
        # Créé dans `bind_loop` : un `asyncio.Semaphore` construit hors boucle
        # s'attacherait à la mauvaise boucle et bloquerait pour de bon.
        self._semaphore: asyncio.Semaphore | None = None
        self._cancellations: dict[str, threading.Event] = {}
        # Référence forte obligatoire : une tâche asyncio sans référence peut être
        # ramassée **en pleine exécution**, et le run s'arrêterait sans un mot.
        self._tasks: set[asyncio.Task[None]] = set()

    # ── Cycle de vie ─────────────────────────────────────────────────────────

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attache le service à la boucle du serveur, au démarrage."""
        # Un seul benchmark à la fois : deux runs simultanés se mesureraient l'un
        # l'autre, et les deux chiffres seraient faux sans que rien ne le signale.
        self._semaphore = asyncio.Semaphore(1)
        self._hub.bind_loop(loop)

    async def shutdown(self) -> None:
        """Demande l'arrêt des runs en cours, et attend.

        Demander plutôt qu'annuler : une inférence interrompue de force
        laisserait le bail de son modèle non rendu, donc une instance immobilisée
        jusqu'au redémarrage.
        """
        for event in self._cancellations.values():
            event.set()
        await self.wait_for_idle()

    async def wait_for_idle(self) -> None:
        """Attend la fin des runs en cours, **sans** demander leur arrêt.

        Utilisée par `shutdown()` après avoir posé les drapeaux d'annulation, et
        par les tests. Elle existe pour eux autant que pour la production : sans
        elle, un test devrait sonder le statut dans une boucle bornée en nombre
        d'itérations, donc échouer dès que la machine ralentit — sous coverage, par
        exemple. Attendre la tâche est déterministe ; compter des itérations ne
        l'est pas.

        La reprise de `self._tasks` est refaite à chaque tour : une tâche peut en
        créer une autre, et un unique `gather` manquerait la seconde.
        """
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    # ── Dépôt ────────────────────────────────────────────────────────────────

    async def submit(
        self,
        run_id: str,
        *,
        model_ids: tuple[str, ...],
        frames: int,
        spec: ProbeSpec,
        image_source: str,
        job_id: str | None,
    ) -> BenchmarkRun:
        """Accepte un run et le lance en tâche de fond. Rend immédiatement.

        L'image de référence est résolue **ici**, de façon synchrone, avant
        d'accepter : si la vidéo du job demandé a été purgée, l'utilisateur doit
        l'apprendre par un refus immédiat, pas par un run qui échoue une minute
        plus tard sans dire lequel de ses choix était en cause.

        Le contexte matériel est capturé au même moment, pour la même raison
        qu'il est persisté : un résultat sans son contexte est trompeur.
        """
        for model_id in model_ids:
            self._probe.describe(model_id)  # 404 explicite avant tout travail

        image = await anyio.to_thread.run_sync(lambda: self._resolve_image(image_source, job_id))

        run = BenchmarkRun(
            id=run_id,
            status="queued",
            model_ids=model_ids,
            frames=frames,
            image_source="job" if image_source == "job" else "sample",
            image_hash=image.sha256,
            image_width=image.width,
            image_height=image.height,
            device=self._probe.device(),
            half=self._probe.half(),
            ultralytics_version=self._probe.ultralytics_version(),
            confidence_threshold=spec.confidence,
            iou_threshold=spec.iou,
            job_id=job_id,
        )
        await self._repository.add(run)
        self._publish(run)

        task = asyncio.create_task(self._run(run, image, spec), name=f"benchmark-{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run

    def _resolve_image(self, image_source: str, job_id: str | None) -> ReferenceImage:
        """Résout l'image de référence. Synchrone : elle touche le disque.

        Un `jobId` sans `imageSource="job"` est traité comme une demande de frame
        de job : c'est la seule lecture qui ne trahit pas l'intention.
        """
        if image_source == "job" or job_id is not None:
            if job_id is None:
                raise ConflictError(
                    "L'image de référence « job » exige un identifiant de job.",
                    code="benchmark_job_required",
                )
            return self._images.from_job(job_id)
        return self._images.sample()

    # ── Lectures ─────────────────────────────────────────────────────────────

    async def get(self, run_id: str) -> BenchmarkRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise BenchmarkNotFoundError(f"Le benchmark « {run_id} » n'existe pas.")
        return run

    async def latest(self) -> BenchmarkRun | None:
        """Le run le plus récent, terminé ou non.

        Cette lecture existe pour une raison d'interface : ouvrir la page de
        benchmark sur un tableau vide alors qu'une mesure existe en base donne
        l'impression que rien n'a jamais fonctionné.
        """
        return await self._repository.latest()

    async def list(self, page: PageParams) -> Page[BenchmarkRun]:
        return await self._repository.list(page)

    # ── Annulation ───────────────────────────────────────────────────────────

    async def cancel_or_purge(self, run_id: str) -> BenchmarkRun:
        """Annule un run actif, supprime un run terminal.

        Une seule route pour les deux gestes : du point de vue de l'utilisateur,
        c'est le même — « je ne veux plus de ce run ».
        """
        run = await self.get(run_id)
        if is_terminal(run.status):
            await self._repository.delete(run_id)
            self._hub.forget(run_id)
            return run

        event = self._cancellations.get(run_id)
        if event is not None:
            event.set()
        # Un run encore `queued` n'a pas de worker pour observer l'événement : il
        # resterait en attente indéfiniment. On le termine ici.
        if run.status == "queued":
            await self._finish(run, "cancelled")
            return await self.get(run_id)
        return run

    # ── Exécution ────────────────────────────────────────────────────────────

    async def _run(self, run: BenchmarkRun, image: ReferenceImage, spec: ProbeSpec) -> None:
        """Déroule un run, du sémaphore au statut terminal."""
        semaphore = self._semaphore
        if semaphore is None:  # pragma: no cover — bind_loop est appelé au démarrage
            message = "BenchmarkService.bind_loop n'a pas été appelé."
            raise RuntimeError(message)

        cancellation = threading.Event()
        self._cancellations[run.id] = cancellation
        try:
            async with semaphore:
                if cancellation.is_set():
                    await self._finish(run, "cancelled")
                    return
                await self._measure_all(run, image, spec, cancellation)
        except Exception as exc:
            logger.exception("benchmark en échec", run_id=run.id, exc_info=exc)
            await self._finish(
                run, "error", error="Le benchmark a échoué. Consultez les journaux du serveur."
            )
        finally:
            self._cancellations.pop(run.id, None)

    async def _measure_all(
        self,
        run: BenchmarkRun,
        image: ReferenceImage,
        spec: ProbeSpec,
        cancellation: threading.Event,
    ) -> None:
        """Mesure les modèles **dans l'ordre du catalogue**, un par un.

        Un par un et jamais en parallèle : deux modèles mesurés simultanément se
        disputent le même CPU (ou le même GPU) et se ralentissent mutuellement.
        Les chiffres resteraient plausibles et seraient faux tous les deux.
        """
        await self._transition(run, "running")

        for model_id in run.model_ids:
            if cancellation.is_set():
                await self._finish(run, "cancelled")
                return

            entry = await anyio.to_thread.run_sync(
                lambda mid=model_id: self._measure_one(mid, image, spec, run.frames)  # type: ignore[misc]
            )
            run.entries.append(entry)
            await self._repository.append_entry(run.id, entry)
            self._publish(run)

        await self._finish(run, "done")

    def _measure_one(
        self,
        model_id: str,
        image: ReferenceImage,
        spec: ProbeSpec,
        frames: int,
    ) -> BenchmarkEntry:
        """Mesure un modèle. **Appelée depuis un thread worker.**

        Ne lève jamais : un échec devient une ligne portant son message (règle 6).
        C'est le seul endroit du projet où l'on avale une exception aussi large, et
        c'est délibéré — l'alternative est un run de vingt modèles perdu pour un
        seul poids manquant.
        """
        label, tier = self._probe.describe(model_id)

        # Interrogé **avant** le chargement : c'est ce qui rend `load_ms = 0`
        # honnête pour un modèle déjà résident (règle 2).
        was_loaded = self._probe.is_loaded(model_id)

        try:
            load_ms = self._load_and_time(model_id, was_loaded=was_loaded)
            samples, last = self._sample(model_id, image, spec, frames)
        except Exception as exc:
            logger.warning("modèle non mesurable", model_id=model_id, error=str(exc))
            # Une tentative de libération malgré l'échec : un chargement à moitié
            # abouti peut tout de même avoir laissé une instance résidente.
            released = self._release(model_id, was_loaded=was_loaded)
            return BenchmarkEntry.failure(
                model_id=model_id,
                label=label,
                tier=tier,
                error=_user_message(exc, model_id),
                released=released,
            )

        released = self._release(model_id, was_loaded=was_loaded)
        entry = BenchmarkEntry.from_samples(
            model_id=model_id,
            label=label,
            tier=tier,
            samples=samples,
            load_ms=load_ms,
            detections=last.detections,
            preprocess_ms=last.preprocess_ms,
            postprocess_ms=last.postprocess_ms,
            was_loaded=was_loaded,
            released=released,
        )
        logger.info(
            "modèle mesuré",
            model_id=model_id,
            median_ms=round(entry.median_ms, 2),
            p95_ms=round(entry.p95_ms, 2),
            detections=entry.detections,
            released=released,
        )
        return entry

    def _load_and_time(self, model_id: str, *, was_loaded: bool) -> float:
        """Charge le modèle et rend la durée du chargement, en millisecondes.

        **Zéro si le modèle était déjà résident** (règle 2). L'horloge murale est
        légitime ici : c'est une mesure de performance, pas un horodatage métier
        (invariant 1).
        """
        if was_loaded:
            return 0.0
        from time import perf_counter

        started = perf_counter()
        self._probe.load(model_id)
        return (perf_counter() - started) * 1000.0

    def _sample(
        self,
        model_id: str,
        image: ReferenceImage,
        spec: ProbeSpec,
        frames: int,
    ) -> tuple[builtins.list[float], ProbeResult]:
        """Un run de chauffe **écarté**, puis `frames` runs retenus (règle 3).

        `builtins.list` et non `list` dans l'annotation : dans le corps de cette
        classe, `list` désigne la méthode de lecture paginée, et l'annotation
        résoudrait vers elle — mypy le refuse, à juste titre.

        Le résultat de la dernière inférence est rendu avec la série : c'est de lui
        que viennent le nombre de détections et les temps de pré/post-traitement.
        Le prendre sur la dernière et non sur la chauffe est volontaire — la
        chauffe n'est pas une mesure, et son `speed` reflète une allocation en
        cours.
        """
        for _ in range(WARMUP_RUNS):
            self._probe.infer_once(model_id, image.pixels, spec)

        samples: list[float] = []
        last: ProbeResult | None = None
        for _ in range(max(1, frames)):
            result = self._probe.infer_once(model_id, image.pixels, spec)
            samples.append(result.inference_ms)
            last = result

        if last is None:  # pragma: no cover — `max(1, frames)` garantit une passe
            message = "Aucune mesure retenue : la boucle d'échantillonnage est vide."
            raise RuntimeError(message)
        return samples, last

    def _release(self, model_id: str, *, was_loaded: bool) -> bool:
        """Libère le modèle après sa mesure (règle 5).

        **Y compris s'il était déjà résident avant le run.** C'est un choix, et il
        mérite d'être défendu : le but de la libération est de ne pas laisser vingt
        modèles en mémoire, et un modèle résident sans bail est justement le
        candidat que l'utilisateur veut voir partir. Un modèle réellement occupé
        par une analyse en cours est protégé — le registre refuse de le décharger,
        et la ligne rapporte `released: false`.
        """
        del was_loaded  # documenté ci-dessus : la résidence antérieure ne protège pas
        try:
            return self._probe.release(model_id)
        except Exception as exc:  # pragma: no cover — garde-fou
            logger.warning("libération en échec", model_id=model_id, error=str(exc))
            return False

    # ── Transitions et publication ───────────────────────────────────────────

    async def _transition(self, run: BenchmarkRun, status: BenchmarkStatus) -> None:
        run.status = status
        await self._repository.set_status(run.id, status)
        self._publish(run)

    async def _finish(
        self, run: BenchmarkRun, status: BenchmarkStatus, *, error: str | None = None
    ) -> None:
        run.status = status
        run.error = error
        await self._repository.set_status(run.id, status, error=error)
        self._publish(run, terminal=True)

    def _publish(self, run: BenchmarkRun, *, terminal: bool = False) -> None:
        """Publie l'état courant dans le hub de progression.

        Le **même** hub que celui des jobs, et le même protocole SSE : un second
        mécanisme de diffusion serait un second endroit où corriger le bug de
        tamponnage des proxys.
        """
        self._hub.publish(
            ProgressEvent(run.id, describe(run), terminal=terminal or is_terminal(run.status))
        )


def _user_message(exc: Exception, model_id: str) -> str:
    """Message français destiné à l'utilisateur, jamais une trace de pile.

    Le `detail` d'une `AppError` est déjà écrit pour être lu par un humain : on le
    reprend tel quel. Pour tout le reste, un message générique — le détail
    technique va au journal, où il est corrélable par `requestId`.
    """
    from traffic_analysis.core.errors import AppError

    if isinstance(exc, AppError):
        return exc.detail
    return f"Le modèle « {model_id} » n'a pas pu être mesuré sur cette machine."


def describe(run: BenchmarkRun) -> dict[str, Any]:
    """Le run tel que l'API l'expose — **une seule forme**, SSE comme JSON.

    Une seule fonction pour les deux transports : deux sérialisations du même
    objet finissent par diverger, et le client ne sait plus laquelle croire.
    """
    fastest = run.fastest()
    return {
        "runId": run.id,
        "status": run.status,
        "progress": round(run.progress, 4),
        "completed": run.completed,
        "total": run.total,
        "error": run.error,
        "device": run.device,
        "half": run.half,
        "ultralyticsVersion": run.ultralytics_version,
        "frames": run.frames,
        "imageSource": run.image_source,
        "imageHash": run.image_hash,
        "imageWidth": run.image_width,
        "imageHeight": run.image_height,
        "jobId": run.job_id,
        "confidenceThreshold": run.confidence_threshold,
        "iouThreshold": run.iou_threshold,
        "fastestModelId": fastest.model_id if fastest else None,
        "entries": [describe_entry(entry) for entry in run.entries],
    }


def describe_entry(entry: BenchmarkEntry) -> dict[str, Any]:
    """Une ligne du tableau. Les durées sont arrondies au centième de ms.

    Arrondies à l'affichage seulement : la base garde la valeur brute, parce
    qu'agréger des valeurs déjà arrondies accumule l'erreur.
    """
    return {
        "modelId": entry.model_id,
        "label": entry.label,
        "tier": entry.tier,
        "loadMs": round(entry.load_ms, 2),
        "medianMs": round(entry.median_ms, 2),
        "p95Ms": round(entry.p95_ms, 2),
        "minMs": round(entry.min_ms, 2),
        "maxMs": round(entry.max_ms, 2),
        "fps": round(entry.fps, 2),
        "preprocessMs": (
            round(entry.preprocess_ms, 2) if entry.preprocess_ms is not None else None
        ),
        "postprocessMs": (
            round(entry.postprocess_ms, 2) if entry.postprocess_ms is not None else None
        ),
        "detections": entry.detections,
        "frames": entry.frames,
        "wasLoaded": entry.was_loaded,
        "released": entry.released,
        "error": entry.error,
    }
