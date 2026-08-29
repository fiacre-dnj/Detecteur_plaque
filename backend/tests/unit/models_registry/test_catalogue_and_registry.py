"""Catalogue et résidence mémoire — sans charger un seul modèle réel.

Le registre est testé avec un faux chargeur : charger un vrai `.pt` en test
téléchargerait des dizaines de mégaoctets depuis la CI, ce que `prompt/10`
interdit explicitement.
"""

from __future__ import annotations

import re
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

from traffic_analysis.core.errors import UnknownModelError
from traffic_analysis.features.models_registry.domain.catalogue import (
    CATALOGUE,
    DEFAULT_MODEL_ID,
    TIER_LABELS,
    TIER_ORDER,
    by_tier,
    find,
    known_ids,
)
from traffic_analysis.features.models_registry.infrastructure.registry import (
    WARMUP_HEIGHT,
    WARMUP_WIDTH,
    ModelRegistry,
    _Resident,
)

if TYPE_CHECKING:
    from pathlib import Path

WEIGHTS_PATTERN = re.compile(r"^[a-z0-9._-]+\.pt$")


class FakeLoadingRegistry(ModelRegistry):
    """Registre dont le chargement est instantané et traçable.

    Sous-classer plutôt que patcher : le comportement de bail, d'éviction et de
    verrouillage — le vrai sujet des tests — reste celui de la production.
    """

    def __init__(self, weights_dir: Path, *, max_loaded: int = 2) -> None:
        super().__init__(weights_dir, max_loaded=max_loaded, device="cpu", half=False)
        self.loads: list[str] = []

    def _load(self, model_id: str) -> Any:  # noqa: ANN401
        self.describe(model_id)
        self.loads.append(model_id)
        return f"modele:{model_id}"


class TestCatalogue:
    def test_vingt_detecteurs_couvrant_quatre_familles_et_cinq_paliers(self) -> None:
        """Ce que l'utilisateur a demandé : chaque famille dans chaque palier."""
        assert len(CATALOGUE) == 20

        grouped = by_tier()
        for tier in TIER_ORDER:
            assert len(grouped[tier]) == 4, f"palier {tier} incomplet"

        families = {model.family for model in CATALOGUE}
        assert families == {"yolov8", "yolo11", "yolo12", "yolo26"}

    def test_les_identifiants_sont_uniques(self) -> None:
        """Un `id` est un contrat partagé avec le frontend et l'historique."""
        ids = [model.id for model in CATALOGUE]
        assert len(set(ids)) == len(ids)

    def test_chaque_poids_est_un_fichier_pt_plausible(self) -> None:
        """`.pt` natif et non `.onnx` : `model.track()` a besoin du pipeline
        complet d'Ultralytics, qu'un export ONNX ne porte pas."""
        for model in CATALOGUE:
            assert WEIGHTS_PATTERN.match(model.weights), model.weights

    def test_chaque_palier_a_un_libelle_affichable(self) -> None:
        assert set(TIER_LABELS) == set(TIER_ORDER)
        assert TIER_LABELS["xlarge"] == "Extra Large"

    def test_chaque_modele_porte_une_note_en_francais(self) -> None:
        """La note est affichée dans le sélecteur : elle aide à choisir."""
        for model in CATALOGUE:
            assert model.note.strip(), model.id

    def test_le_defaut_existe_au_catalogue(self) -> None:
        assert find(DEFAULT_MODEL_ID) is not None
        assert find(DEFAULT_MODEL_ID).tier == "nano"  # type: ignore[union-attr]

    def test_un_identifiant_inconnu_n_est_pas_trouve(self) -> None:
        assert find("yolo42x") is None
        assert "yolo42x" not in known_ids()

    def test_les_paliers_sont_ordonnes_du_plus_leger_au_plus_lourd(self) -> None:
        """L'ordre du sélecteur : on essaie le rapide avant le précis."""
        assert TIER_ORDER == ("nano", "small", "medium", "large", "xlarge")
        for family in {model.family for model in CATALOGUE}:
            sizes = [
                model.size_mb
                for tier in TIER_ORDER
                for model in CATALOGUE
                if model.family == family and model.tier == tier
            ]
            assert sizes == sorted(sizes), f"tailles non croissantes pour {family}"


class TestRegistre:
    def test_un_modele_inconnu_leve_avec_la_liste_des_valides(self, tmp_path: Path) -> None:
        registry = FakeLoadingRegistry(tmp_path)

        with pytest.raises(UnknownModelError) as excinfo:
            registry.describe("yolo42x")

        assert "yolov8n" in str(excinfo.value)

    def test_le_bail_charge_une_fois_puis_reutilise(self, tmp_path: Path) -> None:
        registry = FakeLoadingRegistry(tmp_path)

        with registry.lease("yolov8n") as first:
            assert first == "modele:yolov8n"
        with registry.lease("yolov8n") as second:
            assert second == "modele:yolov8n"

        assert registry.loads == ["yolov8n"]

    def test_deux_bails_simultanes_sur_le_meme_modele_sont_serialises(self, tmp_path: Path) -> None:
        """**L'invariant 9 du projet**, et il manquait.

        `leases` ne comptait que les usages concurrents sans jamais les empêcher :
        deux appelants recevaient la *même* instance et lançaient
        `model.track(..., persist=True)` en parallèle depuis deux threads. Le
        tracker BoT-SORT garde son état d'une frame à l'autre, donc les deux flux
        se mélangeaient — des chiffres plausibles et complètement faux, sans la
        moindre erreur ni la moindre ligne de journal.

        Le cas n'était pas théorique : `max_concurrent_jobs` borne les jobs entre
        eux et `max_realtime_sessions` les sessions entre elles, mais **rien** ne
        bornait un job différé et une session temps réel ensemble — et le
        conteneur les construit sur le même registre.

        Le test observe le **chevauchement**, pas l'ordre : sérialiser signifie
        qu'à aucun instant deux porteurs ne sont dans leur bail à la fois.
        """
        registry = FakeLoadingRegistry(tmp_path)
        inside = 0
        overlapped = False
        started = threading.Barrier(2)
        guard = threading.Lock()

        def hold() -> None:
            nonlocal inside, overlapped
            started.wait(timeout=5)
            with registry.lease("yolov8n"):
                with guard:
                    inside += 1
                    if inside > 1:
                        overlapped = True
                # Assez long pour que l'autre fil ait le temps d'entrer si rien ne
                # l'en empêche — et sans faire dépendre le verdict de la vitesse
                # de la machine : un chevauchement serait détecté, jamais inventé.
                time.sleep(0.05)
                with guard:
                    inside -= 1

        threads = [threading.Thread(target=hold) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not overlapped, "deux bails simultanés ont partagé la même instance"

    def test_le_bail_attend_puis_obtient_l_instance(self, tmp_path: Path) -> None:
        """Attendre, et non refuser.

        Un refus obligerait chaque appelant à gérer une indisponibilité
        transitoire, alors que le travail est déjà mis en file en amont. Le second
        bail doit donc finir par s'ouvrir, pas lever.
        """
        registry = FakeLoadingRegistry(tmp_path)
        obtained: list[str] = []

        def take() -> None:
            with registry.lease("yolov8n") as model:
                obtained.append(str(model))

        with registry.lease("yolov8n"):
            waiter = threading.Thread(target=take)
            waiter.start()
            # Le second bail est bloqué tant que le premier n'est pas rendu.
            waiter.join(timeout=0.2)
            assert obtained == []

        waiter.join(timeout=5)
        assert obtained == ["modele:yolov8n"]

    def test_deux_modeles_differents_ne_s_attendent_pas(self, tmp_path: Path) -> None:
        """Le verrou est **par instance**, jamais global.

        Un verrou unique sérialiserait tout le service : une analyse sur `yolov8n`
        bloquerait une session temps réel sur `yolo11m`, alors que les deux
        instances sont distinctes et leurs états de suivi indépendants.
        """
        registry = FakeLoadingRegistry(tmp_path)
        entered = threading.Event()

        def take_other() -> None:
            with registry.lease("yolo11m"):
                entered.set()

        with registry.lease("yolov8n"):
            other = threading.Thread(target=take_other)
            other.start()
            assert entered.wait(timeout=5), "un modèle distinct a été bloqué"
            other.join(timeout=5)

    def test_une_instance_occupee_n_est_jamais_evincee(self, tmp_path: Path) -> None:
        """Le piège 28 de prompt/13, côté mémoire.

        Arracher un modèle à une analyse en cours la laisserait sans moteur en
        plein vol. Dépasser temporairement le plafond est récupérable ; cela ne
        l'est pas.
        """
        registry = FakeLoadingRegistry(tmp_path, max_loaded=1)

        with registry.lease("yolov8n"):
            with registry.lease("yolo11m"):
                assert set(registry.loaded_ids()) == {"yolov8n", "yolo11m"}
            # Le bail de yolo11m est rendu, mais yolov8n reste occupé.
            assert "yolov8n" in registry.loaded_ids()

    def test_l_eviction_lru_retire_la_plus_ancienne_non_occupee(self, tmp_path: Path) -> None:
        registry = FakeLoadingRegistry(tmp_path, max_loaded=2)

        for model_id in ("yolov8n", "yolo11m", "yolo12l"):
            with registry.lease(model_id):
                pass

        loaded = registry.loaded_ids()
        assert len(loaded) == 2
        assert "yolov8n" not in loaded, "la plus ancienne aurait dû être évincée"

    def test_un_usage_recent_repousse_l_eviction(self, tmp_path: Path) -> None:
        """L'ordre d'usage est l'ordre d'éviction : c'est tout l'intérêt du LRU."""
        registry = FakeLoadingRegistry(tmp_path, max_loaded=2)

        with registry.lease("yolov8n"):
            pass
        with registry.lease("yolo11m"):
            pass
        with registry.lease("yolov8n"):  # yolov8n redevient le plus récent
            pass
        with registry.lease("yolo12l"):
            pass

        assert "yolov8n" in registry.loaded_ids()
        assert "yolo11m" not in registry.loaded_ids()

    def test_le_bail_est_rendu_meme_si_l_analyse_leve(self, tmp_path: Path) -> None:
        """Sans le `finally`, une analyse en échec immobiliserait son modèle
        jusqu'au redémarrage du service."""
        registry = FakeLoadingRegistry(tmp_path)

        with pytest.raises(RuntimeError), registry.lease("yolov8n"):
            raise RuntimeError("analyse en échec")

        assert registry.unload("yolov8n") is True

    def test_decharger_une_instance_occupee_est_refuse(self, tmp_path: Path) -> None:
        registry = FakeLoadingRegistry(tmp_path)

        with registry.lease("yolov8n"):
            assert registry.unload("yolov8n") is False

        assert registry.unload("yolov8n") is True

    def test_decharger_un_modele_absent_rend_faux(self, tmp_path: Path) -> None:
        assert FakeLoadingRegistry(tmp_path).unload("yolov8n") is False

    def test_deux_threads_ne_chargent_pas_le_meme_modele_deux_fois(self, tmp_path: Path) -> None:
        """Deux analyses simultanées sur le même modèle ne doivent pas doubler
        l'empreinte mémoire."""
        registry = FakeLoadingRegistry(tmp_path)
        barrier = threading.Barrier(4)

        def use() -> None:
            barrier.wait()
            with registry.lease("yolo11m"):
                pass

        threads = [threading.Thread(target=use) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Plusieurs chargements peuvent partir en parallèle (le verrou n'est
        # volontairement pas tenu pendant le chargement), mais une seule instance
        # doit rester résidente.
        assert registry.loaded_ids() == ["yolo11m"]


class TestMateriel:
    def test_half_est_toujours_faux_sur_cpu(self, tmp_path: Path) -> None:
        """En fp16 sur CPU, l'inférence **ralentit** (piège 30 de prompt/13)."""
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cpu", half=True)

        assert registry.device() == "cpu"
        assert registry.half() is False

    def test_un_device_explicite_n_est_pas_redecouvert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _capability(monkeypatch, (8, 6))
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cuda:0", half=True)

        assert registry.device() == "cuda:0"
        assert registry.half() is True

    def test_half_est_faux_sur_un_gpu_d_avant_volta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pascal (6.1) calcule le fp16 plus lentement que le fp32.

        Mesuré sur une Quadro P1000 : yolov8n passe de 38,9 ms à 48,9 ms par image
        en demi-précision. « Sur GPU » ne suffit donc pas à justifier le fp16 —
        c'est la même erreur que sur CPU, pour une autre raison matérielle.
        """
        _capability(monkeypatch, (6, 1))
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cuda:0", half=True)

        assert registry.half() is False

    def test_half_reste_vrai_a_partir_de_volta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """7.0 est le seuil exact : c'est là qu'apparaissent les cœurs tensoriels."""
        _capability(monkeypatch, (7, 0))
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cuda:0", half=True)

        assert registry.half() is True

    def test_une_capability_illisible_ne_contredit_pas_le_reglage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On ne désactive que ce qu'on a mesuré.

        Si la sonde échoue, le `half=True` de l'opérateur passe : le contredire sur
        la foi d'un appel qui vient d'échouer désactiverait le fp16 sur des GPU
        parfaitement capables, sans que rien ne le dise.
        """
        import torch

        def _boom(_index: int = 0) -> tuple[int, int]:
            raise RuntimeError("aucun pilote")

        monkeypatch.setattr(torch.cuda, "get_device_capability", _boom)
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cuda:0", half=True)

        assert registry.half() is True


def _capability(monkeypatch: pytest.MonkeyPatch, value: tuple[int, int]) -> None:
    """Fixe la capability CUDA vue par le registre.

    Sans ce stub, le verdict de `half()` dépendrait du GPU de la machine qui lance
    les tests : verts sur une machine sans GPU, rouges sur une Pascal.
    """
    import torch

    monkeypatch.setattr(torch.cuda, "get_device_capability", lambda _index=0: value)


class TestDiagnosticMateriel:
    """Pourquoi `device()` vaut ce qu'il vaut, et le nom du GPU retenu.

    Sans ces champs, un « cpu » ne distingue pas « aucun GPU sur cette machine »
    de « la détection a échoué » — deux causes qui appellent deux gestes
    différents : rien à faire dans le premier cas, installer un pilote dans le
    second.
    """

    def test_un_device_explicite_porte_sa_raison(self, tmp_path: Path) -> None:
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cuda:0", half=True)

        assert registry.device() == "cuda:0"
        assert registry.device_reason() == "configuré explicitement"

    def test_cuda_detecte_porte_sa_raison_et_son_nom(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import torch

        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(torch.cuda, "get_device_name", lambda _index=0: "GPU factice")
        registry = ModelRegistry(tmp_path, max_loaded=2, device="auto", half=True)

        assert registry.device() == "0"
        assert registry.device_reason() == "CUDA détecté"
        assert registry.gpu_name() == "GPU factice"

    def test_aucun_gpu_detecte_porte_sa_raison_et_aucun_nom(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import torch

        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        registry = ModelRegistry(tmp_path, max_loaded=2, device="auto", half=False)

        assert registry.device() == "cpu"
        assert registry.device_reason() == "aucun GPU CUDA détecté"
        assert registry.gpu_name() is None

    def test_torch_indisponible_porte_sa_propre_raison(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`None` dans `sys.modules` fait échouer l'import avec une
        `ModuleNotFoundError` — la façon standard de simuler une dépendance
        absente sans la désinstaller pour de vrai."""
        import sys

        monkeypatch.setitem(sys.modules, "torch", None)
        registry = ModelRegistry(tmp_path, max_loaded=2, device="auto", half=False)

        assert registry.device() == "cpu"
        assert registry.device_reason() == "torch indisponible"

    def test_le_nom_est_lu_sur_le_bon_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`« cuda:1 »` interroge bien le second GPU, pas le premier.

        Sur une machine à deux cartes, lire l'index 0 quoi qu'il arrive
        afficherait le nom d'un GPU que le service n'utilise pas.
        """
        import torch

        monkeypatch.setattr(torch.cuda, "get_device_name", lambda index=0: f"GPU {index}")
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cuda:1", half=False)

        assert registry.gpu_name() == "GPU 1"

    def test_gpu_name_est_none_sur_cpu(self, tmp_path: Path) -> None:
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cpu", half=False)

        assert registry.gpu_name() is None

    def test_device_reason_est_none_avant_toute_resolution(self, tmp_path: Path) -> None:
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cpu", half=False)

        assert registry.device_reason() is None


class _ModeleQuiExigeUnDeviceMarche:
    """Un `.predict()` qui échoue sur tout device sauf celui attendu.

    C'est la seule façon de tester le repli sans un vrai GPU : simuler
    exactement ce qu'un pilote incomplet ferait — répondre `is_available() ==
    True` puis échouer à la première inférence réelle.
    """

    def __init__(self, working_device: str) -> None:
        self._working_device = working_device
        self.predict_calls: list[str] = []

    def predict(self, *_args: object, device: str, **_kwargs: object) -> None:
        self.predict_calls.append(device)
        if device != self._working_device:
            raise RuntimeError(f"simulé : device « {device} » indisponible à l'inférence")


class _RegistreAvecModeleFactice(ModelRegistry):
    """Charge `_ModeleQuiExigeUnDeviceMarche` au lieu d'un vrai `.pt`."""

    def __init__(self, weights_dir: Path, *, working_device: str, half: bool = False) -> None:
        super().__init__(weights_dir, max_loaded=2, device="auto", half=half)
        self._working_device = working_device

    def _load(self, model_id: str) -> Any:  # noqa: ANN401
        self.describe(model_id)
        return _ModeleQuiExigeUnDeviceMarche(self._working_device)


class TestPrechauffageEtDevice:
    """Le warmup est la seule vérification **réelle** du GPU choisi.

    `torch.cuda.is_available()` interroge le pilote ; il peut répondre vrai
    alors que la première inférence échoue quand même. Sans ce repli, le
    service resterait configuré sur un device qui vient de démontrer qu'il ne
    fonctionne pas, et chaque analyse suivante échouerait pareil.
    """

    def test_un_echec_sur_gpu_detecte_replie_sur_cpu_et_reussit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import torch

        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        registry = _RegistreAvecModeleFactice(tmp_path, working_device="cpu")

        registry.warmup("yolov8n")

        assert registry.device() == "cpu"
        assert registry.device_reason() == "échec d'inférence GPU au préchauffage, repli CPU"

    def test_le_repli_invalide_half(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Un GPU qui disparaît ne doit pas laisser `half=True` actif sur le CPU
        qui prend sa place (piège 30 de prompt/13)."""
        import torch

        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        registry = _RegistreAvecModeleFactice(tmp_path, working_device="cpu", half=True)

        registry.warmup("yolov8n")

        assert registry.half() is False

    def test_un_device_explicite_qui_echoue_n_est_pas_retourne(self, tmp_path: Path) -> None:
        """L'opérateur qui force un device fait un choix : le lui rendre en
        silence masquerait une configuration fausse plutôt que de la signaler."""

        class _RegistreDeviceExplicite(ModelRegistry):
            def _load(self, model_id: str) -> Any:  # noqa: ANN401
                self.describe(model_id)
                return _ModeleQuiExigeUnDeviceMarche("cpu")

        registry = _RegistreDeviceExplicite(tmp_path, max_loaded=2, device="cuda:0", half=False)

        registry.warmup("yolov8n")

        # Toujours « cuda:0 » : le warmup a échoué et journalisé, mais n'a pas
        # touché à un device explicitement demandé.
        assert registry.device() == "cuda:0"
        assert registry.device_reason() == "configuré explicitement"

    def test_un_succes_direct_ne_declenche_aucun_repli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import torch

        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        registry = _RegistreAvecModeleFactice(tmp_path, working_device="0")

        registry.warmup("yolov8n")

        assert registry.device() == "0"
        assert registry.device_reason() == "CUDA détecté"

    def test_la_taille_est_absente_tant_que_le_poids_n_est_pas_la(self, tmp_path: Path) -> None:
        """`size_mb` est une estimation du catalogue ; `size_bytes` est la vérité."""
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cpu", half=False)

        assert registry.is_downloaded("yolov8n") is False
        assert registry.size_bytes("yolov8n") is None

        (tmp_path / "yolov8n.pt").write_bytes(b"x" * 1234)
        assert registry.is_downloaded("yolov8n") is True
        assert registry.size_bytes("yolov8n") == 1234


class TestBudgetDeThreads:
    """Deux robinets distincts, et le second manquait.

    `TRAFFIC_INFERENCE_THREADS` n'atteint qu'OpenCV *via* torch — c'est-à-dire
    jamais. Or au repos OpenCV prend tous les processeurs logiques (12 mesurés ici)
    quand torch en prend 6, et le prétraitement d'Ultralytics est du pur OpenCV
    tournant dans le fil qui attend le GPU, pendant que le fil de décodage d'ADR 0031
    en veut autant. C'est nommément la contention qu'ADR 0031 laisse sans réglage.
    """

    @staticmethod
    def _registry(tmp_path: Path) -> ModelRegistry:
        return ModelRegistry(weights_dir=tmp_path, device="cpu", half=False, max_loaded=2)

    def test_zero_ne_touche_a_rien(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Le défaut ne doit poser **aucun** des deux robinets.

        Le test relève la valeur avant et après : sans cela, il passerait pour de
        mauvaises raisons sur une machine dont le budget vaudrait déjà zéro.
        """
        import cv2

        poses: list[int] = []
        monkeypatch.setattr(cv2, "setNumThreads", poses.append)
        avant = cv2.getNumThreads()

        self._registry(tmp_path).apply_thread_budget(0, 0)

        assert poses == []
        assert cv2.getNumThreads() == avant

    def test_le_budget_opencv_atteint_opencv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cv2

        poses: list[int] = []
        monkeypatch.setattr(cv2, "setNumThreads", poses.append)

        self._registry(tmp_path).apply_thread_budget(0, 3)

        assert poses == [3]

    def test_un_opencv_indisponible_ne_fait_pas_echouer_le_demarrage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un budget de threads est un confort ; refuser de démarrer pour lui
        échangerait une gêne contre une panne."""
        import cv2

        def boom(_value: int) -> None:
            raise RuntimeError("pas de pool")

        monkeypatch.setattr(cv2, "setNumThreads", boom)

        self._registry(tmp_path).apply_thread_budget(0, 3)  # ne lève pas


class TestLiberationDeVram:
    """Ce qu'une éviction rend au pilote, et où elle le rend.

    `del self._residents[victim]` ne suffit pas, et la raison ne se devine pas :
    Ultralytics enregistre le crochet du tracker dans une fermeture qui capture le
    prédicteur, donc le compteur de références ne tombe jamais à zéro et les poids
    restent en VRAM jusqu'à un passage générationnel du ramasse-miettes. D'où
    `gc.collect()` **avant** `empty_cache()` — sans lui, l'appel journaliserait un
    succès sans effet, puisqu'`empty_cache` ne rend que des blocs déjà libres.
    """

    @staticmethod
    def _registry(tmp_path: Path, **kwargs: object) -> ModelRegistry:
        base: dict[str, object] = {"device": "cpu", "half": False, "max_loaded": 1}
        return ModelRegistry(weights_dir=tmp_path, **{**base, **kwargs})  # type: ignore[arg-type]

    def test_l_eviction_rend_la_liste_des_modeles_liberes(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path, max_loaded=1)
        registry._residents["a"] = _Resident(model=object(), busy=False)
        registry._residents["b"] = _Resident(model=object(), busy=False)

        freed = registry._evict_if_needed()

        assert freed == ["a"]
        assert list(registry._residents) == ["b"]

    def test_une_instance_occupee_n_est_jamais_liberee(self, tmp_path: Path) -> None:
        """Dépasser le plafond est récupérable ; arracher un modèle en vol ne l'est pas."""
        registry = self._registry(tmp_path, max_loaded=1)
        registry._residents["a"] = _Resident(model=object(), busy=True)
        registry._residents["b"] = _Resident(model=object(), busy=True)

        assert registry._evict_if_needed() == []
        assert list(registry._residents) == ["a", "b"]

    def test_la_liberation_ne_fait_rien_sur_cpu(self, tmp_path: Path) -> None:
        """Pas de VRAM à rendre, donc pas d'import de torch : c'est ce qui garde la
        CI et le moteur factice à l'écart de cette branche."""
        registry = self._registry(tmp_path)

        registry._release_vram(["a"])  # ne lève pas, n'importe rien

    def test_la_liberation_ne_leve_jamais(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rendre de la mémoire est un confort ; échouer ne doit pas casser une éviction."""
        # `device="0"` explicite : `device()` rend « 0 » sans jamais sonder torch,
        # donc la branche GPU est atteinte en CI, sur une machine qui n'en a pas.
        registry = self._registry(tmp_path, device="0")

        # `torch` absent du chemin d'import : l'`except` doit avaler proprement.
        monkeypatch.setitem(__import__("sys").modules, "torch", None)

        registry._release_vram(["a"])  # ne lève pas

    def test_rien_a_liberer_ne_declenche_rien(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path, device="0")

        registry._release_vram([])  # ne lève pas, ne touche pas au GPU


class TestPrechauffage:
    """Ce que le préchauffage soumet — et ce qu'il ne doit **jamais** appeler.

    Il chauffait un carré `640×640` par `predict` sans `imgsz`, quand la production
    soumet un letterbox rectangulaire et par lot. Or `stream_inference` pose
    `done_warmup = True` après cette passe et le prédicteur est réutilisé : la forme
    réellement analysée ne bénéficiait d'aucune chauffe. Mesuré, ~63 ms par job.
    """

    class _RecordingModel:
        """Note la forme de la source et les arguments de chaque `predict`."""

        def __init__(self) -> None:
            self.predict_calls: list[dict[str, object]] = []
            self.track_calls = 0

        def predict(self, source: object, **kwargs: object) -> list[object]:
            shapes = [getattr(item, "shape", None) for item in source]  # type: ignore[union-attr]
            self.predict_calls.append({"count": len(shapes), "shape": shapes[0], **kwargs})
            return []

        def track(self, *_args: object, **_kwargs: object) -> list[object]:
            self.track_calls += 1
            return []

    def _warm(self, tmp_path: Path, **kwargs: object) -> _RecordingModel:
        """Sous-classe plutôt que `monkeypatch` : `__slots__` rend les méthodes
        d'instance immuables, et c'est déjà le patron de `FakeLoadingRegistry`."""
        model = self._RecordingModel()
        recording = model

        class _Registry(ModelRegistry):
            def _load(self, model_id: str) -> Any:  # noqa: ANN401
                self.describe(model_id)
                return recording

        registry = _Registry(weights_dir=tmp_path, device="cpu", half=False, max_loaded=1)
        registry.warmup("yolov8n", **kwargs)  # type: ignore[arg-type]
        return model

    def test_le_prechauffage_soumet_le_lot_et_le_cote_de_production(self, tmp_path: Path) -> None:
        model = self._warm(tmp_path, batch=4, imgsz=640)

        assert len(model.predict_calls) == 1
        call = model.predict_calls[0]
        assert call["count"] == 4
        # Une image de vidéo, pas un carré : c'est le letterbox d'Ultralytics qui en
        # tire la forme réelle du tenseur, et un carré en produirait une autre.
        assert call["shape"] == (WARMUP_HEIGHT, WARMUP_WIDTH, 3)
        assert call["imgsz"] == 640

    def test_le_prechauffage_n_appelle_jamais_track(self, tmp_path: Path) -> None:
        """**Le test qui protège ADR 0047.**

        `on_predict_start` sort immédiatement quand `predictor.trackers` existe et que
        `persist` est vrai. Chauffer par `track` construirait donc un tracker au
        démarrage depuis le fichier de **base**, et le premier job réel ne relirait
        jamais son fichier dérivé — `reset_trackers` repose `REQUEST_TRACKER_KEYS`
        mais pas `with_reid`, consommé à la construction. Ce serait 4× de cadence
        perdue sur une tête `end2end`, en silence. `predict` n'avance pas non plus
        `BaseTrack._count` (invariant 7).
        """
        model = self._warm(tmp_path, batch=4, imgsz=640)

        assert model.track_calls == 0

    def test_les_defauts_gardent_une_seule_image(self, tmp_path: Path) -> None:
        """Un appelant qui ne passe rien obtient l'ancien lot : strictement additif."""
        model = self._warm(tmp_path)

        assert model.predict_calls[0]["count"] == 1
