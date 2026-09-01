"""Ce que le démarrage pose sur le matériel, et ce qu'il ne pose plus.

Deux réglages agissent **avant la première inférence** et n'ont aucun effet visible
ensuite : le budget de threads et l'autotune cuDNN. Aucun des deux ne lève quand il
échoue — ce sont des optimisations, et un service qui refuserait de démarrer parce
qu'il n'a pas pu les poser échangerait de la vitesse contre une panne.

C'est exactement pourquoi la **porte** mérite un test : si elle s'ouvrait par erreur,
personne ne le verrait. L'autotune cuDNN, notamment, coûtait **1,3× à 2,1× de cadence**
sur une analyse avec repérage de plaques (ADR 0033) sans jamais rien signaler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from asgi_lifespan import LifespanManager

from traffic_analysis.app_factory import create_app
from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry

if TYPE_CHECKING:
    from traffic_analysis.core.settings import Settings
    from traffic_analysis.features.counting.application.ports import DetectionTrackingEngine


async def _start(settings: Settings, engine: DetectionTrackingEngine) -> None:
    """Démarre l'application et l'arrête aussitôt : seul le `lifespan` nous intéresse."""
    app = create_app(settings, engine=engine)
    async with LifespanManager(app):
        pass


@pytest.fixture
def autotune_calls(monkeypatch: pytest.MonkeyPatch) -> list[None]:
    """Compte les appels à `enable_cudnn_autotune`, sans jamais toucher au matériel.

    La vraie méthode rend la main sans rien faire hors GPU, donc l'observer par son
    effet serait impossible en CI : `device="cpu"` dans les tests. On observe donc
    l'appel, qui est ce que la porte contrôle.
    """
    calls: list[None] = []

    def record(_self: Any) -> None:  # noqa: ANN401 — la signature de la vraie méthode
        calls.append(None)

    monkeypatch.setattr(ModelRegistry, "enable_cudnn_autotune", record)
    return calls


async def test_l_autotune_cudnn_reste_ferme_par_defaut(
    settings: Settings, fake_engine: DetectionTrackingEngine, autotune_calls: list[None]
) -> None:
    """**Le défaut est fermé depuis ADR 0033.**

    L'autotune réétalonne cuDNN à chaque **nouvelle forme** d'entrée, et le détecteur de
    plaques lui en présente une par recadrage de véhicule : mesuré, six appels sur 124
    dépassaient la seconde et pesaient 73 % de son étage. Ce que l'autotune rendait en
    échange sur le chemin dont la forme est fixe : rien de mesurable.
    """
    assert settings.inference_cudnn_autotune is False

    await _start(settings, fake_engine)

    assert autotune_calls == []


async def test_le_reglage_ouvre_la_porte(
    settings: Settings, fake_engine: DetectionTrackingEngine, autotune_calls: list[None]
) -> None:
    """Le réglage existe pour une machine où la mesure dirait autre chose.

    S'il n'ouvrait plus rien, il serait un réglage mort — le pire état d'un réglage
    (ADR 0007 l'a déjà payé avec `plate_confidence`) : annoncé, documenté, et sans
    aucun effet.
    """
    # `model_copy` et non un `Settings(...)` neuf : les réglages du test portent des
    # chemins temporaires, et les reconstruire à la main les perdrait.
    await _start(settings.model_copy(update={"inference_cudnn_autotune": True}), fake_engine)

    assert autotune_calls == [None]


@pytest.fixture
def thread_budget_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Note `(threads, opencv_threads)` de chaque appel, sans toucher au matériel.

    Comme pour l'autotune : la vraie méthode ne fait rien quand les deux budgets
    valent zéro, donc l'observer par son effet serait impossible. On observe l'appel,
    qui est ce que la porte contrôle.
    """
    calls: list[tuple[int, int]] = []

    def record(_self: Any, threads: int, opencv_threads: int = 0) -> None:  # noqa: ANN401
        calls.append((threads, opencv_threads))

    monkeypatch.setattr(ModelRegistry, "apply_thread_budget", record)
    return calls


async def test_aucun_budget_pose_n_ouvre_pas_la_porte(
    settings: Settings,
    fake_engine: DetectionTrackingEngine,
    thread_budget_calls: list[tuple[int, int]],
) -> None:
    """Qui n'a rien posé ne paie pas l'import de torch, ni celui d'OpenCV."""
    assert settings.inference_threads == 0
    assert settings.opencv_threads == 0

    await _start(settings, fake_engine)

    assert thread_budget_calls == []


async def test_le_budget_torque_seul_ouvre_la_porte(
    settings: Settings,
    fake_engine: DetectionTrackingEngine,
    thread_budget_calls: list[tuple[int, int]],
) -> None:
    await _start(settings.model_copy(update={"inference_threads": 4}), fake_engine)

    assert thread_budget_calls == [(4, 0)]


async def test_le_budget_opencv_seul_ouvre_la_porte(
    settings: Settings,
    fake_engine: DetectionTrackingEngine,
    thread_budget_calls: list[tuple[int, int]],
) -> None:
    """**La panne silencieuse que ce test existe pour empêcher.**

    La garde ne portait que sur `inference_threads`. Poser `TRAFFIC_OPENCV_THREADS`
    seul laissait donc un réglage annoncé, documenté et **sans aucun effet** — le pire
    état d'un réglage, et celui qu'ADR 0007 a déjà payé avec `plate_confidence`.
    """
    await _start(settings.model_copy(update={"opencv_threads": 3}), fake_engine)

    assert thread_budget_calls == [(0, 3)]


async def test_les_deux_budgets_traversent_ensemble(
    settings: Settings,
    fake_engine: DetectionTrackingEngine,
    thread_budget_calls: list[tuple[int, int]],
) -> None:
    """Deux robinets distincts : celui de torch ne doit pas écraser celui d'OpenCV."""
    await _start(
        settings.model_copy(update={"inference_threads": 6, "opencv_threads": 3}),
        fake_engine,
    )

    assert thread_budget_calls == [(6, 3)]
