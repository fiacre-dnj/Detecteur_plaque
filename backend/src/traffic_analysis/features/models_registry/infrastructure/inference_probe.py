"""Adaptateur de mesure : une inférence chronométrée par le registre de modèles.

Ce module satisfait le port `InferenceProbe` de la feature `benchmark` en
s'appuyant sur `ModelRegistry`.

**Il vit ici et non dans `benchmark/infrastructure/` pour une raison
d'architecture**, et le test `tests/test_architecture.py` l'exige : seul
`models_registry` a le droit de toucher son propre registre. Un adaptateur logé
côté benchmark devrait fouiller dans l'`infrastructure` d'une autre feature — et
c'est exactement la frontière que la règle protège. Le sens de la dépendance est
donc inversé : `models_registry` connaît le **port publié** de `benchmark`
(sa couche `application`), et l'implémente.

Trois points méritent d'être lus avant d'y toucher.

**`predict` et non `track`.** Le benchmark mesure une inférence sur une image
fixe, répétée. Un tracker garde un état entre les appels — matrices de coût,
galerie ReID, compensation de mouvement — donc la deuxième mesure ne serait pas
comparable à la première, et le tableau afficherait une dérive au lieu d'une
performance.

**Un bail par inférence.** C'est l'invariant 9, et il vaut ici comme ailleurs :
deux usages simultanés de la même instance mélangeraient leurs états. Le bail
protège aussi l'instance de l'éviction LRU pendant qu'on la mesure — être évincé
au milieu d'une série ferait rentrer un rechargement dans le temps d'inférence.

**L'horloge murale est légitime.** `perf_counter` autour de l'appel est une
**mesure de performance**, pas un horodatage métier : c'est l'exception explicite
de l'invariant 1. `perf_counter` et non `time.time` — cette dernière peut reculer
si le système ajuste son horloge, ce qui produirait une durée négative.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from traffic_analysis.core.logging import get_logger
from traffic_analysis.features.benchmark.application.ports import ProbeResult

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from traffic_analysis.features.benchmark.application.ports import ProbeSpec
    from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry

logger = get_logger("traffic_analysis.benchmark")


class RegistryInferenceProbe:
    """Mesure un modèle du catalogue via le registre qui le détient."""

    __slots__ = ("_registry",)

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def describe(self, model_id: str) -> tuple[str, str]:
        """Libellé et palier. Lève `UnknownModelError` si l'identifiant est faux.

        Le palier vient du catalogue et **jamais du nom de fichier de poids**
        (invariant 10) : c'est le catalogue qui le porte, et c'est la seule raison
        pour laquelle le modèle de plaques n'a jamais paru mal rangé ici.
        """
        descriptor = self._registry.describe(model_id)
        return descriptor.label, descriptor.tier

    def is_loaded(self, model_id: str) -> bool:
        return model_id in self._registry.loaded_ids()

    def load(self, model_id: str) -> None:
        """Charge l'instance sans l'utiliser.

        Le bail est pris et rendu immédiatement : ce qu'on veut, c'est que le
        chargement ait eu lieu et que l'instance soit résidente. La garder sous
        bail jusqu'à la fin de la série serait plus économe d'un point de vue
        comptable, et rendrait `load_ms` inséparable de la première inférence —
        or c'est précisément ce que la colonne « chargement » sert à distinguer.
        """
        with self._registry.lease(model_id):
            pass

    def infer_once(
        self, model_id: str, image: npt.NDArray[np.uint8], spec: ProbeSpec
    ) -> ProbeResult:
        """Une inférence chronométrée, **sans suivi**."""
        with self._registry.lease(model_id) as model:
            started = perf_counter()
            results = model.predict(
                image,
                conf=spec.confidence,
                iou=spec.iou,
                classes=list(spec.class_ids),
                device=self._registry.device(),
                half=self._registry.half(),
                verbose=False,
            )
            elapsed_ms = (perf_counter() - started) * 1000.0

        result = results[0] if results else None
        return ProbeResult(
            inference_ms=elapsed_ms,
            detections=_count_detections(result),
            preprocess_ms=_speed_of(result, "preprocess"),
            postprocess_ms=_speed_of(result, "postprocess"),
        )

    def release(self, model_id: str) -> bool:
        """Décharge l'instance. `False` si elle est occupée par une analyse.

        Le registre refuse de décharger une instance sous bail : c'est ce qui
        garantit qu'un benchmark lancé pendant une analyse ne lui arrache pas son
        modèle. Le refus remonte tel quel dans la ligne (`released: false`), et
        c'est une information utile, pas un échec.
        """
        return self._registry.unload(model_id)

    def device(self) -> str:
        return self._registry.device()

    def half(self) -> bool:
        return self._registry.half()

    def ultralytics_version(self) -> str:
        return self._registry.ultralytics_version()


def _count_detections(result: Any) -> int:  # noqa: ANN401 — `Results` n'est pas typé
    """Nombre de détections retenues **après** application des seuils.

    Rend 0 plutôt que de lever quand `boxes` est absent : une image sans véhicule
    est un résultat légitime, et sur un moteur qui ne remplit pas `boxes` le
    benchmark doit tout de même rapporter ses temps.
    """
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return 0
    try:
        return len(boxes)
    except TypeError:  # pragma: no cover — moteur exotique
        return 0


def _speed_of(result: Any, key: str) -> float | None:  # noqa: ANN401
    """Lit `result.speed[key]`, ou `None` si le moteur ne l'expose pas.

    `None` et non `0.0` : un zéro se lirait comme « instantané », alors que
    l'information est simplement absente. La distinction est visible dans le
    tableau, où la colonne affiche « — ».
    """
    speed = getattr(result, "speed", None)
    if not isinstance(speed, dict):
        return None
    value = speed.get(key)
    if not isinstance(value, (int, float)):
        return None
    return float(value)
