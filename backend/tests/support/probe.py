"""Sonde de mesure factice, pour tester le **protocole** sans matériel.

Comme `FakeEngine`, elle satisfait le port sans en hériter. Elle est
volontairement instrumentée : le protocole de mesure se vérifie par ce qu'il
*appelle*, pas seulement par ce qu'il rend. Trois compteurs comptent :

- `infer_calls` — pour prouver que le run de chauffe a bien lieu **et** est écarté
  (`1 + frames` appels, pour `frames` mesures retenues) ;
- `load_calls` — pour prouver qu'un modèle déjà résident n'est pas rechargé ;
- `released` — pour prouver que chaque modèle est libéré après sa mesure.

Les durées sont **scriptées** et non aléatoires : la médiane et le p95 attendus
d'une série connue sont calculables à la main, donc le test affirme un nombre au
lieu de vérifier vaguement qu'il est « plausible ».
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from traffic_analysis.core.errors import UnknownModelError
from traffic_analysis.features.benchmark.application.ports import ProbeResult, ReferenceImage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import numpy.typing as npt

    from traffic_analysis.features.benchmark.application.ports import ProbeSpec

# Modèles factices. Des identifiants qui ne sont **pas** au catalogue : un test du
# protocole ne doit pas dépendre du contenu du catalogue réel, qui bougera.
FAKE_MODELS: dict[str, tuple[str, str]] = {
    "fake-nano": ("Factice nano", "nano"),
    "fake-large": ("Factice large", "large"),
}


class FakeProbe:
    """Rend des durées scriptées et enregistre ce que le service lui demande."""

    def __init__(
        self,
        *,
        durations: Sequence[float] = (10.0, 12.0, 11.0, 40.0, 11.5),
        detections: int = 3,
        loaded: Sequence[str] = (),
        fail_on: Sequence[str] = (),
        refuse_release: Sequence[str] = (),
        expose_speed: bool = True,
        models: dict[str, tuple[str, str]] | None = None,
        after_release: Callable[[str], None] | None = None,
        block_s: float = 0.0,
    ) -> None:
        self._after_release = after_release
        self._durations = list(durations)
        self._detections = detections
        self._loaded = set(loaded)
        # Attente **bloquante** par inférence. Elle rend la sonde réaliste pour les
        # tests qui ont besoin qu'un run soit encore en cours quand ils l'observent
        # — le flux SSE, notamment. Bloquante et non `await` : la vraie mesure
        # bloque un thread worker, et c'est cette propriété qu'on veut reproduire.
        self._block_s = block_s
        # Modèles qui échouent au chargement : c'est le chemin « un poids ne se
        # télécharge pas », qui ne doit **pas** interrompre le run.
        self._fail_on = set(fail_on)
        # Modèles que le registre refuse de libérer parce qu'ils sont occupés par
        # une analyse en cours. La ligne doit alors rapporter `released: false`.
        self._refuse_release = set(refuse_release)
        self._expose_speed = expose_speed
        self._models = dict(models or FAKE_MODELS)

        self.infer_calls: list[str] = []
        self.load_calls: list[str] = []
        self.release_calls: list[str] = []
        # Position dans la série de durées, **par modèle** : deux modèles mesurés
        # dans le même run doivent voir la même série, sinon comparer leurs
        # médianes ne voudrait rien dire.
        self._positions: dict[str, int] = {}

    # ── Port ─────────────────────────────────────────────────────────────────

    def describe(self, model_id: str) -> tuple[str, str]:
        if model_id not in self._models:
            raise UnknownModelError(f"Le modèle « {model_id} » n'existe pas au catalogue.")
        return self._models[model_id]

    def is_loaded(self, model_id: str) -> bool:
        return model_id in self._loaded

    def load(self, model_id: str) -> None:
        self.load_calls.append(model_id)
        if model_id in self._fail_on:
            message = f"Poids indisponibles pour « {model_id} »."
            raise RuntimeError(message)
        self._loaded.add(model_id)

    def infer_once(
        self,
        model_id: str,
        image: npt.NDArray[np.uint8],  # noqa: ARG002
        spec: ProbeSpec,  # noqa: ARG002
    ) -> ProbeResult:
        """Rend la durée suivante de la série, en bouclant si elle est épuisée.

        La **première** durée de la série est donc celle du run de chauffe : c'est
        ce qui permet à un test de prouver que la chauffe est écartée, en plaçant
        une valeur aberrante en tête et en vérifiant qu'elle n'entre pas dans la
        médiane.
        """
        self.infer_calls.append(model_id)
        if self._block_s:
            from time import sleep

            sleep(self._block_s)
        position = self._positions.get(model_id, 0)
        self._positions[model_id] = position + 1
        return ProbeResult(
            inference_ms=self._durations[position % len(self._durations)],
            detections=self._detections,
            preprocess_ms=1.5 if self._expose_speed else None,
            postprocess_ms=0.8 if self._expose_speed else None,
        )

    def release(self, model_id: str) -> bool:
        self.release_calls.append(model_id)
        if model_id in self._refuse_release:
            return False
        self._loaded.discard(model_id)
        if self._after_release is not None:
            # Point d'accroche pour les tests d'annulation : `release` est le
            # dernier geste de la mesure d'un modèle, donc s'y brancher revient à
            # agir « entre deux modèles » — exactement là où le run observe le
            # drapeau d'annulation.
            self._after_release(model_id)
        return True

    def device(self) -> str:
        return "cpu"

    def half(self) -> bool:
        return False

    def ultralytics_version(self) -> str:
        return "8.3.0-factice"

    # ── Pilotage et inspection par les tests ─────────────────────────────────

    def make_unloadable(self, model_id: str) -> None:
        """Fait échouer le chargement de ce modèle.

        Pilotage après construction, pour les tests qui reçoivent la sonde par
        fixture et ne peuvent donc pas la paramétrer à l'instanciation.
        """
        self._fail_on.add(model_id)

    def make_busy(self, model_id: str) -> None:
        """Simule un modèle occupé par une analyse : le registre refuse de le libérer."""
        self._loaded.add(model_id)
        self._refuse_release.add(model_id)

    def loaded_ids(self) -> set[str]:
        """L'état de résidence, pour vérifier qu'un run le rend intact."""
        return set(self._loaded)

    def infer_calls_for(self, model_id: str) -> int:
        return sum(1 for called in self.infer_calls if called == model_id)


class FakeImageProvider:
    """Fournit une image de référence constante, au hash stable."""

    def __init__(
        self, *, width: int = 64, height: int = 48, job_error: Exception | None = None
    ) -> None:
        self._width = width
        self._height = height
        # Permet de tester le refus « la vidéo du job a été purgée » sans avoir à
        # fabriquer un job ni un fichier.
        self._job_error = job_error
        self.sample_calls = 0
        self.job_calls: list[str] = []

    def sample(self) -> ReferenceImage:
        self.sample_calls += 1
        return self._image("échantillon factice")

    def from_job(self, job_id: str) -> ReferenceImage:
        self.job_calls.append(job_id)
        if self._job_error is not None:
            raise self._job_error
        return self._image(f"frame du job {job_id}")

    def _image(self, source: str) -> ReferenceImage:
        pixels = np.full((self._height, self._width, 3), 120, dtype=np.uint8)
        return ReferenceImage(
            pixels=pixels,
            # Hash constant et lisible : un test qui affirme l'égalité de deux
            # hashs doit pouvoir dire lequel il attend.
            sha256="f" * 64,
            width=self._width,
            height=self._height,
            source=source,
        )
