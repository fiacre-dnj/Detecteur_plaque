"""Les quatre invariants comptables, sur toute la batterie de scénarios.

`prompt/10` les décrit comme « le filet le plus rentable du projet », et la raison
est simple : ils ne vérifient pas qu'un chiffre est *juste* — cela demanderait un
comptage humain — mais que les chiffres affichés ensemble **ne se contredisent
pas**. Un écran où le total des types dépasse le total des véhicules est
immédiatement discrédité, quelle que soit la qualité de la détection.

Les quatre égalités :

1. `crossings == Σ by_line[*].total`
2. `by_line[l].total == positive + negative`, pour chaque ligne
3. `Σ unique_by_class.values() == unique_vehicles`
4. `Σ by_line[*].by_class.values() == crossings`
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from tests.support.scenarios import (
    FRAME_HEIGHT,
    FRAME_MS,
    FRAME_WIDTH,
    Scenario,
    all_scenarios,
)
from traffic_analysis.features.counting.domain.models import AnalysisStats
from traffic_analysis.features.counting.domain.tracking_session import AnalysisSession

SCENARIOS = all_scenarios()


def _scene() -> np.ndarray:
    """Image texturée : la ré-identification a besoin d'apparence pour travailler."""
    image = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    image[:, :] = (40, 90, 180)
    image[::5, :] = (240, 240, 240)
    return image


def _play(scenario: Scenario, *, dedupe: bool = False) -> AnalysisStats:
    """Joue un scénario et rend ses statistiques finales.

    `dedupe` demande le mode d'ADR 0009 — un véhicule compte une fois. Le défaut est
    le mode du produit : on compte des passages (ADR 0014). Les quatre invariants
    comptables tiennent dans les **deux** modes, ce qui est justement ce qui en fait
    des invariants ; seul le plafond de franchissements dépend du mode.
    """
    session = AnalysisSession(
        replace(scenario.config, dedupe_by_identity=dedupe), FRAME_WIDTH, FRAME_HEIGHT
    )
    image = _scene()
    for index, observations in enumerate(scenario.frames):
        session.feed(index, index * FRAME_MS, image, observations)
    return session.stats()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_les_franchissements_sont_la_somme_du_detail_par_ligne(scenario: Scenario) -> None:
    """Invariant 1 — le total est **dérivé**, jamais accumulé en parallèle.

    Deux compteurs indépendants finissent toujours par se contredire.
    """
    stats = _play(scenario)

    assert stats.crossings == sum(tally.total for tally in stats.by_line.values())


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_le_total_d_une_ligne_est_la_somme_de_ses_deux_sens(scenario: Scenario) -> None:
    """Invariant 2 — c'est ce que l'infobulle « ↑ p · ↓ n » promet à l'écran."""
    stats = _play(scenario)

    for line_id, tally in stats.by_line.items():
        assert tally.total == tally.positive + tally.negative, f"ligne « {line_id} »"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_la_repartition_des_uniques_somme_au_nombre_d_uniques(scenario: Scenario) -> None:
    """Invariant 3 — la carte « Véhicules uniques » et les tuiles par type
    doivent raconter la même histoire.

    Cet invariant tient même quand un vote majoritaire bascule en cours de route :
    le vote unique de l'identité **déménage** d'un total de classe à l'autre.
    """
    stats = _play(scenario)

    assert sum(stats.unique_by_class.values()) == stats.unique_vehicles


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_la_repartition_des_passages_somme_aux_franchissements(scenario: Scenario) -> None:
    """Invariant 4 — même exigence, côté passages."""
    stats = _play(scenario)

    ventilated = sum(count for tally in stats.by_line.values() for count in tally.by_class.values())
    assert ventilated == stats.crossings


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_aucun_compteur_n_est_negatif(scenario: Scenario) -> None:
    """Un compteur négatif est le symptôme d'un décompte mal réconcilié.

    Il n'a jamais été observé, et c'est précisément pour cela qu'il faut le
    surveiller : c'est le genre de bug qui n'apparaît qu'en production.
    """
    stats = _play(scenario)

    assert stats.unique_vehicles >= 0
    assert stats.crossings >= 0
    assert stats.reid_hits >= 0
    assert stats.vehicles_per_minute >= 0.0
    for tally in stats.by_line.values():
        assert tally.total >= 0
        assert min(tally.by_class.values(), default=0) >= 0
    for zone_tally in stats.by_zone.values():
        assert zone_tally.entries >= 0
        assert zone_tally.inside >= 0


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_en_deduplication_les_passages_ne_depassent_pas_les_generations(
    scenario: Scenario,
) -> None:
    """Un franchissement de plus que possible signalerait un garde en défaut.

    **Ce plafond est celui du mode déduplication, pas du défaut du produit.** Chaque
    identité y compte une fois par génération (ADR 0009), et une génération naît soit
    à l'admission, soit d'une ré-identification : le plafond exact est donc
    `uniques + ré-identifications`.

    Il est serré, et c'est ce qui fait sa valeur : l'ancien plafond
    (`uniques × lignes × 2`) restait vrai même avec le garde débranché. Le garder
    ici, sur le mode devenu optionnel, est ce qui garantit que le garde fonctionne
    toujours le jour où on le rallume.
    """
    stats = _play(scenario, dedupe=True)

    assert stats.crossings <= stats.unique_vehicles + stats.reid_hits


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_la_ventilation_par_categorie_somme_aux_franchissements(scenario: Scenario) -> None:
    """Véhicules et personnes séparés, sans qu'un franchissement se perde.

    La ventilation est une **propriété dérivée** de `by_class` : cette égalité tient
    donc par construction, et ce test existe pour le cas où quelqu'un la
    transformerait en champ accumulé — ce qui rouvrirait exactement le bug que
    l'invariant 3 a déjà coûté.
    """
    stats = _play(scenario)

    assert sum(stats.by_category.values()) == stats.crossings


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_le_registre_est_coherent_avec_les_statistiques(scenario: Scenario) -> None:
    """Les cartes disent *combien*, le registre dit *lesquels* — sur les mêmes faits.

    Si le registre listait moins de franchissements que les compteurs, un
    utilisateur qui vérifie ligne à ligne ne retrouverait pas son total, et c'est
    exactement ce que le registre existe pour permettre.
    """
    session = AnalysisSession(scenario.config, FRAME_WIDTH, FRAME_HEIGHT)
    image = _scene()
    for index, observations in enumerate(scenario.frames):
        session.feed(index, index * FRAME_MS, image, observations)

    stats = session.stats()
    vehicles = session.vehicles()

    assert len(vehicles) <= stats.unique_vehicles
    assert sum(len(record.crossed_lines) for record in vehicles) == stats.crossings
    for record in vehicles:
        assert record.first_seen_ms <= record.last_seen_ms
        assert record.reid_count >= 0


def test_la_batterie_de_scenarios_n_est_pas_vide() -> None:
    """Garde-fou : un `parametrize` sur une liste vide passe en silence.

    Ce serait la pire des issues — un filet qui rapporte « tout va bien » alors
    qu'il n'a rien attrapé.
    """
    assert len(SCENARIOS) >= 10


def test_au_moins_un_scenario_produit_reellement_des_franchissements() -> None:
    """Second garde-fou : des invariants vérifiés sur des compteurs tous nuls
    seraient satisfaits sans rien prouver."""
    assert any(_play(scenario).crossings > 0 for scenario in SCENARIOS)
