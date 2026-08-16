"""Ce que l'API voit du catalogue et de la mémoire.

Le service distingue **trois états** que la version précédente confondait sous un
seul `available` optimiste :

- `available` — le modèle est au catalogue ;
- `downloaded` — ses poids sont sur le disque ;
- `loaded` — une instance est résidente en mémoire.

C'est cette distinction qui évite le « pourquoi ma première analyse a mis
90 secondes » : l'interface peut annoncer « premier usage : téléchargement
~137 Mo » **avant** que l'utilisateur lance quoi que ce soit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio.to_thread

from traffic_analysis.features.models_registry.domain.catalogue import (
    TIER_LABELS,
    TIER_ORDER,
    ModelTier,
)

if TYPE_CHECKING:
    from traffic_analysis.features.counting.application.ports import PlateDetector, PlateReader
    from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Un modèle du catalogue, avec son état réel sur cette machine."""

    id: str
    label: str
    family: str
    tier: ModelTier
    tier_label: str
    note: str
    size_mb: int
    # Taille réelle sur disque quand le poids est présent ; `None` sinon. La
    # distinction compte : `size_mb` est une estimation du catalogue.
    size_bytes: int | None
    downloaded: bool
    loaded: bool
    is_default: bool


class ModelService:
    """Catalogue enrichi de l'état mémoire, préchargement, déchargement."""

    __slots__ = (
        "_default_model_id",
        "_plate_detector",
        "_plate_loadable",
        "_plate_reader",
        "_registry",
    )

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        default_model_id: str,
        plate_detector: PlateDetector | None = None,
        plate_reader: PlateReader | None = None,
    ) -> None:
        self._registry = registry
        self._default_model_id = default_model_id
        self._plate_detector = plate_detector
        self._plate_reader = plate_reader
        #: Verdict de l'auto-test, `None` tant qu'il n'a pas tourné. Trois états et
        #: non deux : « pas encore testé » n'est pas « en échec », et les afficher
        #: pareil ferait passer un démarrage sans préchauffage pour une panne.
        self._plate_loadable: bool | None = None

    def catalogue_with_state(self) -> list[ModelInfo]:
        loaded = set(self._registry.loaded_ids())
        return [
            ModelInfo(
                id=model.id,
                label=model.label,
                family=model.family,
                tier=model.tier,
                tier_label=TIER_LABELS[model.tier],
                note=model.note,
                size_mb=model.size_mb,
                size_bytes=self._registry.size_bytes(model.id),
                downloaded=self._registry.is_downloaded(model.id),
                loaded=model.id in loaded,
                is_default=model.id == self._default_model_id,
            )
            for model in self._registry.catalogue()
        ]

    def tiers(self) -> list[dict[str, str]]:
        """Paliers dans l'ordre d'affichage, avec leur libellé.

        Servis par l'API plutôt que codés en dur côté client : ajouter un palier
        ne doit demander qu'une ligne, dans le catalogue.
        """
        return [{"id": tier, "label": TIER_LABELS[tier]} for tier in TIER_ORDER]

    def device(self) -> str:
        return self._registry.device()

    def device_reason(self) -> str | None:
        """Pourquoi `device()` vaut ce qu'il vaut, déléguée à l'infrastructure.

        `None` seulement avant tout appel à `device()` — en pratique jamais côté
        API, puisque `/health` appelle toujours `device()` d'abord.
        """
        return self._registry.device_reason()

    def gpu_name(self) -> str | None:
        """Nom du GPU retenu, ou `None` hors GPU. Délégué pour la même raison que
        `device_reason` : l'application ne connaît aucune bibliothèque de vision."""
        return self._registry.gpu_name()

    def half(self) -> bool:
        return self._registry.half()

    def loaded_ids(self) -> list[str]:
        return self._registry.loaded_ids()

    def plate_available(self) -> bool:
        """Le **détecteur** de plaques est-il disponible ?"""
        return self._plate_detector is not None and self._plate_detector.available

    def plate_ocr_available(self) -> bool:
        """Le **lecteur** de plaques — modèle *et* dictionnaire — est-il disponible ?

        Distinct de `plate_available` : ce sont deux artefacts différents, récupérés
        par deux scripts différents, et l'état « détecteur présent, lecteur absent »
        est celui de tout déploiement neuf. Sans ce drapeau, l'interface proposerait
        une case « lire le texte » qui ne fait rien — précisément le mode de panne que
        `plateAvailable` avait été inventé pour éviter.
        """
        return self._plate_reader is not None and self._plate_reader.available

    def plate_loadable(self) -> bool | None:
        """Le détecteur de plaques a-t-il passé son auto-test ?

        `None` = pas encore testé (préchauffage désactivé, ou toujours en cours) ;
        `False` = les poids sont là et **ne se chargent pas**. C'est ce second état
        qui justifie le champ : `plate_available` seul ne peut pas le distinguer d'un
        fonctionnement normal, et ce projet a déjà passé un projet entier avec un
        drapeau vert et une ANPR muette.
        """
        return self._plate_loadable

    async def probe_plates(self) -> bool | None:
        """Lance l'auto-test du détecteur **dans un thread worker**, et retient son
        verdict.

        Dans un thread parce qu'il charge un modèle et lance une inférence : deux
        opérations bloquantes qui figeraient la boucle asyncio, et tout le service
        avec (invariant 11).

        Rend `None` sans rien tenter quand aucun détecteur n'est câblé ou que ses
        poids sont absents : l'absence est déjà dite par `plate_available`, et la
        répéter en « échec » ferait passer un déploiement neuf pour une panne.
        """
        detector = self._plate_detector
        if detector is None or not detector.available:
            return None
        self._plate_loadable = await anyio.to_thread.run_sync(detector.probe)
        return self._plate_loadable

    def ultralytics_version(self) -> str:
        """Version d'Ultralytics, déléguée à l'infrastructure.

        L'application ne connaît aucune bibliothèque de vision : c'est le
        registre qui sait, parce que c'est lui qui l'utilise.
        """
        return self._registry.ultralytics_version()

    async def preload(self, model_id: str) -> None:
        """Charge et préchauffe un modèle **dans un thread worker**.

        Le chargement est bloquant et peut inclure un téléchargement de 137 Mo :
        le laisser dans la boucle figerait tout le service pendant ce temps.

        **Le préchauffage prend un bail sur l'instance.** Si une session temps réel
        ou une analyse occupe déjà le même modèle, cet appel attend qu'elle rende
        son bail. C'est voulu — deux `track()` simultanés sur une même instance
        mélangeraient deux vidéos et produiraient des chiffres plausibles et faux
        (invariant 9) — mais cela signifie qu'une préparation peut durer sans qu'un
        seul octet soit téléchargé. Un appelant qui affiche « téléchargement en
        cours » se trompe donc parfois de cause ; il vaut mieux dire « préparation ».
        """
        self._registry.describe(model_id)  # 404 explicite avant de partir en thread
        await anyio.to_thread.run_sync(self._registry.warmup, model_id)

    async def prepare(self, model_id: str) -> None:
        """Le port `ModelPreparer` de la feature `jobs`, satisfait par `preload`.

        Un nom distinct plutôt qu'un port qui citerait `preload` : du point de vue
        d'un job, l'opération est « rendre ce modèle utilisable », et le fait
        qu'elle passe par un préchauffage est un détail de cette implémentation.
        Les deux noms cohabitent sans coût — la route HTTP garde `preload`, qui dit
        ce que l'utilisateur demande.
        """
        await self.preload(model_id)

    def unload(self, model_id: str) -> bool:
        self._registry.describe(model_id)
        return self._registry.unload(model_id)
