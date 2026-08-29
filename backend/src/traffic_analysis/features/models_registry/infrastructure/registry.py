"""Résidence mémoire des modèles : bail, éviction LRU, préchauffage.

Responsabilités, et **rien d'autre** : cataloguer, charger paresseusement,
prêter, évincer, préchauffer, dire le device.

Deux règles y sont vitales :

- **Un bail par usage.** Deux `track()` simultanés sur la même instance
  partagent l'état de suivi et **mélangent deux vidéos** — des chiffres
  plausibles et complètement faux, que rien ne signale (piège 28 de prompt/13).
- **Un plafond de résidence.** Un modèle résident coûte des centaines de
  mégaoctets ; dix modèles résidents épuisent la mémoire. C'est la leçon du
  benchmark de la version précédente.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from traffic_analysis.core.errors import UnavailableError, UnknownModelError
from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.models_registry.domain.catalogue import (
    CATALOGUE,
    ModelDescriptor,
    find,
    known_ids,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = get_logger("traffic_analysis.models")

WARMUP_SIDE = 640

#: Forme du fond soumis au préchauffage : **celle d'une vidéo**, pas un carré.
#:
#: Le préchauffage soumettait un carré `640×640` sans `imgsz`, quand la production
#: soumet un letterbox rectangulaire — une source 16:9 entre en `384×640`, et par lot.
#: Or `BasePredictor.stream_inference` pose `done_warmup = True` après cette passe et
#: le prédicteur est réutilisé : **la forme réellement analysée ne bénéficiait donc
#: d'aucune chauffe du backend**.
#:
#: Mesuré en courses **alternées, processus neuf à chaque fois**, lot de 4 en 1080p :
#:
#: | préchauffage | 1ᵉʳ lot | régime |
#: |---|---|---|
#: | carré 640, lot 1 (avant) | 85,5 puis 76,6 ms | ~41,5 ms |
#: | forme de production (après) | **65,3 puis 65,8 ms** | ~41,7 ms |
#:
#: Soit **~15 ms par job**, une seule fois — et non les 45 qu'une lecture optimiste
#: du premier micro-banc laissait espérer. Le gain le plus net n'est d'ailleurs pas
#: la moyenne mais la **reproductibilité** : ±0,5 ms contre ±9 avant.
#:
#: Il reste ~24 ms d'hésitation qu'aucun préchauffage au démarrage ne peut retirer :
#: 16:9 est un choix par défaut — le rapport d'aspect de la vidéo n'est pas connu à
#: ce moment-là — et le **dernier lot** de chaque vidéo, plus court donc de forme
#: neuve, n'est de toute façon jamais chauffable.
#:
#: L'enjeu n'est pas le budget total (0,01 % d'une analyse de trois minutes) mais
#: l'endroit où l'hésitation tombe : sur la **première image d'aperçu**, celle qu'on
#: regarde pour savoir si ça a démarré.
WARMUP_HEIGHT = 1080
WARMUP_WIDTH = 1920


@dataclass(slots=True)
class _Resident:
    """Une instance chargée en mémoire, et le verrou qui en sérialise l'usage."""

    model: Any
    # Une instance occupée n'est **jamais** évincée : son bail est en cours
    # d'usage, et la retirer laisserait une analyse sans modèle en plein vol.
    busy: bool = False
    leases: int = field(default=0)
    #: **Le verrou d'exclusion mutuelle de l'invariant 9.**
    #:
    #: Sans lui, `leases` était un simple compteur d'usages concurrents : deux
    #: appelants recevaient la *même* instance et appelaient `model.track(...,
    #: persist=True)` en parallèle depuis deux threads. Le tracker BoT-SORT garde
    #: son état d'une frame à l'autre — les deux flux se mélangeaient, et le
    #: résultat était plausible et complètement faux. Aucune erreur, aucun journal.
    #:
    #: Le cas concret n'était pas théorique : `max_concurrent_jobs` borne les jobs
    #: entre eux et `max_realtime_sessions` les sessions entre elles, mais **rien**
    #: ne bornait un job et une session ensemble — et le conteneur les construit
    #: sur le même registre.
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelRegistry:
    """Prête des instances de modèle, une à la fois, sous plafond mémoire."""

    __slots__ = (
        "_configured_device",
        "_configured_half",
        "_device",
        "_device_reason",
        "_half",
        "_lock",
        "_max_loaded",
        "_residents",
        "_weights_dir",
    )

    def __init__(self, weights_dir: Path, *, max_loaded: int, device: str, half: bool) -> None:
        self._weights_dir = weights_dir
        self._max_loaded = max_loaded
        self._configured_device = device
        self._configured_half = half
        # `OrderedDict` : l'ordre d'insertion **est** l'ordre d'usage, donc le
        # candidat à l'éviction est simplement le premier.
        self._residents: OrderedDict[str, _Resident] = OrderedDict()
        # Le registre est appelé depuis des threads workers : l'état de résidence
        # doit être protégé. Le verrou n'est **jamais** tenu pendant un
        # chargement, qui peut durer le temps d'un téléchargement de 137 Mo.
        self._lock = threading.Lock()
        self._device: str | None = None
        self._half: bool | None = None
        #: Pourquoi `_device` vaut ce qu'il vaut — jamais recalculée après coup,
        #: mémorisée en même temps que `_device` pour rester cohérente avec elle.
        self._device_reason: str | None = None

    # ── Catalogue ────────────────────────────────────────────────────────────

    def catalogue(self) -> tuple[ModelDescriptor, ...]:
        return CATALOGUE

    def describe(self, model_id: str) -> ModelDescriptor:
        descriptor = find(model_id)
        if descriptor is None:
            raise UnknownModelError(
                f"Le modèle « {model_id} » n'existe pas au catalogue. "
                f"Modèles valides : {', '.join(known_ids())}."
            )
        return descriptor

    def weights_path(self, model_id: str) -> Path:
        return self._weights_dir / self.describe(model_id).weights

    def is_downloaded(self, model_id: str) -> bool:
        return self.weights_path(model_id).is_file()

    def size_bytes(self, model_id: str) -> int | None:
        """Taille réelle sur disque, ou `None` si le poids n'est pas là.

        Réelle et non celle du catalogue : cette dernière est indicative et sert
        seulement à annoncer un téléchargement avant qu'il ait lieu.
        """
        path = self.weights_path(model_id)
        return path.stat().st_size if path.is_file() else None

    # ── Matériel ─────────────────────────────────────────────────────────────

    def device(self) -> str:
        """Device effectif, résolu **une seule fois** puis mémorisé.

        `torch` est importé localement : les tests du domaine ne doivent jamais
        payer un import de deux secondes pour une valeur qu'ils n'utilisent pas.

        `device_reason()` explique **pourquoi** cette valeur a été retenue —
        distinction utile parce que « cpu » ne dit pas si c'est parce qu'aucun
        GPU n'a été trouvé, parce que la détection a échoué, ou parce que c'est
        ce que l'opérateur a demandé.
        """
        if self._device is not None:
            return self._device

        if self._configured_device != "auto":
            self._device = self._configured_device
            self._device_reason = "configuré explicitement"
            return self._device

        try:
            import torch

            if torch.cuda.is_available():
                self._device = "0"
                self._device_reason = "CUDA détecté"
            else:
                self._device = "cpu"
                self._device_reason = "aucun GPU CUDA détecté"
        except Exception as exc:
            logger.warning("torch indisponible — bascule sur CPU", error=str(exc))
            self._device = "cpu"
            self._device_reason = "torch indisponible"
        return self._device

    def device_reason(self) -> str | None:
        """Pourquoi `device()` vaut ce qu'il vaut. `None` avant tout appel à `device()`.

        Exposé séparément plutôt que concaténé à `device()` : le badge d'état du
        frontend affiche `device` seul, et cette explication n'a de sens que dans
        un panneau de diagnostic, pas accolée à chaque « cpu » du badge.
        """
        return self._device_reason

    def gpu_name(self) -> str | None:
        """Nom du GPU retenu par `torch.cuda.get_device_name`, ou `None`.

        `None` dans trois cas qu'on ne distingue pas ici — hors GPU, torch
        indisponible, ou l'appel a échoué malgré un device GPU résolu — parce
        qu'aucun des trois n'appelle un geste différent : dans les trois, il n'y a
        simplement rien à nommer. Ne lève jamais, pour la même raison que
        `ultralytics_version()` : c'est un champ de badge, pas un chemin critique.
        """
        device = self.device()
        if device == "cpu":
            return None
        try:
            import torch

            return str(torch.cuda.get_device_name(self._device_index()))
        except Exception:
            return None

    def _device_index(self) -> int:
        """Index CUDA du device retenu. `« cuda:0 »` comme `« 0 »` donnent 0.

        Toute forme non numérique retombe sur 0 : un device qu'on n'arrive pas à
        décomposer est le premier GPU dans tous les cas rencontrés, et les deux
        appelants (`gpu_name`, `_fp16_is_slow`) traitent déjà l'échec sans lever.
        """
        device = self.device()
        if device.isdigit():
            return int(device)
        _, _, suffix = device.partition(":")
        return int(suffix) if suffix.isdigit() else 0

    def _fp16_is_slow(self) -> bool:
        """Vrai **seulement si** le GPU retenu est connu pour calculer mal le fp16.

        Avant Volta (capability < 7.0), il n'y a pas de cœurs tensoriels et le fp16
        est calculé à une fraction du débit fp32 : mesuré sur une Quadro P1000
        (6.1, Pascal), yolov8n passe de **38,9 ms à 48,9 ms par image** en demi-
        précision — le réglage censé accélérer coûte 26 %.

        La question n'est donc pas « suis-je sur GPU » mais « ce GPU-ci calcule-t-il
        le fp16 vite », et c'est ce que `half()` demande désormais.

        **L'inconnu ne vaut pas un refus.** Si la capability n'est pas lisible —
        torch absent, device explicite sur une machine sans pilote — on rend `False`
        et le réglage de l'opérateur passe. Contredire un `half=True` explicite sur
        la foi d'une sonde qui vient d'échouer serait la même faute que le repli
        silencieux qu'`ADR 0011` interdit : on ne désactive que ce qu'on a mesuré.
        """
        try:
            import torch

            major, minor = torch.cuda.get_device_capability(self._device_index())
        except Exception:
            return False
        if major >= 7:
            return False
        logger.info(
            "fp16 désactivé : ce GPU le calcule plus lentement que le fp32",
            capability=f"{major}.{minor}",
            gpu=self.gpu_name(),
        )
        return True

    def half(self) -> bool:
        """fp16 **seulement sur un GPU qui le calcule vite**.

        Deux conditions, et il a fallu les deux :

        1. pas sur CPU. `half=True` n'y va pas plus vite, il ralentit, parce que
           les noyaux fp16 n'y sont pas optimisés (piège 30 de prompt/13) ;
        2. pas sur un GPU d'avant Volta. La même erreur s'y répète pour une autre
           raison matérielle — voir `_fp16_is_slow`.
        """
        if self._half is None:
            self._half = (
                self._configured_half and self.device() != "cpu" and not self._fp16_is_slow()
            )
        return self._half

    def _fall_back_to_cpu(self, reason: str) -> None:
        """Invalide un device GPU déjà mémorisé et repose « cpu » à sa place.

        **Réservé au repli après un échec réel d'inférence** (voir `warmup`) :
        `torch.cuda.is_available()` peut répondre vrai alors que la première
        inférence réelle échoue — pilote incomplet, VRAM insuffisante, CUDA mal
        installé. Sans ce repli, le service resterait configuré sur un device qui
        vient de démontrer qu'il ne fonctionne pas, et chaque analyse ultérieure
        échouerait de la même façon sans que rien ne corrige le diagnostic.

        `_half` est invalidé avec `_device` : un GPU disparu ne doit pas laisser
        `half=True` actif sur le CPU qui prend sa place (piège 30 de prompt/13).
        """
        self._device = "cpu"
        self._device_reason = reason
        self._half = None

    def apply_thread_budget(self, threads: int, opencv_threads: int = 0) -> None:
        """Borne les threads CPU de torch **et** ceux d'OpenCV. `0` ne fait rien.

        **Appelée une fois au démarrage, avant toute inférence.** `set_num_threads`
        redimensionne un pool déjà créé, mais le faire en cours d'analyse changerait
        la cadence au milieu d'une mesure.

        Sans effet sur GPU pour torch : l'inférence n'y vit pas sur ces threads. On
        l'applique quand même sans condition, parce que le pré et le post-traitement,
        eux, restent sur CPU.

        **`opencv_threads` est un second robinet, et il en fallait un.** Au repos,
        OpenCV prend *tous* les processeurs logiques (12 mesurés ici) quand torch en
        prend 6, et rien ne les arbitrait : `threads` ne touche que torch. Or le
        prétraitement d'Ultralytics est du pur OpenCV et tourne dans le fil qui
        attend le GPU, pendant que `decode_ahead` décode dans un autre — la
        contention qu'ADR 0031 nomme comme la cause de son gain non réalisé en 720p
        et 1080p, sans qu'aucun réglage ne la borne.

        **Ce que ce robinet ne couvre pas, et c'est délibéré.**
        `cv2.setNumThreads` borne le `parallel_for_` — `resize`, `copyMakeBorder`,
        `cvtColor`, `Laplacian`, `imencode` — c'est-à-dire le prétraitement, qui est
        sur le chemin critique. Il ne borne **pas** le pool du décodeur FFmpeg, qui
        se pose par capture (`CAP_PROP_N_THREADS` ; ce build n'expose aucune variable
        d'environnement pour lui). Ce second robinet n'est pas posé : le décodage vit
        dans son propre fil depuis ADR 0031, donc hors du chemin critique, et son
        effet n'a pas été mesuré ici. Poser un réglage dont on n'a pas mesuré l'effet
        est exactement ce que ce dépôt refuse.

        **Défaut `0`, et c'est mesuré, pas prudent** : machine libre, OpenCV à 3 fils
        au lieu de 12 fait *perdre* 3,4 % au chemin d'inférence ; avec un fil OpenCV
        concurrent, il en fait *gagner* 9,7 puis 10,2 %. L'échange change de signe
        selon la charge et le nombre de cœurs — un défaut non nul serait juste ici et
        faux ailleurs. Même doctrine que `inference_threads`.

        Ne lève jamais. Un budget de threads est un confort d'exécution ; un service
        qui refuserait de démarrer parce qu'il n'a pas pu le poser échangerait une
        gêne contre une panne.
        """
        if threads > 0:
            try:
                import torch

                torch.set_num_threads(threads)
                # Le pool inter-op ne se redimensionne pas après la première inférence,
                # et lève alors plutôt que d'ignorer. Toléré séparément : borner
                # l'intra-op est l'essentiel du gain.
                with suppress(Exception):
                    torch.set_num_interop_threads(max(1, threads // 2))
                logger.info("budget de threads d'inférence posé", threads=threads)
            except Exception as exc:
                logger.warning("budget de threads non appliqué", error=str(exc))

        if opencv_threads > 0:
            try:
                import cv2

                before = cv2.getNumThreads()
                cv2.setNumThreads(opencv_threads)
                logger.info(
                    "budget de threads OpenCV posé",
                    threads=opencv_threads,
                    avant=before,
                )
            except Exception as exc:
                logger.warning("budget de threads OpenCV non appliqué", error=str(exc))

    def enable_cudnn_autotune(self) -> None:
        """Laisse cuDNN choisir ses algorithmes de convolution par la mesure.

        **Désactivée par défaut depuis ADR 0033**, et n'appelée que si
        `TRAFFIC_INFERENCE_CUDNN_AUTOTUNE` le demande. Ce qui suit explique pourquoi,
        parce que c'est le premier endroit où l'on vient regarder.

        **La prémisse de cette optimisation était fausse pour la moitié du pipeline.**
        Elle disait : « les premières images d'une nouvelle forme d'entrée coûtent plus
        cher, mais notre forme est fixe pour une vidéo donnée — `imgsz` est un réglage,
        la résolution ne change pas en cours de route — donc l'étalonnage est amorti dès
        les premières images ». C'est exact du **détecteur de véhicules**, qui reçoit
        toujours des images de la même taille. C'est faux du **détecteur de plaques**,
        qui reçoit un recadrage de véhicule par piste : Ultralytics impose `rect=True`
        en prédiction, donc un recadrage soumis **seul** produit une forme d'entrée qui
        dépend de son rapport d'aspect, et cuDNN réétalonne à chaque nouvelle forme.

        Mesuré sur une scène clairsemée réelle : **six appels sur 124 dépassaient la
        seconde et pesaient 73 % du temps de l'étage de plaques**, l'analyse tournant à
        8,4 img/s au lieu de 18,2 — pour des détections et des plaques publiées
        **strictement identiques**. Ce que l'autotune rendait en échange, sur le chemin
        dont la forme *est* fixe : 7,92 ms d'inférence contre 8,00 sans, soit rien.

        **Appelée une fois au démarrage, avant toute inférence**, comme
        `apply_thread_budget` et pour la même raison : le choix est mémorisé par forme
        d'entrée, et le déclencher au milieu d'une analyse ferait payer l'étalonnage à
        une image en plein vol.

        Sans effet hors GPU, et sans effet si torch est absent. Ne lève jamais :
        c'est une optimisation, et un service qui refuserait de démarrer parce
        qu'il n'a pas pu l'activer échangerait de la vitesse contre une panne.
        """
        if self.device() == "cpu":
            return
        try:
            import torch

            torch.backends.cudnn.benchmark = True
            logger.info("autotune cuDNN activé")
        except Exception as exc:
            logger.warning("autotune cuDNN non activé", error=str(exc))

    def loaded_ids(self) -> list[str]:
        with self._lock:
            return list(self._residents)

    def ultralytics_version(self) -> str:
        """Version d'Ultralytics, ou « indisponible ».

        Une chaîne et jamais une exception : cette valeur est affichée dans le
        badge d'état du frontend, et un badge ne doit pas faire tomber une page.
        """
        try:
            import ultralytics
        except Exception:
            return "indisponible"
        return str(getattr(ultralytics, "__version__", "inconnue"))

    # ── Bail ─────────────────────────────────────────────────────────────────

    @contextmanager
    def lease(self, model_id: str) -> Iterator[Any]:
        """Réserve une instance **en exclusivité** pour la durée de l'usage.

        Deux garanties, et il a fallu les deux :

        1. l'instance est marquée occupée, donc à l'abri de l'éviction — la
           retirer laisserait une analyse sans modèle en plein vol ;
        2. **un seul appelant à la fois** l'utilise réellement. Un second bail sur
           le même modèle *attend* que le premier soit rendu.

        La seconde manquait, et c'est l'invariant 9 du projet. `leases` ne comptait
        que les usages concurrents sans jamais les empêcher : deux appelants
        recevaient la même instance et lançaient `model.track(..., persist=True)`
        en parallèle. Le tracker garde son état d'une frame à l'autre, donc les
        deux flux se mélangeaient — des chiffres plausibles et complètement faux,
        sans la moindre erreur.

        **Le bail attend plutôt que de refuser.** Un refus obligerait chaque
        appelant à gérer une indisponibilité transitoire, alors que le travail est
        déjà mis en file en amont (`max_concurrent_jobs`, `max_realtime_sessions`).
        Attendre est ici le comportement correct : l'analyse suivante démarre dès
        que la précédente rend la main.

        L'attente a lieu **hors** du verrou du registre : le tenir pendant une
        analyse de plusieurs minutes bloquerait jusqu'à la lecture du catalogue.
        """
        self.describe(model_id)  # 404 explicite avant tout chargement
        resident = self._acquire(model_id)
        # Sérialise l'usage réel. Acquis après `_acquire`, donc l'instance est déjà
        # comptée occupée et ne peut pas être évincée pendant qu'on attend son tour.
        with resident.lock:
            try:
                yield resident.model
            finally:
                with self._lock:
                    current = self._residents.get(model_id)
                    if current is not None:
                        current.leases = max(0, current.leases - 1)
                        current.busy = current.leases > 0

    def _acquire(self, model_id: str) -> _Resident:
        """Réserve l'instance et rend le **résident**, verrou compris.

        Le résident et non le modèle nu : l'appelant a besoin du verrou pour
        sérialiser l'usage, et le lui faire rechercher séparément rouvrirait une
        course entre l'obtention de l'instance et celle de son verrou.
        """
        with self._lock:
            resident = self._residents.get(model_id)
            if resident is not None:
                self._residents.move_to_end(model_id)
                resident.leases += 1
                resident.busy = True
                return resident

        # Chargement **hors verrou** : il peut durer le temps d'un téléchargement
        # de 137 Mo, et tenir le verrou bloquerait toute autre analyse.
        model = self._load(model_id)

        with self._lock:
            existing = self._residents.get(model_id)
            if existing is not None:
                # Une autre course a chargé le même modèle pendant ce temps :
                # on garde la sienne et on abandonne la nôtre au GC.
                self._residents.move_to_end(model_id)
                existing.leases += 1
                existing.busy = True
                return existing

            fresh = _Resident(model=model, busy=True, leases=1)
            self._residents[model_id] = fresh
            freed = self._evict_if_needed()

        # **Hors du verrou du registre, délibérément.** `cudaFree` synchronise
        # l'appareil : le faire sous verrou bloquerait toute demande de bail pendant
        # ce temps, y compris celles qui n'ont rien à voir avec l'éviction.
        self._release_vram(freed)
        return fresh

    def _evict_if_needed(self) -> list[str]:
        """Évince les plus anciennes instances **non occupées**, et dit lesquelles.

        Appelée sous verrou. Si toutes les instances résidentes sont occupées, on
        dépasse temporairement le plafond plutôt que d'arracher un modèle à une
        analyse en cours — dépasser est récupérable, pas l'autre.

        Rend la liste des évincées pour que l'appelant rende leur VRAM **après**
        avoir relâché le verrou : voir `_release_vram`.
        """
        freed: list[str] = []
        while len(self._residents) > self._max_loaded:
            victim = next(
                (name for name, resident in self._residents.items() if not resident.busy), None
            )
            if victim is None:
                logger.warning(
                    "plafond de modèles dépassé : toutes les instances sont occupées",
                    loaded=len(self._residents),
                    limit=self._max_loaded,
                )
                return freed
            del self._residents[victim]
            freed.append(victim)
            logger.info("modèle évincé", model_id=victim, limit=self._max_loaded)
        return freed

    def _release_vram(self, freed: Sequence[str]) -> None:
        """Rend au pilote la VRAM d'instances qu'on vient de laisser tomber.

        **`del` ne suffit pas, et la raison ne se devine pas.** Ultralytics crée un
        cycle de références en enregistrant le crochet du tracker :
        `predictor._hook = predictor.model.model.model[-1].register_forward_pre_hook(...)`
        où la fermeture capture `predictor`. Le module retient le crochet, le crochet
        retient le prédicteur, le prédicteur retient le modèle : le compteur de
        références ne tombe **jamais** à zéro, et les poids restent en VRAM jusqu'à un
        passage générationnel du ramasse-miettes, c'est-à-dire à un moment que
        personne ne contrôle.

        D'où `gc.collect()` **avant** `empty_cache()`, et pas à la place :
        `empty_cache` ne rend que des blocs **déjà libres** dans l'allocateur mis en
        cache de torch. Tant que le cycle tient l'objet, les blocs ne sont pas libres
        et l'appel ne rend rien — on aurait un correctif qui journalise un succès sans
        effet, exactement la famille de panne que ce dépôt collectionne.

        **Quand c'est utile, et quand c'est du folklore coûteux.** Utile ici, parce
        qu'une éviction change le profil de tailles d'allocation (on passe d'un palier
        à un autre) et que la carte de cette machine n'a que 4 Go, partagés avec le
        compositeur du bureau. Folklore coûteux **par image ou par lot** — l'allocateur
        réutiliserait ses blocs gratuitement, et les rendre force un `cudaMalloc` neuf
        qui sérialise avec l'appareil — et **en fin de bail**, où rien n'a été libéré
        puisque le modèle reste résident.

        Ne rend pas les poids à l'hôte par `.to("cpu")` : l'objet est jeté juste après,
        donc ce serait copier 137 Mo pour les détruire.

        Ne lève jamais : rendre de la mémoire est un confort, pas une garantie.
        """
        if not freed or self.device() == "cpu":
            return
        try:
            import gc

            import torch

            before = torch.cuda.memory_reserved()
            gc.collect()
            torch.cuda.empty_cache()
            logger.info(
                "VRAM rendue après éviction",
                modeles=list(freed),
                reserve_avant_mio=before // 2**20,
                reserve_apres_mio=torch.cuda.memory_reserved() // 2**20,
            )
        except Exception as exc:
            logger.warning("libération VRAM impossible", error=str(exc))

    def _load(self, model_id: str) -> Any:  # noqa: ANN401
        descriptor = self.describe(model_id)
        self._weights_dir.mkdir(parents=True, exist_ok=True)
        target = self._weights_dir / descriptor.weights

        try:
            from ultralytics import YOLO  # type: ignore[attr-defined]
        except Exception as exc:
            raise UnavailableError(
                "Ultralytics n'est pas installé sur ce serveur : aucune analyse n'est possible.",
                code="engine_unavailable",
            ) from exc

        logger.info(
            "chargement du modèle",
            model_id=model_id,
            downloaded=target.is_file(),
            device=self.device(),
        )
        try:
            # Chemin absolu quand le poids est déjà là : sinon Ultralytics croit
            # à un identifiant et retélécharge.
            model = YOLO(str(target) if target.is_file() else descriptor.weights)
        except Exception as exc:
            raise UnavailableError(
                f"Le modèle « {model_id} » n'a pas pu être chargé "
                f"(téléchargement impossible ou poids corrompu).",
                code="model_unavailable",
            ) from exc

        self._tidy_downloaded_weights(descriptor, target)
        return model

    def _tidy_downloaded_weights(self, descriptor: ModelDescriptor, target: Path) -> None:
        """Range le poids qu'Ultralytics a déposé dans le répertoire courant.

        Ultralytics télécharge dans le CWD quand le fichier n'existe pas au chemin
        demandé. Sans ce déplacement, chaque démarrage retéléchargerait le même
        modèle, et le répertoire de travail se remplirait de `.pt`.
        """
        if target.is_file():
            return
        stray = Path.cwd() / descriptor.weights
        if stray.is_file():
            stray.replace(target)
            logger.info("poids rangé", model_id=descriptor.id, path=str(target))

    # ── Préchauffage et déchargement ─────────────────────────────────────────

    def warmup(self, model_id: str, *, batch: int = 1, imgsz: int = WARMUP_SIDE) -> None:
        """Une inférence à vide, pour que la première requête réelle ne paie pas.

        Le premier appel d'un modèle inclut son chargement **et** sa fusion de
        couches : sans préchauffage, il se lit comme un blocage de plusieurs
        dizaines de secondes (piège 31 de prompt/13).

        **C'est aussi la seule vérification réelle du GPU choisi.**
        `torch.cuda.is_available()` (dans `device()`) ne fait qu'interroger le
        pilote ; il peut répondre vrai alors qu'une inférence échoue quand même —
        pilote incomplet, VRAM déjà saturée par un autre processus, build CUDA
        incompatible. Si cette première inférence réelle échoue sur un device
        auto-détecté (pas explicitement demandé par l'opérateur), on retombe sur
        CPU et on retente une fois : mieux vaut démarrer plus lentement que rester
        configuré sur un device qui vient de démontrer qu'il ne fonctionne pas, et
        faire échouer de la même façon chaque analyse jusqu'au prochain redémarrage.

        Un échec est **journalisé, pas fatal** : mieux vaut un service qui démarre
        et qui sera lent une fois qu'un service qui refuse de démarrer.

        **`batch` et `imgsz` servent à chauffer la forme de production**, et pas une
        autre : voir `WARMUP_HEIGHT`. Le fond est une image de vidéo, pas un carré,
        parce que le letterbox d'Ultralytics en tire la forme réelle du tenseur.

        **Jamais par `track()`, et c'est le piège de ce correctif.**
        `on_predict_start` sort immédiatement quand `predictor.trackers` existe et que
        `persist` est vrai : chauffer par `track` construirait un tracker au démarrage,
        depuis le fichier de **base**, et le premier job réel ne relirait jamais son
        fichier dérivé. `reset_trackers` repose `REQUEST_TRACKER_KEYS` mais **pas**
        `with_reid`, consommé à la construction — ce serait ADR 0047 défait en
        silence, soit 4× de cadence perdue sur une tête `end2end`. `predict` ne
        construit aucun tracker et n'avance pas `BaseTrack._count` (invariant 7).
        """
        try:
            import numpy as np

            blank = np.zeros((WARMUP_HEIGHT, WARMUP_WIDTH, 3), dtype=np.uint8)
            source = [blank] * max(1, batch)
            try:
                with self.lease(model_id) as model:
                    model.predict(
                        source,
                        imgsz=imgsz,
                        verbose=False,
                        device=self.device(),
                        half=self.half(),
                    )
            except Exception as exc:
                # Un device explicitement demandé (`device != "auto"`) reste tel
                # quel : l'opérateur a fait ce choix, et le retourner en silence
                # masquerait une configuration fausse plutôt que de la signaler.
                if self._configured_device != "auto" or self.device() == "cpu":
                    raise
                logger.warning(
                    "échec d'inférence sur le device détecté — repli CPU",
                    model_id=model_id,
                    device=self.device(),
                    error=str(exc),
                )
                self._fall_back_to_cpu("échec d'inférence GPU au préchauffage, repli CPU")
                # Mêmes arguments que la première tentative : un repli qui chaufferait
                # une autre forme laisserait la production payer son hésitation quand
                # même, et le repli passerait pour un correctif sans en être un.
                with self.lease(model_id) as model:
                    model.predict(
                        source,
                        imgsz=imgsz,
                        verbose=False,
                        device=self.device(),
                        half=self.half(),
                    )
            logger.info(
                "modèle préchauffé",
                model_id=model_id,
                device=self.device(),
                device_reason=self.device_reason(),
            )
        except Exception as exc:
            logger.warning("préchauffage en échec", model_id=model_id, error=str(exc))

    def unload(self, model_id: str) -> bool:
        """Décharge une instance résidente. Refuse si elle est occupée."""
        with self._lock:
            resident = self._residents.get(model_id)
            if resident is None:
                return False
            if resident.busy:
                logger.info("déchargement refusé : instance occupée", model_id=model_id)
                return False
            del self._residents[model_id]
        logger.info("modèle déchargé", model_id=model_id)
        # Même raison qu'à l'éviction, et même position : hors du verrou.
        self._release_vram([model_id])
        return True
