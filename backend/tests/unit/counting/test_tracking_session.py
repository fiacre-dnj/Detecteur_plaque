"""La session de comptage — les sept scénarios normatifs de prompt/03 §7.

Ces tests utilisent des `TrackObservation` fabriquées à la main : **aucun moteur,
aucun modèle, aucun GPU**. C'est la décision d'architecture qui rend tout le reste
testable.

Le test le plus précieux du fichier est
`test_un_vehicule_occulte_trois_secondes_reste_le_meme_vehicule` : il mesure
exactement ce que l'ordre « relâcher avant admettre » achète. Avec le mauvais
ordre, on obtenait 2 véhicules uniques et 0 ré-identification ; avec le bon, 1 et 1.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.support.builders import CAR, TRUCK, box_at, make_line, make_zone, track_path
from traffic_analysis.features.counting.domain.models import BoundingBox, PlateDetection
from traffic_analysis.features.counting.domain.reid import ReidOptions
from traffic_analysis.features.counting.domain.tracking_session import (
    AnalysisSession,
    SessionConfig,
)

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FPS = 25.0
FRAME_MS = 1000.0 / FPS


def _scene(*, texture: int = 0) -> np.ndarray:
    """Image de scène. Un motif la rend descriptible par la ré-identification.

    `np.zeros` suffit à tous les tests de comptage — le domaine ne dépend d'aucun
    pixel — mais la ré-identification a besoin d'apparence pour fonctionner.
    """
    image = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    if texture:
        image[:, :] = (texture, 60, 200 - texture)
        image[::5, :] = (255, 255, 255)
    return image


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
        image = _scene(texture=40)

        for index, observation in enumerate(observations):
            session.feed(index, index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.unique_vehicles == 1
        assert stats.crossings == 1
        assert stats.by_line["l1"].total == 1

    def test_le_badge_compte_est_pose_sur_la_piste(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        path = [(900.0, 300.0 + step * 50.0) for step in range(10)]
        observations = track_path(1, CAR, path)
        image = _scene(texture=40)

        outcome = None
        for index, observation in enumerate(observations):
            outcome = session.feed(index, index * FRAME_MS, image, (observation,))

        assert outcome is not None
        assert outcome.tracks[0].counted is True

    def test_le_registre_decrit_le_vehicule(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        path = [(900.0, 300.0 + step * 50.0) for step in range(10)]
        image = _scene(texture=40)

        for index, observation in enumerate(track_path(1, CAR, path)):
            session.feed(index, index * FRAME_MS, image, (observation,))

        vehicles = session.vehicles()
        assert len(vehicles) == 1
        record = vehicles[0]
        assert record.label == "car"
        assert record.first_seen_ms == 0.0
        assert record.last_seen_ms == pytest.approx(9 * FRAME_MS)
        assert len(record.crossed_lines) == 1
        assert record.crossed_lines[0].line_id == "l1"
        # Sans échelle px/m fournie, la vitesse reste en px/s.
        assert record.avg_speed_px_s is not None
        assert record.avg_speed_kmh is None

    def test_avec_une_echelle_la_vitesse_est_convertie(self) -> None:
        session = AnalysisSession(_config(pixels_per_meter=10.0), FRAME_WIDTH, FRAME_HEIGHT)
        path = [(900.0, 300.0 + step * 50.0) for step in range(10)]
        image = _scene(texture=40)

        for index, observation in enumerate(track_path(1, CAR, path)):
            session.feed(index, index * FRAME_MS, image, (observation,))

        assert session.vehicles()[0].avg_speed_kmh is not None


class TestReidentification:
    def test_un_vehicule_occulte_trois_secondes_reste_le_meme_vehicule(self) -> None:
        """LE test de l'ordre « relâcher avant admettre ».

        Le véhicule traverse, disparaît trois secondes (plus que `max_lost_ms`), et
        revient avec un **nouvel id de piste** — c'est exactement ce que fait
        BoT-SORT après une occlusion longue.

        **Le détail qui fait tout : aucune frame vide entre les deux.** La mort de
        l'ancienne piste et la naissance de sa remplaçante doivent avoir lieu dans
        le *même* appel à `feed`, parce que c'est ce que fait le moteur — et c'est
        la seule situation où le mauvais ordre se voit. Avec une frame vide
        intermédiaire, le release et l'admission tombent dans deux appels
        différents et les deux ordres donnent le même résultat : le test passerait
        en étant inutile.

        Attendu : 1 véhicule unique, au moins 1 ré-identification, et **1 seul**
        franchissement puisqu'il ne recroise pas la ligne. Avec le mauvais ordre :
        2 uniques et 0 ré-identification.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        # Traversée : de y=300 à y=750, la ligne est à y=500.
        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, image, (observation,))

        premiere_passe = session.stats()
        assert premiere_passe.crossings == 1

        # Trois secondes plus tard, sans aucune frame entre-temps : la piste 1 est
        # morte et la piste 7 la remplace dans le même appel.
        for step in range(10):
            observation = track_path(7, CAR, [(910.0, 760.0 + step * 5.0)])[0]
            session.feed(100 + step, 4000.0 + step * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.unique_vehicles == 1, "le retour a été admis comme un véhicule neuf"
        assert stats.reid_hits >= 1
        assert stats.crossings == 1, "le retour a recompté un franchissement"

    def test_un_vehicule_reidentifie_qui_recroise_compte_une_seconde_fois(self) -> None:
        """Le pendant du test précédent, et la règle d'[ADR 0009] de bout en bout.

        Même scénario — traversée, trois secondes d'absence, retour reconnu — mais
        cette fois le véhicule **recroise** la ligne en remontant. La
        ré-identification a ré-armé son comptage : c'est un second passage, et il
        doit compter. Toujours **un seul** véhicule unique : on compte des
        passages, pas des immatriculations.

        Sans ré-armement on mesurerait 1 franchissement, et un véhicule faisant la
        navette sur une route resterait invisible après son premier passage.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        # Descente : de y=300 à y=750, la ligne est à y=500.
        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, image, (observation,))
        assert session.stats().crossings == 1

        # Trois secondes plus tard, un nouvel id de piste remonte depuis le bas et
        # repasse la ligne. Aucune frame vide : la mort et la naissance ont lieu
        # dans le même appel, comme le fait le moteur.
        for step in range(10):
            observation = track_path(7, CAR, [(910.0, 760.0 - step * 50.0)])[0]
            session.feed(100 + step, 4000.0 + step * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.unique_vehicles == 1, "le retour a été admis comme un véhicule neuf"
        assert stats.reid_hits >= 1
        assert stats.crossings == 2, "la ré-identification n'a pas ré-armé le comptage"
        assert stats.by_line["l1"].negative == 1, "le retour remonte, il compte en négatif"

    def test_un_id_de_piste_ressuscite_recupere_son_identite(self) -> None:
        """Récupération **par id**, sans passer par l'apparence.

        BoT-SORT réutilise ses identifiants. Quand le même id revient peu après
        avoir été perdu, c'est le même véhicule, et c'est une information plus
        fiable qu'un appariement d'apparence : un véhicule à contre-jour ou trop
        petit peut ne produire aucune signature exploitable et deviendrait sinon un
        véhicule de plus.

        Le scénario force ce chemin en rendant l'apparence inutilisable : la boîte
        fait moins de 20 px de côté, donc `build_signature` refuse. Seule la
        récupération par id peut alors sauver l'identité.

        La frame vide intermédiaire est nécessaire : `_advance_tracks` s'exécute
        avant `_release_lost`, donc sans elle la piste serait simplement mise à
        jour et ne mourrait jamais.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)
        petite = (16.0, 16.0)

        for index in range(4):
            observation = track_path(1, CAR, [(900.0, 300.0 + index * 10.0)], box_size=petite)[0]
            session.feed(index, index * FRAME_MS, image, (observation,))
        assert session.stats().unique_vehicles == 1

        session.feed(50, 3000.0, image, ())  # la piste 1 meurt ici

        # Le MÊME id de piste réapparaît, dans la fenêtre d'appariement.
        for index in range(4):
            observation = track_path(1, CAR, [(920.0, 340.0 + index * 10.0)], box_size=petite)[0]
            session.feed(100 + index, 4000.0 + index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.unique_vehicles == 1, "l'id ressuscité a été admis comme un véhicule neuf"
        assert stats.reid_hits == 1

    def test_un_id_reutilise_bien_plus_tard_ne_recupere_rien(self) -> None:
        """Au-delà de la fenêtre d'appariement, un id réutilisé est un autre véhicule.

        Le conserver indéfiniment ferait fusionner deux véhicules distincts, ce qui
        est l'erreur la plus difficile à remarquer : le total baisse sans que rien à
        l'écran ne l'explique.
        """
        session = AnalysisSession(_config(max_lost_ms=2500.0), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)
        petite = (16.0, 16.0)

        for index in range(4):
            observation = track_path(1, CAR, [(900.0, 300.0)], box_size=petite)[0]
            session.feed(index, index * FRAME_MS, image, (observation,))
        session.feed(50, 3000.0, image, ())  # la piste 1 meurt ici

        # Bien au-delà de `reid.max_gap_ms` (30 s), et ailleurs dans l'image.
        for index in range(4):
            observation = track_path(1, CAR, [(300.0, 700.0)], box_size=petite)[0]
            session.feed(500 + index, 90_000.0 + index * FRAME_MS, image, (observation,))

        assert session.stats().unique_vehicles == 2

    def test_deux_vehicules_identiques_simultanes_restent_deux(self) -> None:
        """L'exclusivité : une identité portée par une piste vivante est inéligible.

        Sans elle, la seconde voiture hériterait de l'identité de la première et ne
        serait jamais comptée.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        for index in range(10):
            y = 300.0 + index * 50.0
            observations = (
                track_path(1, CAR, [(700.0, y)])[0],
                track_path(2, CAR, [(1100.0, y)])[0],
            )
            session.feed(index, index * FRAME_MS, image, observations)

        stats = session.stats()
        assert stats.unique_vehicles == 2
        assert stats.crossings == 2


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
        image = _scene(texture=40)

        # x = 100 : hors de la zone, qui commence à x = 400.
        for index, observation in enumerate(
            track_path(1, CAR, [(100.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.unique_vehicles == 0
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
        image = _scene(texture=40)

        for index, observation in enumerate(
            track_path(1, CAR, [(100.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, image, (observation,))

        assert session.stats().unique_vehicles == 1


class TestVoteDeClasse:
    def test_une_lecture_qui_alterne_ne_fait_pas_osciller_le_compteur(self) -> None:
        """`identity_label` reste stable, et `unique_by_class` somme aux uniques."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)
        lectures = [TRUCK, TRUCK, CAR, TRUCK, CAR, TRUCK, TRUCK, CAR, TRUCK, TRUCK]

        for index, class_id in enumerate(lectures):
            observation = track_path(1, class_id, [(900.0, 300.0 + index * 50.0)])[0]
            session.feed(index, index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.unique_by_class == {"truck": 1}
        assert sum(stats.unique_by_class.values()) == stats.unique_vehicles
        # Le franchissement est comptabilisé sous la classe votée.
        assert stats.by_line["l1"].by_class == {"truck": 1}


class TestStatistiques:
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
        image = _scene(texture=40)

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 60.0) for step in range(12)])
        ):
            session.feed(index, index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.crossings == sum(tally.total for tally in stats.by_line.values())
        assert sum(stats.by_class.values()) == stats.crossings
        # Le véhicule traverse les deux lignes, mais ne compte qu'une fois (ADR
        # 0009) : c'est la première ligne franchie qui porte le total.
        assert stats.crossings == 1
        assert stats.by_line["haute"].total == 1
        assert stats.by_line["basse"].total == 0

    def test_le_debit_est_nul_sous_trois_secondes_de_flux(self) -> None:
        """En dessous de 3 s, l'extrapolation oscille trop pour être publiable.

        Un chiffre qui saute de 12 à 240 véhicules par minute décrédibilise tout
        le reste de l'écran.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(10)])
        ):
            session.feed(index, index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.analysed_scene_ms < 3000.0
        assert stats.vehicles_per_minute == 0.0

    def test_au_dela_de_trois_secondes_le_debit_est_publie(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        for index in range(120):  # 120 frames à 25 fps = 4,8 s
            y = 300.0 + (index % 10) * 50.0
            observation = track_path(1, CAR, [(900.0, y)])[0]
            session.feed(index, index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.analysed_scene_ms >= 3000.0
        assert stats.vehicles_per_minute > 0.0

    def test_le_temps_ecoule_est_le_temps_de_scene_analyse(self) -> None:
        """Côté serveur il n'y a pas d'attente d'utilisateur à mesurer.

        Le champ reste dans le contrat parce que l'interface affiche les deux, mais
        il ne doit pas être renseigné avec une horloge murale.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)
        for index, observation in enumerate(track_path(1, CAR, [(900.0, 300.0)] * 5)):
            session.feed(index, index * FRAME_MS, image, (observation,))

        stats = session.stats()
        assert stats.elapsed_ms == stats.analysed_scene_ms
        assert stats.elapsed_ms == pytest.approx(4 * FRAME_MS)

    def test_le_diagnostic_distingue_confirme_et_provisoire(self) -> None:
        """« Le compte est faux » n'est diagnosticable que si l'on voit pourquoi."""
        session = AnalysisSession(_config(min_hits=5), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        session.feed(0, 0.0, image, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        stats = session.stats()

        assert stats.diagnostics.confirmed_tracks == 0
        assert stats.diagnostics.tentative_tracks == 1


class TestTimelineEtAliasing:
    def test_deux_frames_consecutives_ont_des_snapshots_differents(self) -> None:
        """Non-régression du piège d'aliasing de la timeline.

        Sans `snapshot()`, la timeline stockerait la référence vivante et **toutes
        ses lignes convergeraient vers l'état final** : à la relecture, chaque
        frame afficherait la position de sortie des véhicules.
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)
        timeline = []

        for index, observation in enumerate(
            track_path(1, CAR, [(900.0, 300.0 + step * 50.0) for step in range(5)])
        ):
            outcome = session.feed(index, index * FRAME_MS, image, (observation,))
            timeline.append(tuple(track.snapshot() for track in outcome.tracks))

        premiere = timeline[0][0].centroid
        derniere = timeline[-1][0].centroid
        assert premiere != derniere
        assert premiere.y == pytest.approx(300.0)
        assert derniere.y == pytest.approx(500.0)


class TestPlaques:
    def test_la_meilleure_plaque_par_identite_est_conservee(self) -> None:
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        outcome = session.feed(0, 0.0, image, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        track = outcome.tracks[0]
        session.record_plates(track, (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.42),))

        outcome = session.feed(1, FRAME_MS, image, (track_path(1, CAR, [(900.0, 350.0)])[0],))
        track = outcome.tracks[0]
        session.record_plates(track, (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.71),))

        outcome = session.feed(2, 2 * FRAME_MS, image, (track_path(1, CAR, [(900.0, 400.0)])[0],))
        track = outcome.tracks[0]
        session.record_plates(track, (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.33),))

        assert session.vehicles()[0].best_plate_score == pytest.approx(0.71)

    def test_les_plaques_ne_survivent_pas_a_la_frame_suivante(self) -> None:
        """Garder les plaques d'une frame à l'autre ferait afficher une plaque là
        où le modèle n'en voit plus."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        outcome = session.feed(0, 0.0, image, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        session.record_plates(
            outcome.tracks[0], (PlateDetection(BoundingBox(1.0, 1.0, 20.0, 8.0), 0.9),)
        )

        outcome = session.feed(1, FRAME_MS, image, (track_path(1, CAR, [(900.0, 350.0)])[0],))

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
        image = _scene(texture=40)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                image,
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
        image = _scene(texture=40)

        first = session.feed(0, 0.0, image, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        session.record_plates(first.tracks[0], (_plate("AB123CD", 0.95),))
        assert first.tracks[0].plate_text == ""

        second = session.feed(1, FRAME_MS, image, (track_path(1, CAR, [(900.0, 350.0)])[0],))
        session.record_plates(second.tracks[0], (_plate("AB123CD", 0.95),))
        assert second.tracks[0].plate_text == ""

        third = session.feed(2, 2 * FRAME_MS, image, (track_path(1, CAR, [(900.0, 400.0)])[0],))
        assert third.tracks[0].plate_text == "AB123CD"
        assert third.tracks[0].plate_text_score == pytest.approx(0.95)

    def test_le_snapshot_emporte_le_texte_vote(self) -> None:
        """Sans cela, la relecture afficherait des boîtes muettes."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                image,
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
        image = _scene(texture=40)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                image,
                (track_path(1, CAR, [(900.0, 300.0 + index * 50.0)])[0],),
            )
            session.record_plates(outcome.tracks[0], (_plate("AB123CD", 0.95),))
        assert outcome.tracks[0].plate_text == "AB123CD"

        # Silence assez long pour que `_release_lost` détruise la piste, mais dans la
        # fenêtre d'appariement de la galerie : c'est bien une reprise, pas un
        # nouveau véhicule.
        revival_ms = 3 * FRAME_MS + 1500.0
        revived = session.feed(80, revival_ms, image, (track_path(1, CAR, [(900.0, 460.0)])[0],))

        assert revived.tracks[0].global_id == outcome.tracks[0].global_id
        assert revived.tracks[0].plate_text == "AB123CD"

    def test_le_registre_porte_le_vote_et_non_la_derniere_lecture(self) -> None:
        """Trois `AB123CD` puis un `XY999ZZ` : le registre affiche `AB123CD`."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)
        readings = ("AB123CD", "AB123CD", "AB123CD", "XY999ZZ")

        for index, text in enumerate(readings):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                image,
                (track_path(1, CAR, [(900.0, 300.0 + index * 40.0)])[0],),
            )
            session.record_plates(outcome.tracks[0], (_plate(text, 0.95),))

        assert session.vehicles()[0].plate_text == "AB123CD"

    def test_une_lecture_unique_ne_pose_aucun_texte(self) -> None:
        """L'invariant 4 de bout en bout : une lecture n'est pas un vote."""
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        outcome = session.feed(0, 0.0, image, (track_path(1, CAR, [(900.0, 300.0)])[0],))
        session.record_plates(outcome.tracks[0], (_plate("AB123CD", 0.99),))

        outcome = session.feed(1, FRAME_MS, image, (track_path(1, CAR, [(900.0, 350.0)])[0],))

        assert outcome.tracks[0].plate_text == ""
        assert session.vehicles()[0].plate_text is None

    def test_une_plaque_sans_texte_laisse_le_registre_muet(self) -> None:
        """« Vue mais illisible » : un score de détection, aucun texte.

        C'est l'état que l'interface rate le plus facilement, et il doit être
        distinguable de « aucune plaque ».
        """
        session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        for index in range(3):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                image,
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
        image = _scene(texture=40)

        for index in range(4):
            outcome = session.feed(
                index,
                index * FRAME_MS,
                image,
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


class TestZones:
    def test_les_entrees_de_zone_sont_emises_et_le_registre_les_note(self) -> None:
        zone = make_zone(
            "z1", points=((400.0, 200.0), (1500.0, 200.0), (1500.0, 800.0), (400.0, 800.0))
        )
        session = AnalysisSession(_config(zones=(zone,)), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        # Démarre hors zone (x=100), puis entre.
        session.feed(0, 0.0, image, (track_path(1, CAR, [(100.0, 300.0)])[0],))
        session.feed(1, FRAME_MS, image, (track_path(1, CAR, [(120.0, 300.0)])[0],))
        outcome = session.feed(2, 2 * FRAME_MS, image, (track_path(1, CAR, [(900.0, 300.0)])[0],))

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

    def test_les_options_de_reidentification_ont_leurs_defauts(self) -> None:
        assert SessionConfig().reid == ReidOptions()

    def test_une_session_sans_geometrie_ne_compte_rien_mais_ne_leve_pas(self) -> None:
        """L'API refuse ce cas en 422 ; le domaine, lui, doit rester robuste."""
        session = AnalysisSession(SessionConfig(), FRAME_WIDTH, FRAME_HEIGHT)
        image = _scene(texture=40)

        outcome = session.feed(0, 0.0, image, (track_path(1, CAR, [(900.0, 300.0)])[0],))

        assert outcome.crossings == ()
        assert session.stats().crossings == 0


def test_une_boite_hors_image_ne_fait_pas_lever_la_session() -> None:
    """Le suivi extrapole parfois une boîte au-delà du bord de l'image.

    La signature est alors refusée (`None`) et la piste reçoit une identité neuve —
    ce qui est le comportement voulu, sans exception.
    """
    session = AnalysisSession(_config(), FRAME_WIDTH, FRAME_HEIGHT)
    observation = track_path(1, CAR, [(5000.0, 5000.0)])[0]

    outcome = session.feed(0, 0.0, _scene(texture=40), (observation,))

    assert outcome.tracks[0].global_id == 1


def test_la_boite_est_bien_celle_de_l_observation() -> None:
    """Garde-fou du constructeur de tests : `box_at` centre la boîte."""
    observation = track_path(1, CAR, [(900.0, 500.0)])[0]

    assert observation.box == box_at((900.0, 500.0))
