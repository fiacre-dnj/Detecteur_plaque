"""La suppression des boîtes incluses — piège 6 de `prompt/13`.

Sur un bus ou un semi-remorque, le détecteur émet parfois une boîte sur la cabine
**et** une sur le véhicule entier. Leur IoU vaut environ 0,3 : sous n'importe quel
seuil raisonnable, donc le NMS les garde toutes les deux. Résultat, deux pistes,
deux identités, deux franchissements — un total trop haut que rien n'explique.

Le critère qui les attrape est la *containment* (`intersection / min(aire)`), pas
l'IoU. Le seuil est sévère parce que l'erreur symétrique — supprimer un vrai
véhicule — est bien pire : sous-compter est la panne la plus difficile à remarquer.
"""

from __future__ import annotations

import numpy as np

from tests.support.builders import CAR, TRUCK, make_line, track_path
from traffic_analysis.features.counting.domain.models import BoundingBox, TrackObservation
from traffic_analysis.features.counting.domain.tracking_session import (
    CONTAINMENT_THRESHOLD,
    AnalysisSession,
    SessionConfig,
)

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FRAME_MS = 40.0


class TestContainment:
    """La mesure elle-même, sur `BoundingBox`."""

    def test_une_boite_entierement_incluse_vaut_un(self) -> None:
        whole = BoundingBox(100.0, 100.0, 400.0, 200.0)
        cabin = BoundingBox(120.0, 120.0, 100.0, 100.0)

        assert whole.containment(cabin) == 1.0

    def test_la_mesure_est_symetrique(self) -> None:
        # Elle divise par la plus petite aire : l'ordre des arguments ne peut donc
        # pas changer le verdict, et aucun appelant n'a à s'en soucier.
        whole = BoundingBox(100.0, 100.0, 400.0, 200.0)
        cabin = BoundingBox(120.0, 120.0, 100.0, 100.0)

        assert whole.containment(cabin) == cabin.containment(whole)

    def test_deux_boites_disjointes_valent_zero(self) -> None:
        assert (
            BoundingBox(0.0, 0.0, 50.0, 50.0).containment(BoundingBox(500.0, 500.0, 50.0, 50.0))
            == 0.0
        )

    def test_des_boites_qui_se_touchent_par_un_bord_valent_zero(self) -> None:
        # Contact sans recouvrement : l'aire d'intersection est nulle, pas
        # infinitésimale. Un `>=` mal placé rendrait ici une valeur non nulle.
        assert (
            BoundingBox(0.0, 0.0, 50.0, 50.0).containment(BoundingBox(50.0, 0.0, 50.0, 50.0)) == 0.0
        )

    def test_une_boite_degeneree_ne_divise_pas_par_zero(self) -> None:
        assert BoundingBox(0.0, 0.0, 0.0, 0.0).containment(BoundingBox(0.0, 0.0, 10.0, 10.0)) == 0.0

    def test_l_iou_ne_verrait_pas_le_cas_cible(self) -> None:
        """La justification du choix de mesure, en chiffres.

        Une containment de 1,0 pour une IoU de 0,125 : c'est tout l'écart entre
        « le NMS garde les deux » et « la cabine est écartée ».
        """
        whole = BoundingBox(0.0, 0.0, 400.0, 200.0)  # 80 000 px²
        cabin = BoundingBox(0.0, 0.0, 100.0, 100.0)  # 10 000 px²

        intersection = whole.intersection_area(cabin)
        union = whole.area + cabin.area - intersection

        assert whole.containment(cabin) == 1.0
        assert intersection / union == 0.125


def _session(**overrides: object) -> AnalysisSession:
    # Ligne **verticale** au milieu de l'image : les trajectoires de ces tests
    # sont horizontales, donc elles la traversent.
    config = SessionConfig(
        lines=(make_line("l1", a=(960.0, 0.0), b=(960.0, 1080.0)),),
        min_hits=1,
        **overrides,  # type: ignore[arg-type]
    )
    return AnalysisSession(config, FRAME_WIDTH, FRAME_HEIGHT)


def _blank() -> np.ndarray:
    return np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)


def _observation(track_id: int, box: BoundingBox, class_id: int = TRUCK) -> TrackObservation:
    return TrackObservation(
        track_id=track_id,
        class_id=class_id,
        label="truck" if class_id == TRUCK else "car",
        score=0.9,
        box=box,
    )


class TestSuppressionDansLaSession:
    def test_la_cabine_incluse_ne_devient_pas_une_piste(self) -> None:
        """Le cas cible : elle serait sinon comptée en plus du véhicule entier."""
        session = _session()
        whole = _observation(1, BoundingBox(100.0, 400.0, 400.0, 200.0))
        cabin = _observation(2, BoundingBox(120.0, 420.0, 100.0, 100.0))

        outcome = session.feed(0, 0.0, _blank(), [whole, cabin])

        assert len(outcome.tracks) == 1
        assert outcome.tracks[0].track_id == 1

    def test_c_est_la_plus_petite_qui_part(self) -> None:
        # La cabine est un morceau du véhicule : c'est la boîte du véhicule entier
        # qui décrit l'objet physique, et elle doit survivre. Garder la petite
        # fausserait le centroïde, donc l'instant du franchissement.
        session = _session()
        small = _observation(7, BoundingBox(120.0, 420.0, 100.0, 100.0))
        large = _observation(9, BoundingBox(100.0, 400.0, 400.0, 200.0))

        # Ordre inversé : la plus petite est présentée en premier.
        outcome = session.feed(0, 0.0, _blank(), [small, large])

        assert [track.track_id for track in outcome.tracks] == [9]

    def test_une_voiture_devant_un_camion_est_conservee(self) -> None:
        """**Le garde-fou qui rend le seuil sévère nécessaire.**

        Une voiture roulant devant un camion peut être à 0,8 dans sa boîte. La
        supprimer effacerait un vrai véhicule — et sous-compter est l'erreur la
        plus difficile à remarquer, parce que rien ne la signale.
        """
        session = _session()
        truck = _observation(1, BoundingBox(100.0, 400.0, 400.0, 200.0), class_id=TRUCK)
        # 80 % de la voiture est dans la boîte du camion : sous le seuil de 0,9.
        car = _observation(2, BoundingBox(420.0, 420.0, 100.0, 100.0), class_id=CAR)
        assert truck.box.containment(car.box) < CONTAINMENT_THRESHOLD

        outcome = session.feed(0, 0.0, _blank(), [truck, car])

        assert len(outcome.tracks) == 2

    def test_deux_vehicules_cote_a_cote_sont_conserves(self) -> None:
        session = _session()
        left = _observation(1, BoundingBox(100.0, 400.0, 120.0, 80.0))
        right = _observation(2, BoundingBox(300.0, 400.0, 120.0, 80.0))

        outcome = session.feed(0, 0.0, _blank(), [left, right])

        assert len(outcome.tracks) == 2

    def test_une_seule_detection_traverse_sans_traitement(self) -> None:
        session = _session()

        outcome = session.feed(
            0, 0.0, _blank(), [_observation(1, BoundingBox(0.0, 0.0, 80.0, 60.0))]
        )

        assert len(outcome.tracks) == 1

    def test_le_doublon_ne_produit_pas_un_second_franchissement(self) -> None:
        """La conséquence qui compte : le **total**.

        C'est ce chiffre-là que le piège fausse — deux franchissements pour un
        camion, sans la moindre erreur ni le moindre indice à l'écran.
        """
        session = _session()
        whole = track_path(1, TRUCK, [(900.0, 500.0), (1020.0, 500.0)], box_size=(400.0, 200.0))
        cabin = track_path(2, TRUCK, [(900.0, 500.0), (1020.0, 500.0)], box_size=(100.0, 100.0))

        for index, (big, small) in enumerate(zip(whole, cabin, strict=True)):
            session.feed(index, index * FRAME_MS, _blank(), [big, small])

        assert session.stats().crossings == 1

    def test_la_suppression_est_comptee_dans_le_diagnostic(self) -> None:
        # Une suppression silencieuse serait aussi opaque que le doublon qu'elle
        # évite : c'est ce chiffre qui dit si le seuil est bien réglé.
        session = _session()
        whole = _observation(1, BoundingBox(100.0, 400.0, 400.0, 200.0))
        cabin = _observation(2, BoundingBox(120.0, 420.0, 100.0, 100.0))

        session.feed(0, 0.0, _blank(), [whole, cabin])

        assert session.stats().diagnostics.contained_out == 1

    def test_aucune_suppression_laisse_le_compteur_a_zero(self) -> None:
        session = _session()

        session.feed(0, 0.0, _blank(), [_observation(1, BoundingBox(0.0, 0.0, 80.0, 60.0))])

        assert session.stats().diagnostics.contained_out == 0
