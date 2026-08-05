"""Statistique d'un échantillon de mesures — le domaine pur du benchmark.

Ces tests affirment des **nombres calculés à la main**, pas des ordres de grandeur.
C'est ce qui distingue un test de statistique utile d'un test qui vérifie
seulement que la fonction ne lève pas.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.benchmark.domain.records import (
    BenchmarkEntry,
    BenchmarkRun,
    is_terminal,
    median,
    percentile,
)


class TestMediane:
    def test_serie_impaire_prend_la_valeur_centrale(self) -> None:
        assert median([12.0, 10.0, 11.0]) == 11.0

    def test_serie_paire_moyenne_les_deux_valeurs_centrales(self) -> None:
        assert median([10.0, 12.0, 14.0, 20.0]) == 13.0

    def test_la_mediane_ignore_une_valeur_aberrante(self) -> None:
        """C'est **la** raison d'être de la médiane ici.

        Une série de cinq inférences contient presque toujours une valeur
        aberrante — ordonnancement du système, ramasse-miettes, throttle
        thermique. La moyenne de cette série vaut 16,9 ms et ne décrit aucune
        inférence réelle ; la médiane vaut 11,5 et décrit toutes les autres.
        """
        samples = [10.0, 11.0, 11.5, 12.0, 40.0]

        assert median(samples) == 11.5
        assert sum(samples) / len(samples) == pytest.approx(16.9)

    def test_une_serie_vide_rend_zero_au_lieu_de_lever(self) -> None:
        """Contrat explicite : une ligne en échec n'a aucune mesure.

        Elle doit tout de même pouvoir être construite et sérialisée, sinon un
        modèle dont le poids ne se télécharge pas ferait tomber le run entier —
        exactement ce que la règle 6 du protocole existe pour empêcher.
        """
        assert median([]) == 0.0


class TestCentile:
    def test_le_p95_interpole_entre_les_deux_rangs_voisins(self) -> None:
        """Sur cinq points, le rang du p95 vaut 0,95 × 4 = 3,8.

        Donc 80 % du chemin entre la quatrième valeur (12) et la cinquième (40) :
        12 + 0,8 × 28 = 34,4. Sans interpolation, `p95` rendrait brutalement 40 —
        c'est-à-dire `max`, et la colonne n'apprendrait rien de plus.
        """
        assert percentile([10.0, 11.0, 11.5, 12.0, 40.0], 0.95) == pytest.approx(34.4)

    def test_un_seul_point_est_son_propre_centile(self) -> None:
        assert percentile([13.0], 0.95) == 13.0

    def test_une_serie_vide_rend_zero(self) -> None:
        assert percentile([], 0.95) == 0.0


class TestLigneDeMesure:
    def test_la_cadence_derive_de_la_mediane_et_non_d_une_seconde_mesure(self) -> None:
        """Invariant 3 du projet, appliqué au benchmark.

        `fps` est **dérivé**, jamais mesuré à part : deux nombres censés dire la
        même chose finissent par se contredire, et l'utilisateur ne sait alors plus
        lequel croire.
        """
        entry = BenchmarkEntry(model_id="m", label="M", tier="nano", median_ms=25.0)

        assert entry.fps == pytest.approx(40.0)

    def test_une_ligne_sans_mesure_rend_une_cadence_nulle_et_non_une_division_par_zero(
        self,
    ) -> None:
        entry = BenchmarkEntry(model_id="m", label="M", tier="nano", median_ms=0.0)

        assert entry.fps == 0.0

    def test_from_samples_calcule_mediane_p95_min_et_max(self) -> None:
        entry = BenchmarkEntry.from_samples(
            model_id="m",
            label="M",
            tier="nano",
            samples=[10.0, 11.0, 11.5, 12.0, 40.0],
            load_ms=120.0,
            detections=4,
        )

        assert entry.median_ms == 11.5
        assert entry.p95_ms == pytest.approx(34.4)
        assert entry.min_ms == 10.0
        assert entry.max_ms == 40.0
        # `frames` compte les mesures **retenues** : la chauffe est écartée en
        # amont, elle n'apparaît jamais dans la série reçue ici.
        assert entry.frames == 5
        assert not entry.failed

    def test_une_ligne_en_echec_porte_son_message_et_des_durees_nulles(self) -> None:
        entry = BenchmarkEntry.failure(
            model_id="m", label="M", tier="xlarge", error="Poids indisponibles."
        )

        assert entry.failed
        assert entry.error == "Poids indisponibles."
        assert entry.median_ms == 0.0
        assert entry.frames == 0


class TestRun:
    @staticmethod
    def _run(entries: list[BenchmarkEntry]) -> BenchmarkRun:
        return BenchmarkRun(
            id="r1",
            status="running",
            model_ids=("a", "b", "c"),
            frames=5,
            image_source="sample",
            image_hash="f" * 64,
            image_width=64,
            image_height=48,
            device="cpu",
            half=False,
            ultralytics_version="8.3.0",
            confidence_threshold=0.35,
            iou_threshold=0.45,
            entries=entries,
        )

    def test_la_progression_est_la_fraction_de_modeles_mesures(self) -> None:
        run = self._run([BenchmarkEntry(model_id="a", label="A", tier="nano")])

        assert run.progress == pytest.approx(1 / 3)
        assert (run.completed, run.total) == (1, 3)

    def test_le_plus_rapide_ignore_les_lignes_en_echec(self) -> None:
        """Un échec a `median_ms = 0`, et un zéro gagnerait tous les classements.

        Sans cette exclusion, le modèle affiché comme « le plus rapide » serait
        systématiquement celui qui n'a pas pu être mesuré.
        """
        run = self._run(
            [
                BenchmarkEntry.failure(model_id="a", label="A", tier="nano", error="échec"),
                BenchmarkEntry(model_id="b", label="B", tier="small", median_ms=30.0),
                BenchmarkEntry(model_id="c", label="C", tier="medium", median_ms=18.0),
            ]
        )

        fastest = run.fastest()

        assert fastest is not None
        assert fastest.model_id == "c"

    def test_aucun_plus_rapide_quand_tout_a_echoue(self) -> None:
        run = self._run(
            [BenchmarkEntry.failure(model_id="a", label="A", tier="nano", error="échec")]
        )

        assert run.fastest() is None


@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        ("queued", False),
        ("running", False),
        ("done", True),
        ("error", True),
        ("cancelled", True),
    ],
)
def test_les_statuts_terminaux_sont_ceux_qui_ferment_le_flux_sse(
    status: str, terminal: bool
) -> None:
    assert is_terminal(status) is terminal  # type: ignore[arg-type]
