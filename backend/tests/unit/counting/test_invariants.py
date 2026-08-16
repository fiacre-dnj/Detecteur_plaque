"""Les quatre invariants comptables, sur toute la batterie de scénarios.

`prompt/10` les décrit comme « le filet le plus rentable du projet », et la raison
est simple : ils ne vérifient pas qu'un chiffre est *juste* — cela demanderait un
comptage humain — mais que les chiffres affichés ensemble **ne se contredisent
pas**. Un écran où le total des types dépasse le total des véhicules est
immédiatement discrédité, quelle que soit la qualité de la détection.

Les quatre égalités :

1. `crossings == Σ by_line[*].total`
2. `by_line[l].total == positive.total + negative.total`, pour chaque ligne
3. `Σ tracked_by_class.values() == tracked_vehicles`
4. `Σ by_line[*].by_class.values() == crossings`
"""

from __future__ import annotations

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


def _play(scenario: Scenario) -> AnalysisStats:
    """Joue un scénario et rend ses statistiques finales."""
    session = _played(scenario)
    return session.stats()


def _played(scenario: Scenario) -> AnalysisSession:
    """Joue un scénario et rend la session, pour les tests qui veulent le registre."""
    session = AnalysisSession(scenario.config, FRAME_WIDTH, FRAME_HEIGHT)
    for index, observations in enumerate(scenario.frames):
        session.feed(index, index * FRAME_MS, observations)
    return session


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
        assert tally.total == tally.positive.total + tally.negative.total, f"ligne « {line_id} »"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_la_repartition_par_type_somme_au_nombre_de_vehicules(scenario: Scenario) -> None:
    """Invariant 3 — la carte « Véhicules détectés » et les tuiles par type
    doivent raconter la même histoire.

    Cet invariant tient même quand un vote majoritaire bascule en cours de route :
    la voix unique du véhicule **déménage** d'un total de classe à l'autre.
    """
    stats = _play(scenario)

    assert sum(stats.tracked_by_class.values()) == stats.tracked_vehicles


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

    assert stats.tracked_vehicles >= 0
    assert stats.crossings >= 0
    assert stats.vehicles_per_minute >= 0.0
    for tally in stats.by_line.values():
        assert tally.total >= 0
        assert min(tally.by_class.values(), default=0) >= 0
        for side in (tally.positive, tally.negative):
            assert side.total >= 0
            assert min(side.by_class.values(), default=0) >= 0
    for zone_tally in stats.by_zone.values():
        assert zone_tally.entries >= 0
        assert zone_tally.inside >= 0


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_un_franchissement_n_existe_que_pour_un_vehicule_compte(scenario: Scenario) -> None:
    """Aucun passage ne peut être attribué à un véhicule absent du registre.

    Remplace le plafond du mode déduplication, disparu avec ADR 0016 en même temps
    que `dedupe_by_identity` et `reid_hits` dont il dépendait.

    Ce qui le remplace est plus fort, parce qu'il ne borne pas un total mais vérifie
    une **appartenance** : chaque `global_id` qui a fait bouger un compteur doit
    figurer dans le registre. Le plafond `uniques + ré-identifications` laissait
    passer un franchissement attribué à un numéro inexistant du moment que le total
    tenait ; celui-ci ne le laisse pas.
    """
    session = _played(scenario)
    stats = session.stats()
    known = {record.global_id for record in session.vehicles()}

    for line_id, tally in stats.by_line.items():
        assert tally.total >= 0, f"ligne « {line_id} »"
    assert stats.crossed_unique == len(known & _counted_ids(session))
    assert _counted_ids(session) <= known, "un passage sans véhicule au registre"


def _counted_ids(session: AnalysisSession) -> set[int]:
    """Les numéros ayant fait bouger un compteur — la source du badge ✓.

    Lu par un accès privé, faute d'API publique : la seule autre voie serait de
    recomposer l'ensemble depuis `vehicles()`, ce qui ferait dériver l'attendu du
    résultat qu'on veut vérifier.
    """
    return session._counter.counted_identities()


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
def test_les_vehicules_ayant_franchi_ne_depassent_jamais_les_vehicules_vus(
    scenario: Scenario,
) -> None:
    """`crossed_unique <= tracked_vehicles`, sur **tous** les scénarios.

    C'est l'inégalité qui fait du taux de franchissement un pourcentage. Elle tient
    par nature — on ne peut pas avoir franchi sans avoir été vu — mais elle ne
    tenait *pas* avec `crossings` au numérateur : depuis ADR 0014 un aller-retour
    compte 2 passages pour 1 véhicule, et le taux affichait 200 %.

    Le test porte donc sur le remplaçant, et il couvre aussi le cas dégénéré :
    aucun franchissement doit donner 0, jamais un négatif ni un `None`.
    """
    stats = _play(scenario)

    assert 0 <= stats.crossed_unique <= stats.tracked_vehicles
    # Et jamais plus de véhicules distincts que de passages : chaque véhicule
    # compté a fait bouger un compteur au moins une fois.
    assert stats.crossed_unique <= stats.crossings


def test_un_aller_retour_compte_deux_passages_mais_un_seul_vehicule() -> None:
    """**Le cas exact qui cassait le taux de franchissement.**

    Un véhicule qui franchit puis revient produit 2 passages sous ADR 0014. Avec
    `crossings / tracked_vehicles`, le taux valait 200 % — un pourcentage impossible
    affiché sans le moindre avertissement, et documenté à l'époque comme voulu.

    Ce test fixe les deux chiffres séparément, pour que personne ne « corrige »
    l'un en croyant réparer l'autre : les 2 passages sont justes, c'est le
    dénominateur qui était mal choisi.
    """
    scenario = next(s for s in SCENARIOS if "aller" in str(s).lower())
    stats = _play(scenario)

    assert stats.crossings >= 2
    assert stats.crossed_unique == 1
    assert stats.crossed_unique / stats.tracked_vehicles <= 1.0


@pytest.mark.parametrize("scenario", SCENARIOS, ids=str)
def test_le_registre_est_coherent_avec_les_statistiques(scenario: Scenario) -> None:
    """Les cartes disent *combien*, le registre dit *lesquels* — sur les mêmes faits.

    Si le registre listait moins de franchissements que les compteurs, un
    utilisateur qui vérifie ligne à ligne ne retrouverait pas son total, et c'est
    exactement ce que le registre existe pour permettre.
    """
    session = _played(scenario)

    stats = session.stats()
    vehicles = session.vehicles()

    # **Égalité et non inégalité** : les deux filtrent sur la même confirmation
    # depuis ADR 0016. Sous la galerie, le registre était indexé sur les agrégats et
    # le total sur un compteur d'émission distinct, donc seul un `<=` tenait.
    assert len(vehicles) == stats.tracked_vehicles
    assert sum(len(record.crossed_lines) for record in vehicles) == stats.crossings
    for record in vehicles:
        assert record.first_seen_ms <= record.last_seen_ms


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
