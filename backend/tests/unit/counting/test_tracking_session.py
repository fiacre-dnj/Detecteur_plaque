"""La session de comptage — les scénarios normatifs de prompt/03 §7.

Ces tests utilisent des `TrackObservation` fabriquées à la main : **aucun moteur,
aucun modèle, aucun GPU**. C'est la décision d'architecture qui rend tout le reste
testable. Et depuis ADR 0016, `feed()` ne reçoit même plus l'image : le comptage ne
touche plus un seul pixel.

La classe la plus précieuse du fichier est `TestNumerotationDesVehicules`. Elle
verrouille les deux propriétés que la ré-identification empêchait de tenir — un
numéro strictement croissant et jamais réattribué — **et** la conséquence assumée
qui va avec : un véhicule occulté plus longtemps que `max_lost_ms` compte deux fois.
Un test qui affirme la contrepartie autant que le bénéfice est ce qui empêche de
« corriger » l'un en cassant l'autre.
"""

from __future__ import annotations

import pytest

from tests.support.builders import (
    CAR,
    PERSON,
    TRUCK,
    box_at,
    make_line,
    make_zone,
    track_path,
)
from traffic_analysis.features.counting.domain.models import BoundingBox, PlateDetection
from traffic_analysis.features.counting.domain.tracking_session import (
    AnalysisSession,
    SessionConfig,
)

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FPS = 25.0
FRAME_MS = 1000.0 / FPS


def _config(**overrides: object) -> SessionConfig:
    base: dict[str, object] = {"lines": (make_line("l1"),), "min_hits": 2}
    base.update(overrides)
    return SessionConfig(**base)  # type: ignore[arg-type]


def _plate(text: str, text_score: float, score: float = 0.71) -> PlateDetection:
    """Une plaque lue, telle que le service la remet à `record_plates`.

    Le texte est passé **brut** — c'est le domaine qui le canonicalise, et c'est
    précisément ce que les tests de cette section vérifient.
    """
    return PlateDetection(
        box=BoundingBox(1.0, 1.0, 20.0, 8.0), score=score, text=text, text_score=text_score
    )


class TestVehiculeQuiTraverse:
    def test_un_vehicule_qui_traverse_donne_un_unique_et_un_franchissement(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        path = [(900.0, 300.0 + step * 50.0) for step in range(10)]
        observations = track_path(1, CAR, path)

        for index, observation in enumerate(observations):
            session.feed(index, index * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.tracked_vehicles == 1
        assert stats.crossings == 1
        assert stats.by_line["l1"].total == 1

    def test_le_badge_compte_est_pose_sur_la_piste(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        path = [(900.0, 300.0 + step * 50.0) for step in range(10)]
        observations = track_path(1, CAR, path)

        outcome = None
        for index, observation in enumerate(observations):
            outcome = session.feed(index, index * FRAME_MS, (observation,))

        assert outcome is not None
        assert outcome.tracks[0].counted is True

    def test_le_registre_decrit_le_vehicule(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        path = [(900.0, 300.0 + step * 50.0) for step in range(10)]

        for index, observation in enumerate(track_path(1, CAR, path)):
            session.feed(index, index * FRAME_MS, (observation,))

        vehicles = session.vehicles()
        assert len(vehicles) == 1
        record = vehicles[0]
        assert record.label == "car"
        assert record.first_seen_ms == 0.0
        assert record.last_seen_ms == pytest.approx(9 * FRAME_MS)
        assert len(record.crossed_lines) == 1
        assert record.crossed_lines[0].line_id == "l1"


class TestNumerotationDesVehicules:
    """Les propriétés du numéro de véhicule, et le prix qu'elles coûtent.

    Chaque test de cette classe verrouille une facette d'ADR 0016. Les deux
    premiers sont les héritiers directs des tests de ré-identification qu'ils
    remplacent : le scénario est identique, **l'attendu est inversé**, et c'est
    exactement ce qu'on veut voir écrit noir sur blanc.
    """

    def test_un_vehicule_occulte_trop_longtemps_compte_deux_fois(self) -> None:
        """La conséquence assumée d'ADR 0016, verrouillée par un test.

        Le véhicule traverse, disparaît trois secondes (plus que `max_lost_ms`) et
        revient avec un **nouvel id de piste** — c'est ce que fait BoT-SORT au-delà
        de `track_buffer`. Plus rien ne recolle les deux morceaux, donc cela fait
        deux véhicules.

        Ce test remplace celui qui attendait 1. Il n'est pas là par acquit de
        conscience : il documente le prix payé pour un numéro qui ne revient jamais
        en arrière, et il échouera si quelqu'un réintroduit un recollage par
        apparence sans écrire d'ADR.

        **Aucune frame vide entre les deux passes**, comme dans le test qu'il
        remplace : la mort de l'ancienne piste et la naissance de sa remplaçante
        tombent dans le *même* appel à `feed`, parce que c'est ce que fait le moteur.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)

        # Traversée : de y=300 à y=750, la ligne est à y=500.
        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))

        assert session.stats().crossings == 1

        # Trois secondes plus tard, la piste 7 remplace la piste 1 dans le même appel.
        for step in range(10):
            observation = track_path(7, CAR, [(910.0, 760.0 + step * 5.0)])[0]
            session.feed(100 + step, 4000.0 + step * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.tracked_vehicles == 2, "un nouvel id de piste est un nouveau véhicule"
        # Il ne recroise pas la ligne : le second véhicule est vu sans être compté.
        assert stats.crossings == 1
        assert stats.crossed_unique == 1
        assert stats.tracked_vehicles - stats.crossed_unique == 1

    def test_un_vehicule_revenu_qui_recroise_compte_un_second_passage(self) -> None:
        """Le pendant du précédent : deux véhicules, deux franchissements, deux sens.

        Même scénario, mais le second morceau **remonte** et repasse la ligne. Le
        franchissement compte, dans le sens négatif — c'est ce qu'un aller-retour
        doit produire. Ce qui change, c'est que le comptage n'a plus besoin d'un
        « ré-armement » pour l'autoriser : chaque franchissement observé compte.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))
        assert session.stats().crossings == 1

        for step in range(10):
            observation = track_path(7, CAR, [(910.0, 760.0 - step * 50.0)])[0]
            session.feed(100 + step, 4000.0 + step * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.tracked_vehicles == 2
        assert stats.crossings == 2
        assert stats.by_line["l1"].positive.total == 1, "la descente compte en positif"
        assert stats.by_line["l1"].negative.total == 1, "la remontée compte en négatif"
        assert stats.by_line["l1"].total == 2, "le total est dérivé des deux sens"

    def test_un_id_de_piste_reactive_dans_la_fenetre_garde_son_numero(self) -> None:
        """Une occlusion **courte** ne fabrique pas un véhicule de plus.

        Ultralytics réactive une piste perdue avec son propre identifiant tant
        qu'elle tient dans `track_buffer`. La session n'a alors rien abandonné —
        `max_lost_ms` en est le miroir exact — donc la piste retrouve son
        `SessionTrack`, ses `hits` et son numéro.

        C'est ce qui rend le comptage utilisable : sans cela, chaque poteau, chaque
        camion croisé et chaque tremblement de boîte ajouterait un véhicule.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(4):
            observation = track_path(1, CAR, [(900.0, 300.0 + index * 10.0)])[0]
            session.feed(index, index * FRAME_MS, (observation,))
        assert session.stats().tracked_vehicles == 1

        # Une seconde de silence — sous `max_lost_ms` — puis le même id revient.
        session.feed(50, 1000.0, ())
        for index in range(4):
            observation = track_path(1, CAR, [(920.0, 340.0 + index * 10.0)])[0]
            session.feed(100 + index, 1500.0 + index * FRAME_MS, (observation,))

        assert session.stats().tracked_vehicles == 1

    def test_un_id_reutilise_apres_la_fenetre_recoit_un_numero_neuf(self) -> None:
        """Le garde contre la fusion de deux véhicules distincts.

        Au-delà de `max_lost_ms`, la session a oublié la correspondance piste →
        numéro (`TrackNumbering.forget`). Un identifiant qui réapparaît reçoit donc
        un numéro neuf.

        **C'est aussi ce qui protège du compteur global d'Ultralytics.**
        `BaseTrack._count` est un attribut de classe : une session temps réel qui
        démarre pendant une analyse le remet à zéro, et l'analyse se remet à voir des
        identifiants 1, 2, 3. Sans cet oubli, ils rendraient d'anciens numéros et
        deux véhicules fusionneraient — un total qui baisse sans que rien à l'écran
        ne l'explique.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(4):
            observation = track_path(1, CAR, [(900.0, 300.0)])[0]
            session.feed(index, index * FRAME_MS, (observation,))
        session.feed(50, 3000.0, ())  # la piste 1 est abandonnée ici

        # Le même identifiant, bien plus tard et ailleurs dans l'image.
        for index in range(4):
            observation = track_path(1, CAR, [(300.0, 700.0)])[0]
            session.feed(500 + index, 90_000.0 + index * FRAME_MS, (observation,))

        assert session.stats().tracked_vehicles == 2

    def test_deux_vehicules_simultanes_recoivent_deux_numeros(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(10):
            y = 300.0 + index * 50.0
            observations = (
                track_path(1, CAR, [(700.0, y)])[0],
                track_path(2, CAR, [(1100.0, y)])[0],
            )
            session.feed(index, index * FRAME_MS, observations)

        stats = session.stats()
        assert stats.tracked_vehicles == 2
        assert stats.crossings == 2

    def test_les_numeros_sont_une_suite_partagee_par_tous_les_types(self) -> None:
        """La cohérence inter-types, verrouillée.

        Une voiture, un camion et un piéton reçoivent 1, 2 et 3 — **une seule
        suite**, pas un compteur par classe. Un `car#1` et un `truck#1` coexistants
        seraient deux véhicules portant le même badge à l'écran, et le registre
        n'aurait plus de clé.

        Ici les trois pistes se confirment, donc le total **est** le dernier numéro
        émis. Le test suivant montre le cas où les deux divergent.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        numbers: dict[int, int] = {}
        for index in range(6):
            y = 300.0 + index * 50.0
            observations = (
                track_path(1, CAR, [(600.0, y)])[0],
                track_path(2, TRUCK, [(900.0, y)])[0],
                track_path(3, PERSON, [(1200.0, y)])[0],
            )
            outcome = session.feed(index, index * FRAME_MS, observations)
            for track in outcome.tracks:
                if track.global_id:
                    numbers[track.track_id] = track.global_id

        assert numbers == {1: 1, 2: 2, 3: 3}
        assert session.stats().tracked_vehicles == 3
        assert max(numbers.values()) == session.stats().tracked_vehicles

    def test_un_scintillement_prend_un_numero_mais_n_est_pas_compte(self) -> None:
        """Émettre un numéro et compter un véhicule sont deux gestes distincts.

        Deux pistes naissent sur l'image 0 et prennent les numéros 1 et 2 — il leur
        faut un agrégat immédiatement, sinon la première lecture de plaque n'aurait
        nulle part où voter. La piste 99 disparaît aussitôt : son numéro reste émis et
        **n'entre jamais dans le total**.

        C'est de là que viennent les trous de la numérotation, et c'est le prix d'un
        badge qui ne change jamais en cours de route. Ne pas « corriger » cela en
        renumérotant à la confirmation : un même véhicule changerait de numéro entre
        sa première et sa deuxième image.
        """
        session = AnalysisSession(_config(min_hits=2), FRAME_WIDTH, FRAME_HEIGHT)

        outcome = session.feed(
            0,
            0.0,
            (
                track_path(1, CAR, [(600.0, 300.0)])[0],
                track_path(99, CAR, [(1500.0, 300.0)])[0],
            ),
        )
        assert sorted(track.global_id for track in outcome.tracks) == [1, 2]
        assert session.stats().tracked_vehicles == 0, "aucune piste n'est encore confirmée"

        # La piste 99 a disparu ; la piste 1 se confirme et devient le seul véhicule.
        outcome = session.feed(1, FRAME_MS, (track_path(1, CAR, [(600.0, 350.0)])[0],))
        assert outcome.tracks[0].global_id == 1
        assert session.stats().tracked_vehicles == 1

        # Une piste qui arrive plus tard prend le numéro suivant — le 2 est consommé.
        for index in (2, 3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                (
                    track_path(1, CAR, [(600.0, 350.0 + index * 20.0)])[0],
                    track_path(5, CAR, [(1000.0, 300.0 + index * 20.0)])[0],
                ),
            )
        assert sorted(track.global_id for track in outcome.tracks) == [1, 3]
        assert session.stats().tracked_vehicles == 2
        assert [record.global_id for record in session.vehicles()] == [1, 3]

    def test_le_registre_a_exactement_autant_de_lignes_que_de_vehicules(self) -> None:
        """`len(vehicles()) == tracked_vehicles`, le total rendu vérifiable.

        Les deux comptent les mêmes pistes confirmées. Sous la galerie, cette
        égalité tenait par coïncidence — le registre était indexé sur les agrégats et
        le total sur un compteur d'émission distinct.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(8):
            y = 300.0 + index * 50.0
            session.feed(
                index,
                index * FRAME_MS,
                (
                    track_path(1, CAR, [(600.0, y)])[0],
                    track_path(2, TRUCK, [(1000.0, y)])[0],
                ),
            )
        # Une piste d'une seule image, qui ne doit apparaître nulle part.
        session.feed(8, 8 * FRAME_MS, (track_path(42, CAR, [(50.0, 50.0)])[0],))

        stats = session.stats()
        assert stats.tracked_vehicles == 2
        assert len(session.vehicles()) == stats.tracked_vehicles
        assert [record.global_id for record in session.vehicles()] == [1, 2]

    def test_crossed_only_ne_garde_que_les_vehicules_qui_ont_franchi(self) -> None:
        """Le filtre de l'aperçu — la population que l'écran affiche (ADR 0023).

        Il existe pour ce qui **voyage**, pas pour ce qui s'affiche : l'aperçu
        d'une analyse en cours republie le registre entier plusieurs fois par
        minute, et sur une scène réelle deux tiers des objets suivis n'ont franchi
        aucune ligne — ils sont stationnés, ou hors du tracé.

        L'égalité `len(vehicles()) == tracked_vehicles` du test précédent ne vaut
        donc **pas** sous ce filtre, et c'est exactement pourquoi il est explicite.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        # La piste 1 traverse la ligne ; la piste 2 reste immobile loin d'elle.
        for index in range(10):
            session.feed(
                index,
                index * FRAME_MS,
                (
                    track_path(1, CAR, [(900.0, 300.0 + index * 50.0)])[0],
                    track_path(2, TRUCK, [(150.0, 150.0)])[0],
                ),
            )

        assert [record.global_id for record in session.vehicles()] == [1, 2]
        assert [record.global_id for record in session.vehicles(crossed_only=True)] == [1]

    def test_crossed_only_rend_les_memes_enregistrements_que_sans_filtre(self) -> None:
        """Le filtre **retire des lignes, il n'en modifie aucune**.

        C'est ce qui autorise l'aperçu et le résultat final à afficher le même
        tableau : si le filtre changeait un champ — une vitesse moyenne, un vote de
        plaque — le registre changerait sous les yeux de l'utilisateur à la fin de
        l'analyse, et l'écart se lirait comme un bug de comptage.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        for index in range(10):
            session.feed(
                index,
                index * FRAME_MS,
                (track_path(1, CAR, [(900.0, 300.0 + index * 50.0)])[0],),
            )

        assert session.vehicles(crossed_only=True) == tuple(
            record for record in session.vehicles() if record.crossed_lines
        )


class TestMasqueDeZone:
    def test_une_observation_hors_zone_ne_cree_aucune_piste(self) -> None:
        """Avec « ignorer hors zone », les zones sont la région d'intérêt.

        Une voiture en stationnement dans un coin de l'image ne coûte alors rien et
        n'entre dans aucun compteur.
        """
        zone = make_zone(
            "z1", points=((400.0, 200.0), (1500.0, 200.0), (1500.0, 800.0), (400.0, 800.0))
        )
        session = AnalysisSession(
            _config(zones=(zone,), mask_outside_zones=True), FRAME_WIDTH, FRAME_HEIGHT
        )

        # x = 100 : hors de la zone, qui commence à x = 400.
        for index, observation in enumerate(
            track_path(1, CAR, [(100.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.tracked_vehicles == 0
        assert stats.crossings == 0
        assert stats.active_tracks == 0
        assert stats.diagnostics.masked_out == 10

    def test_sans_masque_la_zone_n_est_qu_un_filtre_de_comptage(self) -> None:
        """Garde-fou : la même scène, masque désactivé, produit bien une piste."""
        zone = make_zone(
            "z1", points=((400.0, 200.0), (1500.0, 200.0), (1500.0, 800.0), (400.0, 800.0))
        )
        session = AnalysisSession(
            _config(zones=(zone,), mask_outside_zones=False), FRAME_WIDTH, FRAME_HEIGHT
        )

        for index, observation in enumerate(
            track_path(1, CAR, [(100.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))

        assert session.stats().tracked_vehicles == 1


class TestVoteDeClasse:
    def test_une_lecture_qui_alterne_ne_fait_pas_osciller_le_compteur(self) -> None:
        """`identity_label` reste stable, et `tracked_by_class` somme aux uniques."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        lectures = [TRUCK, TRUCK, CAR, TRUCK, CAR, TRUCK, TRUCK, CAR, TRUCK, TRUCK]

        for index, class_id in enumerate(lectures):
            observation = track_path(1, class_id, [(900.0, 300.0 + index * 50.0)])[0]
            session.feed(index, index * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.tracked_by_class == {"truck": 1}
        assert sum(stats.tracked_by_class.values()) == stats.tracked_vehicles
        # Le franchissement est comptabilisé sous la classe votée.
        assert stats.by_line["l1"].by_class == {"truck": 1}


class TestStatistiques:
    def test_les_pistes_actives_sont_celles_de_la_derniere_frame(self) -> None:
        """« Objets suivis » est un instantané, pas la mémoire de la session.

        Une piste perdue survit jusqu'à `max_lost_ms` pour que le tracker puisse la
        réactiver avec son identifiant. La compter dans `active_tracks` faisait
        redescendre le chiffre deux secondes et demie **après** les boîtes de
        l'écran, et le rendait incomparable à celui de la relecture, que le client
        calcule sur les pistes de la frame.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(6)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))
        assert session.stats().active_tracks == 1

        # La piste cesse d'être rapportée, mais reste retenue : la session ne l'a pas
        # oubliée (elle garde son numéro), l'écran ne la dessine plus.
        session.feed(6, 6 * FRAME_MS, ())
        stats = session.stats()
        assert stats.active_tracks == 0
        assert stats.tracked_vehicles == 1

    def test_les_franchissements_sont_derives_du_detail_par_ligne(self) -> None:
        session = AnalysisSession(
            _config(
                lines=(
                    make_line("haute", a=(0.0, 400.0), b=(1920.0, 400.0)),
                    make_line("basse", a=(0.0, 700.0), b=(1920.0, 700.0)),
                )
            ),
            FRAME_WIDTH,
            FRAME_HEIGHT,
        )

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 60.0) for step in range(12)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))

        stats = session.stats()
        # L'invariant 3, celui qui ne bouge pas : le total est **dérivé** du détail
        # par ligne, jamais accumulé à côté.
        assert stats.crossings == sum(tally.total for tally in stats.by_line.values())
        assert sum(stats.by_class.values()) == stats.crossings
        # Le véhicule traverse les deux lignes, et compte donc **deux passages**
        # (ADR 0014). C'était 1 sous ADR 0009, où la première ligne franchie portait
        # seule le total.
        assert stats.crossings == 2
        assert stats.by_line["haute"].total == 1
        assert stats.by_line["basse"].total == 1
        # La ventilation par catégorie est dérivée du même `by_class` : sa somme est
        # le total, par construction.
        assert stats.by_category == {"vehicle": 2}
        assert sum(stats.by_category.values()) == stats.crossings

    def test_le_debit_est_nul_sous_trois_secondes_de_flux(self) -> None:
        """En dessous de 3 s, l'extrapolation oscille trop pour être publiable.

        Un chiffre qui saute de 12 à 240 véhicules par minute décrédibilise tout
        le reste de l'écran.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.analysed_scene_ms < 3000.0
        assert stats.vehicles_per_minute == 0.0

    def test_au_dela_de_trois_secondes_le_debit_est_publie(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(120):  # 120 frames à 25 fps = 4,8 s
            y = 300.0 + (index % 10) * 50.0
            observation = track_path(1, CAR, [(900.0, y)])[0]
            session.feed(index, index * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.analysed_scene_ms >= 3000.0
        assert stats.vehicles_per_minute > 0.0

    def test_le_temps_ecoule_est_le_temps_de_scene_analyse(self) -> None:
        """Côté serveur il n'y a pas d'attente d'utilisateur à mesurer.

        Le champ reste dans le contrat parce que l'interface affiche les deux, mais
        il ne doit pas être renseigné avec une horloge murale.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        for index, observation in enumerate(track_path(1, CAR, [(900.0, 300.0)] * 5)):
            session.feed(index, index * FRAME_MS, (observation,))

        stats = session.stats()
        assert stats.elapsed_ms == stats.analysed_scene_ms
        assert stats.elapsed_ms == pytest.approx(4 * FRAME_MS)

    def test_le_diagnostic_distingue_confirme_et_provisoire(self) -> None:
        """« Le compte est faux » n'est diagnosticable que si l'on voit pourquoi."""
        session = AnalysisSession(_config(min_hits=5), FRAME_WIDTH, FRAME_HEIGHT)

        session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        stats = session.stats()

        assert stats.diagnostics.confirmed_tracks == 0
        assert stats.diagnostics.tentative_tracks == 1

    def test_le_diagnostic_range_les_observations_de_part_et_d_autre_du_seuil(self) -> None:
        """Les deux compteurs de score, **qui ne valaient plus jamais autre chose que zéro**.

        Personne ne les renseignait : le domaine annonçait que l'adaptateur le ferait
        « s'il peut les observer », et l'adaptateur ne l'a jamais fait. Conséquence
        visible à l'écran, sur *toutes* les analyses : le panneau de diagnostic
        affichait deux zéros et déclenchait son alerte « aucune détection, à aucun
        seuil » — un message alarmant, faux, qui envoyait chercher le défaut dans la
        vidéo alors que le comptage marchait.

        Ce que mesure `rescued_by_low_score` est la bande basse de BoT-SORT en train de
        travailler : une observation sous le seuil de l'utilisateur prolonge une piste
        sans jamais en ouvrir une (ADR 0024).
        """
        session = AnalysisSession(_config(confidence_threshold=0.5), FRAME_WIDTH, FRAME_HEIGHT)

        # Trois images au-dessus du seuil, deux en dessous — la piste survit aux
        # secondes grâce à la bande basse, ce que le diagnostic doit rendre lisible.
        forte = track_path(1, CAR, [(900.0, 300.0)] * 3, score=0.9)
        faible = track_path(1, CAR, [(900.0, 320.0)] * 2, score=0.2)
        for index, observation in enumerate([*forte, *faible]):
            session.feed(index, index * FRAME_MS, (observation,))

        diagnostics = session.stats().diagnostics
        assert diagnostics.high_detections == 3
        assert diagnostics.rescued_by_low_score == 2

    def test_une_observation_masquee_n_est_comptee_qu_une_fois(self) -> None:
        """Elle appartient à `masked_out`, pas aux compteurs de score.

        Sinon le même rejet apparaîtrait dans deux lignes du panneau, et la somme des
        chiffres cesserait de décrire un chemin — ce que le diagnostic est.
        """
        session = AnalysisSession(
            _config(zones=(make_zone("z1"),), mask_outside_zones=True),
            FRAME_WIDTH,
            FRAME_HEIGHT,
        )

        # Hors de la zone par défaut (400..1500 × 200..800) : l'observation est
        # masquée avant d'atteindre le suivi.
        session.feed(0, 0.0, (track_path(1, CAR, [(100.0, 100.0)], score=0.9)[0],))

        diagnostics = session.stats().diagnostics
        assert diagnostics.masked_out == 1
        assert diagnostics.high_detections == 0
        assert diagnostics.rescued_by_low_score == 0

    def test_le_diagnostic_explique_une_ligne_restee_a_zero(self) -> None:
        """Une ligne à `0` dit si personne ne passe, ou si le trait est mal posé.

        Le véhicule monte vers la ligne (y=500), s'éteint à 30 px d'elle — sa boîte
        la recouvrait encore — puis le silence dépasse `max_lost_ms`. Sans ce
        chiffre, la ligne affiche exactement le même `0` qu'une ligne que personne
        n'emprunte, et rien à l'écran ne distingue les deux.

        L'attente est en **deux temps** parce que c'est l'ordre qui porte le sens :
        tant que la piste vit, elle n'a rien manqué.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 20.0) for step in range(9)])
        ):
            session.feed(index, index * FRAME_MS, (observation,))

        assert session.stats().crossings == 0
        assert session.stats().diagnostics.near_misses == {"l1": 0}, (
            "la piste vit encore : elle approche, elle n'a pas manqué"
        )

        # Le silence dépasse `max_lost_ms` : la session abandonne la piste, et
        # « elle s'est éteinte là » devient vrai.
        session.feed(100, 4000.0, ())

        assert session.stats().diagnostics.near_misses == {"l1": 1}
        assert session.stats().crossings == 0, "un quasi-franchissement ne compte pas"


class TestTimelineEtAliasing:
    def test_deux_frames_consecutives_ont_des_snapshots_differents(self) -> None:
        """Non-régression du piège d'aliasing de la timeline.

        Sans `snapshot()`, la timeline stockerait la référence vivante et **toutes
        ses lignes convergeraient vers l'état final** : à la relecture, chaque
        frame afficherait la position de sortie des véhicules.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        timeline = []

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(5)])
        ):
            outcome = session.feed(index, index * FRAME_MS, (observation,))
            timeline.append(tuple(track.snapshot() for track in outcome.tracks))

        premiere = timeline[0][0].centroid
        derniere = timeline[-1][0].centroid
        assert premiere != derniere
        assert premiere.y == pytest.approx(300.0)
        assert derniere.y == pytest.approx(500.0)


class TestPlaques:
    def test_la_meilleure_plaque_par_identite_est_conservee(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        outcome = session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        track = outcome.tracks[0]
        session.record_plates(track, (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.42),))

        outcome = session.feed(1, FRAME_MS, (track_path(1, CAR, [(900.0, 350.0)])[0],))
        track = outcome.tracks[0]
        session.record_plates(track, (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.71),))

        outcome = session.feed(2, 2 * FRAME_MS, (track_path(1, CAR, [(900.0, 400.0)])[0],))
        track = outcome.tracks[0]
        session.record_plates(track, (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.33),))

        assert session.vehicles()[0].best_plate_score == pytest.approx(0.71)

    def test_les_plaques_ne_survivent_pas_a_la_frame_suivante(self) -> None:
        """Garder les plaques d'une frame à l'autre ferait afficher une plaque là
        où le modèle n'en voit plus."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        outcome = session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        session.record_plates(
            outcome.tracks[0], (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.9),)
        )

        outcome = session.feed(1, FRAME_MS, (track_path(1, CAR, [(900.0, 350.0)])[0],))

        assert outcome.tracks[0].plates == []
        # …mais le meilleur score reste dans l'agrégat de l'identité.
        assert session.vehicles()[0].best_plate_score == pytest.approx(0.9)


class TestTexteDePlaque:
    """Le vote du texte, et le miroir qui le pose sur la piste vivante.

    Ce que ces tests protègent : **l'invariant 4 appliqué au texte**. Ils affirment
    trois choses qu'aucun test de `plate_vote.py` ne peut affirmer seul — que la
    normalisation tourne réellement dans le pipeline, que la source du texte affiché
    est l'agrégat et non la frame, et que le texte survit à la destruction de la
    piste par une occlusion longue.
    """

    def test_record_plates_normalise_avant_de_faire_voter(self) -> None:
        """Le lecteur rend du sale ; c'est le domaine qui canonicalise.

        L'entrée est en minuscules avec des espaces parasites. Que la sortie soit
        `AB-123-CD` **prouve** que `normalise_plate_text` a tourné — c'est tout
        l'intérêt de la placer dans le domaine plutôt que dans l'adaptateur.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                (track_path(1, CAR, [(900.0, 300.0 + index * 50.0)])[0],),
            )
            session.record_plates(outcome.tracks[0], (_plate(" ab-123-cd ", 0.95),))

        assert session.vehicles()[0].plate_text == "AB-123-CD"

    def test_le_texte_apparait_sur_la_piste_a_la_frame_suivante(self) -> None:
        """La source est l'agrégat, pas la frame — et cela se mesure.

        Les deux lectures du vote ont lieu sur les frames 0 et 1, donc le vote ne
        tranche qu'après le `record_plates` de la frame 1. Le miroir de la frame 2 est
        le premier à pouvoir poser le texte. Un texte qui apparaîtrait dès la frame 1
        signifierait qu'on publie la lecture de la frame courante.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        first = session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        session.record_plates(first.tracks[0], (_plate("AB123CD", 0.95),))
        assert first.tracks[0].plate_text == ""

        second = session.feed(1, FRAME_MS, (track_path(1, CAR, [(900.0, 350.0)])[0],))
        session.record_plates(second.tracks[0], (_plate("AB123CD", 0.95),))
        assert second.tracks[0].plate_text == ""

        third = session.feed(2, 2 * FRAME_MS, (track_path(1, CAR, [(900.0, 400.0)])[0],))
        assert third.tracks[0].plate_text == "AB123CD"
        assert third.tracks[0].plate_text_score == pytest.approx(0.95)

    def test_le_snapshot_emporte_le_texte_vote(self) -> None:
        """Sans cela, la relecture afficherait des boîtes muettes."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                (track_path(1, CAR, [(900.0, 300.0 + index * 50.0)])[0],),
            )
            session.record_plates(outcome.tracks[0], (_plate("AB123CD", 0.95),))

        snapshot = outcome.tracks[0].snapshot()
        assert snapshot.plate_text == "AB123CD"

    def test_le_texte_survit_a_une_occlusion_longue(self) -> None:
        """Le test qui compte le plus : la piste meurt, l'identité non.

        `_release_lost` détruit le `SessionTrack` au-delà de `max_lost_ms`. Quand
        BoT-SORT ressuscite le même id de piste, `_recover_identity` rend l'identité —
        et c'est le **miroir** qui repose le texte sur un objet tout neuf, sans une
        ligne de code dédiée à la réhydratation.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                (track_path(1, CAR, [(900.0, 300.0 + index * 50.0)])[0],),
            )
            session.record_plates(outcome.tracks[0], (_plate("AB123CD", 0.95),))
        assert outcome.tracks[0].plate_text == "AB123CD"

        # Silence assez long pour que `_release_lost` détruise la piste, mais dans la
        # fenêtre d'appariement de la galerie : c'est bien une reprise, pas un
        # nouveau véhicule.
        revival_ms = 3 * FRAME_MS + 1500.0
        revived = session.feed(80, revival_ms, (track_path(1, CAR, [(900.0, 460.0)])[0],))

        assert revived.tracks[0].global_id == outcome.tracks[0].global_id
        assert revived.tracks[0].plate_text == "AB123CD"

    def test_le_registre_porte_le_vote_et_non_la_derniere_lecture(self) -> None:
        """Trois `AB123CD` puis un `XY999ZZ` : le registre affiche `AB123CD`."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        readings = ("AB123CD", "AB123CD", "AB123CD", "XY999ZZ")

        for index, text in enumerate(readings):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                (track_path(1, CAR, [(900.0, 300.0 + index * 40.0)])[0],),
            )
            session.record_plates(outcome.tracks[0], (_plate(text, 0.95),))

        assert session.vehicles()[0].plate_text == "AB123CD"

    def test_une_lecture_unique_ne_pose_aucun_texte(self) -> None:
        """L'invariant 4 de bout en bout : une lecture n'est pas un vote."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        outcome = session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        session.record_plates(outcome.tracks[0], (_plate("AB123CD", 0.99),))

        outcome = session.feed(1, FRAME_MS, (track_path(1, CAR, [(900.0, 350.0)])[0],))

        assert outcome.tracks[0].plate_text == ""
        assert session.vehicles()[0].plate_text is None

    def test_une_plaque_sans_texte_laisse_le_registre_muet(self) -> None:
        """« Vue mais illisible » : un score de détection, aucun texte.

        C'est l'état que l'interface rate le plus facilement, et il doit être
        distinguable de « aucune plaque ».
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                (track_path(1, CAR, [(900.0, 300.0 + index * 50.0)])[0],),
            )
            session.record_plates(
                outcome.tracks[0], (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.71),)
            )

        record = session.vehicles()[0]
        assert record.plate_text is None
        assert record.plate_text_score is None
        assert record.best_plate_score == pytest.approx(0.71)

    def test_une_lecture_illisible_est_refusee_avant_le_vote(self) -> None:
        """`normalise_plate_text` rend `""` : la lecture ne vote pas du tout."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)

        for index in range(4):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                (track_path(1, CAR, [(900.0, 300.0 + index * 40.0)])[0],),
            )
            # « A1 » : deux caractères, sous le plancher de plausibilité.
            session.record_plates(outcome.tracks[0], (_plate("A1", 0.99),))
            assert outcome.tracks[0].plates[0].text is None

        assert session.vehicles()[0].plate_text is None

    def test_plate_text_is_confident_ne_leve_pas_sur_une_identite_inconnue(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        assert session.plate_text_is_confident(0) is False
        assert session.plate_text_is_confident(999) is False


class TestRegleDeCapture:
    """`should_capture` et `record_snapshot`, testés directement. ADR 0051.

    Ils n'avaient aucun test de domaine : tout passait par le service, où la cause et
    le rang sont choisis par du code d'application. Ici on interroge la règle
    elle-même, et c'est le seul endroit où l'échelle de priorité est visible d'un
    coup d'œil.
    """

    @staticmethod
    def _session_with_track() -> tuple[AnalysisSession, int]:
        """Deux images : la piste doit être **confirmée** pour entrer dans `vehicles()`."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        outcome = session.feed(1, FRAME_MS, (track_path(1, CAR, [(900.0, 350.0)])[0],))
        return session, outcome.tracks[0].global_id

    def test_la_premiere_capture_passe_quelle_que_soit_la_cause(self) -> None:
        session, global_id = self._session_with_track()

        assert session.should_capture(global_id, "appearance", 60.0) is True

    def test_une_cause_plus_prioritaire_passe_toujours(self) -> None:
        """Même avec un rang numériquement bien plus petit.

        C'est le cas qu'une comparaison de rangs entre tiers raterait : 0,80 de
        confiance de lecture contre 300 px de largeur.
        """
        session, global_id = self._session_with_track()
        session.record_snapshot(global_id, "appearance", 300.0, 0.0)

        assert session.should_capture(global_id, "plate_box", 40.0) is True
        assert session.should_capture(global_id, "plate_text", 0.80) is True

    def test_une_cause_moins_prioritaire_est_refusee_meme_avec_un_meilleur_rang(self) -> None:
        session, global_id = self._session_with_track()
        session.record_snapshot(global_id, "plate_text", 0.80, 0.0)

        assert session.should_capture(global_id, "plate_box", 999.0) is False
        assert session.should_capture(global_id, "appearance", 999.0) is False

    def test_a_cause_egale_seule_une_meilleure_vue_passe(self) -> None:
        session, global_id = self._session_with_track()
        session.record_snapshot(global_id, "plate_text", 0.90, 0.0)

        assert session.should_capture(global_id, "plate_text", 0.85) is False
        assert session.should_capture(global_id, "plate_text", 0.95) is True

    def test_la_marge_refuse_une_amelioration_trop_faible(self) -> None:
        """Le garde-fou d'ADR 0050, porté sur les tiers dont le rang est une largeur.

        À 1,15, une vue 10 % plus large ne suffit pas : sans cela, « plus large » est
        vrai à presque chaque image d'un véhicule qui approche.
        """
        session, global_id = self._session_with_track()
        session.record_snapshot(global_id, "appearance", 100.0, 0.0)

        assert session.should_capture(global_id, "appearance", 110.0, 1.15) is False
        assert session.should_capture(global_id, "appearance", 120.0, 1.15) is True

    def test_une_marge_sous_un_est_ramenee_a_un(self) -> None:
        """Comme `should_embed` : une marge inférieure à 1 rendrait la règle
        décroissante, donc remplaçable par moins bien."""
        session, global_id = self._session_with_track()
        session.record_snapshot(global_id, "plate_text", 0.90, 0.0)

        assert session.should_capture(global_id, "plate_text", 0.89, 0.5) is False

    def test_une_identite_inconnue_refuse_sans_lever(self) -> None:
        """`0` en est une, et le service la rencontre."""
        session, _ = self._session_with_track()

        assert session.should_capture(0, "plate_text", 0.99) is False
        # Et l'enregistrement se tait de la même façon.
        session.record_snapshot(0, "plate_text", 0.99, 0.0)

    def test_le_score_publie_n_existe_que_sur_le_tier_lu(self) -> None:
        """L'invariant que `record_snapshot` tient **par construction**.

        La confiance est dérivée de la cause et non passée à part : c'est ce qui
        interdit à un appelant d'annoncer `plate_box` en posant une confiance de
        lecture, donc de publier un `snapshotScore` que rien n'a lu.
        """
        session, global_id = self._session_with_track()

        session.record_snapshot(global_id, "plate_box", 82.0, 40.0)
        vehicle = session.vehicles()[0]
        assert vehicle.snapshot_kind == "plate_box"
        assert vehicle.snapshot_score is None
        assert vehicle.snapshot_ms == pytest.approx(40.0)

        session.record_snapshot(global_id, "plate_text", 0.77, 80.0)
        vehicle = session.vehicles()[0]
        assert vehicle.snapshot_kind == "plate_text"
        assert vehicle.snapshot_score == pytest.approx(0.77)

    def test_sans_capture_les_trois_champs_sont_nuls(self) -> None:
        """Le drapeau est `snapshot_ms` doublé de `snapshot_kind`, et ils vont ensemble."""
        session, _ = self._session_with_track()
        vehicle = session.vehicles()[0]

        assert vehicle.snapshot_kind is None
        assert vehicle.snapshot_ms is None
        assert vehicle.snapshot_score is None


class TestRegleDApparence:
    """`record_embedding` et `record_rematch` — deux règles monotones (ADR 0055).

    Elles ne l'étaient ni l'une ni l'autre, et les deux écrasements se voyaient à
    l'écran : une re-détection qui désignait le mauvais véhicule, et une règle
    monotone de ré-encodage qui repartait en arrière.
    """

    @staticmethod
    def _session_with_track() -> tuple[AnalysisSession, int]:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        outcome = session.feed(1, FRAME_MS, (track_path(1, CAR, [(900.0, 350.0)])[0],))
        return session, outcome.tracks[0].global_id

    def test_la_largeur_encodee_ne_redescend_jamais(self) -> None:
        """Sinon la règle monotone rouvre des ré-encodages déjà payés — ADR 0050 à l'envers.

        Depuis ADR 0055 un franchissement force un encodage quelle que soit la
        largeur de la boîte : sans cette clause, une boîte étroite au moment du
        passage abaisse la référence.
        """
        session, global_id = self._session_with_track()
        session.record_embedding(global_id, 300.0, None)
        session.record_embedding(global_id, 100.0, None)

        assert session.should_embed(global_id, 200.0) is False
        assert session.should_embed(global_id, 320.0) is True

    def test_la_ressemblance_a_la_requete_retient_la_meilleure(self) -> None:
        """**Le jumeau du défaut de la re-détection**, sur le même étage.

        Ce test affirmait l'inverse — « c'est une mesure sur la vue courante, pas un
        rang » — et il épinglait un défaut : un véhicule est encodé six à onze fois,
        donc publier la dernière mesure la rend **arbitraire**. Deux vues du même
        véhicule ne se ressemblent pas autant qu'on croit (0,387 au plus bas), donc
        une vue oblique ne réfute pas une vue franche.
        """
        session, global_id = self._session_with_track()
        session.record_embedding(global_id, 300.0, 0.90)
        session.record_embedding(global_id, 100.0, 0.40)

        assert session.vehicles()[0].match_score == pytest.approx(0.90)

    def test_une_meilleure_ressemblance_remonte(self) -> None:
        """Le pendant positif : la règle n'est pas « garder la première »."""
        session, global_id = self._session_with_track()
        session.record_embedding(global_id, 100.0, 0.40)
        session.record_embedding(global_id, 300.0, 0.90)

        assert session.vehicles()[0].match_score == pytest.approx(0.90)

    def test_une_mesure_tue_par_le_plancher_n_efface_pas_un_score_acquis(self) -> None:
        """`None` couvre deux états, et **aucun n'est une rétractation**.

        Le plancher de déploiement décide de ce qu'on publie, jamais de ce qu'on
        efface. Le cas mordait au défaut : `cosine_similarity` étant bornée à
        `[-1, 1]`, une similarité négative échoue `score >= 0.0` — donc le plancher
        par défaut suffisait à faire disparaître un véhicule des résultats qu'il
        avait mérités, tout en lui laissant la photo qui servait à le vérifier.
        """
        session, global_id = self._session_with_track()
        session.record_embedding(global_id, 300.0, 0.83)
        session.record_embedding(global_id, 320.0, None)

        vehicle = session.vehicles()[0]
        assert vehicle.match_score == pytest.approx(0.83)
        # La largeur, elle, a bien avancé : les deux champs sont monotones et
        # indépendants.
        assert session.should_embed(global_id, 310.0) is False

    def test_sans_aucune_mesure_le_score_reste_nul(self) -> None:
        """Encoder sans image de requête ne fabrique pas de ressemblance."""
        session, global_id = self._session_with_track()
        session.record_embedding(global_id, 300.0, None)

        assert session.vehicles()[0].match_score is None

    def test_la_re_detection_retient_la_meilleure_mesure(self) -> None:
        """**Le défaut mesuré sur une vidéo doublée.**

        Un véhicule franchit plusieurs lignes, donc compare plusieurs vues, et deux
        vues d'un même véhicule ne se ressemblent pas autant qu'on croit : la
        dernière mesure est souvent la plus mauvaise et désigne quelqu'un d'autre.
        """
        session, global_id = self._session_with_track()
        session.record_rematch(global_id, 7, 0.98)
        session.record_rematch(global_id, 9, 0.31)

        vehicle = session.vehicles()[0]
        assert vehicle.rematch_of == 7
        assert vehicle.rematch_score == pytest.approx(0.98)

    def test_une_meilleure_mesure_deplace_le_numero_avec_le_score(self) -> None:
        """Le numéro suit le score : jamais le meilleur score d'un antécédent avec le
        numéro d'un autre."""
        session, global_id = self._session_with_track()
        session.record_rematch(global_id, 7, 0.31)
        session.record_rematch(global_id, 9, 0.98)

        vehicle = session.vehicles()[0]
        assert vehicle.rematch_of == 9
        assert vehicle.rematch_score == pytest.approx(0.98)

    def test_une_identite_inconnue_se_tait(self) -> None:
        session, _ = self._session_with_track()

        session.record_rematch(0, 7, 0.99)
        session.record_embedding(0, 300.0, 0.99)

        assert session.vehicles()[0].rematch_of is None


class TestZones:
    def test_les_entrees_de_zone_sont_emises_et_le_registre_les_note(self) -> None:
        zone = make_zone(
            "z1", points=((400.0, 200.0), (1500.0, 200.0), (1500.0, 800.0), (400.0, 800.0))
        )
        session = AnalysisSession(_config(zones=(zone,)), FRAME_WIDTH, FRAME_HEIGHT)

        # Démarre hors zone (x=100), puis entre.
        session.feed(0, 0.0, (track_path(1, CAR, [(100.0, 300.0)])[0],))
        session.feed(1, FRAME_MS, (track_path(1, CAR, [(120.0, 300.0)])[0],))
        outcome = session.feed(2, 2 * FRAME_MS, (track_path(1, CAR, [(900.0, 300.0)])[0],))

        assert len(outcome.zone_events) == 1
        assert session.stats().by_zone["z1"].entries == 1
        assert session.vehicles()[0].zones_visited == ("z1",)


class TestConfigurationParDefaut:
    def test_max_lost_ms_est_le_miroir_du_track_buffer_du_tracker(self) -> None:
        """2500 ms ≈ 75 frames à 30 fps, la valeur de `botsort_reid.yaml`.

        Si l'une des deux change, l'autre doit suivre : sinon le moteur et le
        domaine ne sont plus d'accord sur ce qu'est « une piste perdue ».
        """
        assert SessionConfig().max_lost_ms == 2500.0

    def test_une_session_sans_geometrie_ne_compte_rien_mais_ne_leve_pas(self) -> None:
        """L'API refuse ce cas en 422 ; le domaine, lui, doit rester robuste."""
        session = AnalysisSession(SessionConfig(), FRAME_WIDTH, FRAME_HEIGHT)

        outcome = session.feed(0, 0.0, (track_path(1, CAR, [(900.0, 300.0)])[0],))

        assert outcome.crossings == ()
        assert session.stats().crossings == 0


def test_une_boite_hors_image_ne_fait_pas_lever_la_session() -> None:
    """Le suivi extrapole parfois une boîte au-delà du bord de l'image.

    Elle ne pose plus aucun problème depuis ADR 0016 : le comptage ne lit plus de
    pixels, donc il n'y a plus de recadrage à refuser. Le test reste parce qu'il
    verrouille la robustesse, pas l'implémentation qui l'assurait.
    """
    session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
    observation = track_path(1, CAR, [(5000.0, 5000.0)])[0]

    outcome = session.feed(0, 0.0, (observation,))

    assert outcome.tracks[0].global_id == 1


def test_la_boite_est_bien_celle_de_l_observation() -> None:
    """Garde-fou du constructeur de tests : `box_at` centre la boîte."""
    observation = track_path(1, CAR, [(900.0, 500.0)])[0]

    assert observation.box == box_at((900.0, 500.0))
