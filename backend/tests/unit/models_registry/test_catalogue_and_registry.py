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
from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry

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

    def test_un_device_explicite_n_est_pas_redecouvert(self, tmp_path: Path) -> None:
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cuda:0", half=True)

        assert registry.device() == "cuda:0"
        assert registry.half() is True

    def test_la_taille_est_absente_tant_que_le_poids_n_est_pas_la(self, tmp_path: Path) -> None:
        """`size_mb` est une estimation du catalogue ; `size_bytes` est la vérité."""
        registry = ModelRegistry(tmp_path, max_loaded=2, device="cpu", half=False)

        assert registry.is_downloaded("yolov8n") is False
        assert registry.size_bytes("yolov8n") is None

        (tmp_path / "yolov8n.pt").write_bytes(b"x" * 1234)
        assert registry.is_downloaded("yolov8n") is True
        assert registry.size_bytes("yolov8n") == 1234
