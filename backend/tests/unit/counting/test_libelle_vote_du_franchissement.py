"""Un franchissement porte le vote **final**, pas celui de l'instant du passage.

L'invariant 4 promet qu'on compte sous `identity_label`, le vote majoritaire sur *la
vie du véhicule*. C'était vrai du registre et de `tracked_by_class`, relus à la fin ;
c'était faux des franchissements, écrits une fois pour toutes avec le vote tel qu'il
était à l'instant du passage — et `_retally` ne déplaçait la voix que dans
`tracked_by_class`.

Le cas frappe précisément moto, vélo et personne, les trois classes que le détecteur
confond, et dont la lecture **s'améliore en approchant** : un deux-roues lu `person` de
loin bascule après le franchissement si la ligne est dans la moitié éloignée du champ.

Deux conséquences distinctes, et la seconde est la plus dommageable :

- le même objet était classé différemment par deux surfaces de la même page ;
- la règle de **voie réservée**, évaluée côté client sur ce libellé, pouvait signaler en
  rouge une moto parfaitement autorisée, avec sa photo.

La propriété testée est une **égalité**, jamais une valeur : un seul objet ne peut pas
porter deux classes.
"""

from __future__ import annotations

from tests.support.builders import CLASS_LABELS, MOTORCYCLE, PERSON, make_line
from traffic_analysis.features.counting.domain.models import BoundingBox, TrackObservation
from traffic_analysis.features.counting.domain.tracking_session import (
    AnalysisSession,
    SessionConfig,
)

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FRAME_MS = 40.0

#: Ligne **horizontale** au milieu : les trajectoires de ce module descendent.
LINE = make_line("l1", a=(0.0, 540.0), b=(1920.0, 540.0))


def _session() -> AnalysisSession:
    return AnalysisSession(
        SessionConfig(lines=(LINE,), min_hits=1, class_ids=(PERSON, MOTORCYCLE)),
        FRAME_WIDTH,
        FRAME_HEIGHT,
    )


def _observation(class_id: int, y: float) -> TrackObservation:
    return TrackObservation(
        track_id=1,
        class_id=class_id,
        label=CLASS_LABELS[class_id],
        score=0.90,
        box=BoundingBox(900.0, y, 60.0, 90.0),
    )


def _run(session: AnalysisSession, labels: list[int]) -> None:
    """Un deux-roues qui descend et traverse la ligne, lu différemment au fil du temps.

    La trajectoire passe de `y = 300` à `y = 780` : la ligne à 540 est franchie au
    milieu, donc **avant** que le vote ne bascule si les premières lectures sont
    `person`. C'est exactement la géométrie du cas réel — la ligne dans la moitié
    éloignée du champ, la lecture qui se corrige en approchant.
    """
    step = 480 / max(1, len(labels) - 1)
    for index, class_id in enumerate(labels):
        session.feed(index, index * FRAME_MS, [_observation(class_id, 300.0 + index * step)])


class TestLeVoteBasculeApresLeFranchissement:
    def test_un_seul_objet_ne_porte_jamais_deux_classes(self) -> None:
        """**L'égalité, et pas la valeur.** C'est elle qui est la propriété.

        Avant le correctif : `by_class == {'person': 1}` pendant que
        `tracked_by_class == {'motorcycle': 1}`. Le même véhicule, deux classes, sur le
        même écran.
        """
        session = _session()
        _run(session, [PERSON, PERSON, PERSON, MOTORCYCLE, MOTORCYCLE, MOTORCYCLE, MOTORCYCLE])

        stats = session.stats()
        assert stats.crossings == 1
        assert stats.by_class == stats.tracked_by_class

    def test_la_ventilation_de_la_ligne_suit_aussi(self) -> None:
        """`by_line[*].by_class` est ce que lisent le KPI et le camembert par ligne.

        Le laisser figé pendant que `by_class` bouge remplacerait une incohérence par
        une autre — c'est pourquoi le déplacement a lieu **dans le compteur de lignes**
        et non sur un agrégat calculé après coup.
        """
        session = _session()
        _run(session, [PERSON, PERSON, PERSON, MOTORCYCLE, MOTORCYCLE, MOTORCYCLE, MOTORCYCLE])

        tally = session.stats().by_line["l1"]
        moved = {**tally.positive.by_class, **tally.negative.by_class}
        assert moved == {"motorcycle": 1}

    def test_le_total_de_la_ligne_ne_bouge_pas(self) -> None:
        """Un franchissement reste un franchissement : seule l'étiquette change.

        C'est ce qui rend le déplacement sûr vis-à-vis de l'invariant 3 —
        `total == Σ by_class` doit rester vrai des deux côtés du basculement.
        """
        session = _session()
        _run(session, [PERSON, PERSON, PERSON, MOTORCYCLE, MOTORCYCLE, MOTORCYCLE, MOTORCYCLE])

        tally = session.stats().by_line["l1"]
        for side in (tally.positive, tally.negative):
            assert side.total == sum(side.by_class.values())
        assert tally.total == session.stats().crossings

    def test_un_vote_qui_ne_bascule_pas_ne_deplace_rien(self) -> None:
        """Le témoin : sans basculement, le comportement est celui d'avant, au bit près."""
        session = _session()
        _run(session, [MOTORCYCLE] * 7)

        stats = session.stats()
        assert stats.by_class == {"motorcycle": 1}
        assert stats.by_class == stats.tracked_by_class

    def test_le_vote_reste_collant_a_l_egalite(self) -> None:
        """Trois contre trois laisse le tenant en place, et rien ne doit être déplacé.

        La règle du `>` strict de `TrackNumbering.vote` : une lecture qui alterne ne
        doit jamais faire osciller un véhicule entre deux compteurs — et donc jamais
        faire osciller une ventilation de ligne non plus.
        """
        session = _session()
        _run(session, [PERSON, PERSON, PERSON, MOTORCYCLE, MOTORCYCLE, MOTORCYCLE])

        stats = session.stats()
        assert stats.tracked_by_class == {"person": 1}
        assert stats.by_class == stats.tracked_by_class
