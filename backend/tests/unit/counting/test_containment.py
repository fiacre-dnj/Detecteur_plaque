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

from tests.support.builders import (
    BICYCLE,
    BUS,
    CAR,
    CLASS_LABELS,
    MOTORCYCLE,
    PERSON,
    TRUCK,
    make_line,
    track_path,
)
from traffic_analysis.features.counting.domain.models import (
    BoundingBox,
    TrackObservation,
    class_group,
)
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


def _observation(track_id: int, box: BoundingBox, class_id: int = TRUCK) -> TrackObservation:
    # Le label vient de la table partagée et non d'un ternaire : depuis ADR 0056 le
    # domaine lit `label` pour décider d'un groupe, donc une observation étiquetée
    # « car » avec un identifiant de moto ferait passer un test pour la mauvaise
    # raison — et le ternaire d'avant faisait exactement cela de toute classe
    # autre que `truck`.
    return TrackObservation(
        track_id=track_id,
        class_id=class_id,
        label=CLASS_LABELS[class_id],
        score=0.9,
        box=box,
    )


class TestSuppressionDansLaSession:
    def test_la_cabine_incluse_ne_devient_pas_une_piste(self) -> None:
        """Le cas cible : elle serait sinon comptée en plus du véhicule entier."""
        session = _session()
        whole = _observation(1, BoundingBox(100.0, 400.0, 400.0, 200.0))
        cabin = _observation(2, BoundingBox(120.0, 420.0, 100.0, 100.0))

        outcome = session.feed(0, 0.0, [whole, cabin])

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
        outcome = session.feed(0, 0.0, [small, large])

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

        outcome = session.feed(0, 0.0, [truck, car])

        assert len(outcome.tracks) == 2

    def test_deux_vehicules_cote_a_cote_sont_conserves(self) -> None:
        session = _session()
        left = _observation(1, BoundingBox(100.0, 400.0, 120.0, 80.0))
        right = _observation(2, BoundingBox(300.0, 400.0, 120.0, 80.0))

        outcome = session.feed(0, 0.0, [left, right])

        assert len(outcome.tracks) == 2

    def test_une_seule_detection_traverse_sans_traitement(self) -> None:
        session = _session()

        outcome = session.feed(0, 0.0, [_observation(1, BoundingBox(0.0, 0.0, 80.0, 60.0))])

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
            session.feed(index, index * FRAME_MS, [big, small])

        assert session.stats().crossings == 1

    def test_la_suppression_est_comptee_dans_le_diagnostic(self) -> None:
        # Une suppression silencieuse serait aussi opaque que le doublon qu'elle
        # évite : c'est ce chiffre qui dit si le seuil est bien réglé.
        session = _session()
        whole = _observation(1, BoundingBox(100.0, 400.0, 400.0, 200.0))
        cabin = _observation(2, BoundingBox(120.0, 420.0, 100.0, 100.0))

        session.feed(0, 0.0, [whole, cabin])

        assert session.stats().diagnostics.contained_out == 1

    def test_aucune_suppression_laisse_le_compteur_a_zero(self) -> None:
        session = _session()

        session.feed(0, 0.0, [_observation(1, BoundingBox(0.0, 0.0, 80.0, 60.0))])

        assert session.stats().diagnostics.contained_out == 0


class TestGroupesDeClasses:
    """La famille d'objets physiquement exclusifs — ADR 0056.

    Le seuil de 0,9 a été calibré sur une *voiture* devant un camion, à 0,8. La
    mesure divisant par la plus petite aire, un objet nettement plus petit atteint
    1,000 sans effort : c'est structurel, pas accidentel, et cela frappe exactement
    les deux classes qu'on peine à détecter.
    """

    def test_les_trois_cas_qui_atteignent_un(self) -> None:
        """La prémisse du correctif, vérifiée avant tout le reste.

        Si l'une de ces containments cessait d'être au-dessus du seuil, les tests
        suivants passeraient pour la mauvaise raison — ils vérifieraient une garde
        qui n'a rien à garder.
        """
        moto = BoundingBox(880.0, 470.0, 60.0, 95.0)
        camion = BoundingBox(800.0, 400.0, 250.0, 240.0)
        pieton = BoundingBox(900.0, 540.0, 30.0, 80.0)
        bus = BoundingBox(850.0, 480.0, 200.0, 160.0)
        pilote = BoundingBox(512.0, 545.0, 36.0, 110.0)
        machine = BoundingBox(500.0, 545.0, 60.0, 145.0)

        assert camion.containment(moto) >= CONTAINMENT_THRESHOLD
        assert bus.containment(pieton) >= CONTAINMENT_THRESHOLD
        assert machine.containment(pilote) >= CONTAINMENT_THRESHOLD

    def test_une_moto_dans_la_boite_d_un_camion_survit(self) -> None:
        """Elle ne laissait aucune trace : ni piste, ni observation, ni diagnostic."""
        session = _session()
        camion = _observation(1, BoundingBox(800.0, 400.0, 250.0, 240.0), class_id=TRUCK)
        moto = _observation(2, BoundingBox(880.0, 470.0, 60.0, 95.0), class_id=MOTORCYCLE)

        outcome = session.feed(0, 0.0, [camion, moto])

        assert {track.track_id for track in outcome.tracks} == {1, 2}
        assert session.stats().diagnostics.contained_out == 0

    def test_un_pieton_devant_un_bus_survit(self) -> None:
        session = _session()
        bus = _observation(1, BoundingBox(850.0, 480.0, 200.0, 160.0), class_id=BUS)
        pieton = _observation(2, BoundingBox(900.0, 540.0, 30.0, 80.0), class_id=PERSON)

        outcome = session.feed(0, 0.0, [bus, pieton])

        assert {track.track_id for track in outcome.tracks} == {1, 2}

    def test_un_pilote_dans_la_boite_de_sa_moto_survit(self) -> None:
        """Le cas qui rend le correctif du NMS insuffisant à lui seul.

        Un pilote qui survit à `agnostic_nms` — leur IoU réaliste vaut 0,407, sous le
        seuil de 0,45 — était réeffacé ici, à containment 1,000. Corriger le NMS sans
        corriger la containment n'aurait rien rendu.
        """
        session = _session()
        machine = _observation(1, BoundingBox(500.0, 545.0, 60.0, 145.0), class_id=MOTORCYCLE)
        pilote = _observation(2, BoundingBox(512.0, 545.0, 36.0, 110.0), class_id=PERSON)

        outcome = session.feed(0, 0.0, [machine, pilote])

        assert {track.track_id for track in outcome.tracks} == {1, 2}

    def test_le_franchissement_d_une_moto_englobee_est_compte(self) -> None:
        """La conséquence qui compte : le **total**, comme pour le piège 6.

        Sans la garde, la moto ne franchit rien — elle n'existe à aucune image — et
        le carrefour affiche un camion là où deux véhicules sont passés.
        """
        session = _session()
        camion = track_path(1, TRUCK, [(900.0, 500.0), (1020.0, 500.0)], box_size=(250.0, 240.0))
        moto = track_path(2, MOTORCYCLE, [(900.0, 520.0), (1020.0, 520.0)], box_size=(60.0, 95.0))

        for index, (gros, petit) in enumerate(zip(camion, moto, strict=True)):
            session.feed(index, index * FRAME_MS, [gros, petit])

        stats = session.stats()
        assert stats.crossings == 2
        assert stats.by_class == {"truck": 1, "motorcycle": 1}

    def test_un_velo_et_une_moto_restent_dedupliques(self) -> None:
        """Trois groupes et pas deux : un scooter sort sous l'une ou l'autre classe.

        `bicycle` et `motorcycle` sont un même objet vu par deux classes voisines.
        Les séparer redonnerait sur les deux-roues le doublon que le piège 6 décrit
        sur les véhicules à moteur.
        """
        session = _session()
        moto = _observation(1, BoundingBox(500.0, 545.0, 60.0, 145.0), class_id=MOTORCYCLE)
        velo = _observation(2, BoundingBox(505.0, 560.0, 50.0, 120.0), class_id=BICYCLE)
        assert moto.box.containment(velo.box) >= CONTAINMENT_THRESHOLD

        outcome = session.feed(0, 0.0, [moto, velo])

        assert len(outcome.tracks) == 1

    def test_la_cabine_car_dans_un_semi_truck_reste_dedupliquee(self) -> None:
        """**La non-régression du piège 6**, et la raison du groupe plutôt que du label.

        Le détecteur ne nomme pas toujours la cabine comme le semi. Une garde écrite
        `first.label != second.label` rouvrirait exactement la panne que ce correctif
        est censé préserver : deux pistes, deux véhicules, deux franchissements.
        """
        session = _session()
        semi = _observation(1, BoundingBox(300.0, 400.0, 400.0, 200.0), class_id=TRUCK)
        cabine = _observation(2, BoundingBox(320.0, 420.0, 120.0, 160.0), class_id=CAR)
        assert semi.label != cabine.label

        outcome = session.feed(0, 0.0, [semi, cabine])

        assert [track.track_id for track in outcome.tracks] == [1]
        assert session.stats().diagnostics.contained_out == 1


class TestClassGroup:
    """La fonction pure, seule juge — et son repli."""

    def test_les_deux_roues_sont_un_groupe_a_part(self) -> None:
        assert class_group("motorcycle") == class_group("bicycle")
        assert class_group("motorcycle") != class_group("car")
        assert class_group("motorcycle") != class_group("person")

    def test_les_vehicules_a_moteur_partagent_leur_groupe(self) -> None:
        assert (
            class_group("car") == class_group("bus") == class_group("truck") == class_group("train")
        )

    def test_un_label_inconnu_rejoint_les_vehicules_a_moteur(self) -> None:
        """Le repli conservateur : il garde le comportement d'avant les groupes.

        Un label inconnu vient d'un modèle entraîné hors COCO — une voiture nommée
        autrement, typiquement. Lui donner un groupe à part lui retirerait la
        déduplication du piège 6 en silence.
        """
        assert class_group("voiture") == class_group("car")

    def test_deux_boites_de_meme_label_sont_toujours_du_meme_groupe(self) -> None:
        """La propriété qui protège le cas cible **par construction**, pas par la table."""
        for label in ("truck", "car", "motorcycle", "person", "inconnu"):
            assert class_group(label) == class_group(label)
