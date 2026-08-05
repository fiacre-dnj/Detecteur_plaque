"""Présence en zone — spécification de prompt/03 §4.

Deux notions cohabitent et ne doivent jamais être confondues :

- **`entries`** est un cumul d'entrées *uniques par identité*, qui ne décroît
  jamais ;
- **`inside`** est une lecture instantanée, réécrite à chaque frame.

Accumuler `inside` donnerait un nombre de « présents » qui ne cesse de croître —
c'est l'erreur que `test_l_occupation_est_une_lecture_et_non_un_cumul` interdit.
"""

from __future__ import annotations

from tests.support.builders import CAR, TRUCK, box_at, make_zone, session_track, track_path
from traffic_analysis.features.counting.domain.models import SessionTrack
from traffic_analysis.features.counting.domain.zone_counter import ZonePresenceCounter

# Zone rectangulaire de (400,200) à (1500,800).
ZONE = make_zone("z1")
DEDANS = (900.0, 500.0)
DEHORS = (100.0, 500.0)


def _move(track: SessionTrack, centre: tuple[float, float]) -> None:
    track.previous_centroid = track.centroid
    track.box = box_at(centre)
    track.centroid = track.box.centroid


def _track_at(
    centre: tuple[float, float], *, hits: int = 5, global_id: int = 1, track_id: int = 1
) -> SessionTrack:
    observation = track_path(track_id, CAR, [centre])[0]
    return session_track(observation, hits=hits, global_id=global_id)


class TestEntreeSimple:
    def test_une_piste_qui_entre_emet_une_entree(self) -> None:
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        track = _track_at(DEHORS)

        assert counter.observe((track,), 0.0, 0) == ()
        _move(track, DEDANS)
        events = counter.observe((track,), 40.0, 1)

        assert len(events) == 1
        assert events[0].zone_id == "z1"
        assert counter.by_zone["z1"].entries == 1

    def test_une_piste_nee_dedans_amorce_l_etat_sans_emettre(self) -> None:
        """Elle n'a pas été *observée* entrer.

        Émettre ici compterait une entrée pour chaque véhicule déjà dans la zone
        au démarrage de l'analyse — donc pour tout le trafic présent à la
        première image.
        """
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        track = _track_at(DEDANS)

        events = counter.observe((track,), 0.0, 0)

        assert events == ()
        assert counter.by_zone["z1"].entries == 0
        # …mais elle est bien comptée comme présente.
        assert counter.by_zone["z1"].inside == 1

    def test_l_evenement_porte_le_temps_de_scene_et_le_libelle_vote(self) -> None:
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        track = _track_at(DEHORS, global_id=42)
        track.identity_label = "truck"
        counter.observe((track,), 0.0, 0)

        _move(track, DEDANS)
        events = counter.observe((track,), 120.0, 3)

        assert events[0].timestamp_ms == 120.0
        assert events[0].frame_index == 3
        assert events[0].global_id == 42
        assert events[0].label == "truck"


class TestDeduplication:
    def test_sortir_puis_revenir_ne_compte_pas_une_seconde_entree(self) -> None:
        """Un véhicule qui manœuvre dans un carrefour ne doit pas gonfler le total."""
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        track = _track_at(DEHORS, global_id=7)

        for centre in (DEHORS, DEDANS, DEHORS, DEDANS):
            _move(track, centre)
            counter.observe((track,), 0.0, 0)

        assert counter.by_zone["z1"].entries == 1

    def test_deux_pistes_de_la_meme_identite_ne_comptent_qu_une_entree(self) -> None:
        """La piste est détruite après une occlusion longue, l'identité survit.

        Le garde porte donc sur `(zone, identité)`, pas sur la piste.
        """
        counter = ZonePresenceCounter((ZONE,), min_hits=2)

        premiere = _track_at(DEHORS, track_id=1, global_id=7)
        counter.observe((premiere,), 0.0, 0)
        _move(premiere, DEDANS)
        counter.observe((premiere,), 40.0, 1)

        seconde = _track_at(DEHORS, track_id=99, global_id=7)
        counter.observe((seconde,), 5000.0, 100)
        _move(seconde, DEDANS)
        events = counter.observe((seconde,), 5040.0, 101)

        assert events == ()
        assert counter.by_zone["z1"].entries == 1

    def test_deux_identites_distinctes_comptent_chacune(self) -> None:
        counter = ZonePresenceCounter((ZONE,), min_hits=2)

        for track_id, global_id in ((1, 10), (2, 20)):
            track = _track_at(DEHORS, track_id=track_id, global_id=global_id)
            counter.observe((track,), 0.0, 0)
            _move(track, DEDANS)
            counter.observe((track,), 40.0, 1)

        assert counter.by_zone["z1"].entries == 2


class TestReportSousMinHits:
    def test_une_piste_non_confirmee_qui_entre_puis_se_confirme_emet_son_entree(self) -> None:
        """Le piège 9 de prompt/13, version zone.

        C'est **l'écriture de l'état** qu'il faut différer, pas l'émission. Si le
        front dehors→dedans est consommé pendant que la piste est encore
        provisoire, l'entrée est perdue silencieusement — et il n'y a aucun moyen
        de s'en apercevoir en lisant les compteurs.
        """
        counter = ZonePresenceCounter((ZONE,), min_hits=3)
        track = _track_at(DEHORS, hits=1)

        counter.observe((track,), 0.0, 0)  # dehors, provisoire → état amorcé à False
        _move(track, DEDANS)
        assert counter.observe((track,), 40.0, 1) == ()  # dedans, encore provisoire

        track.hits = 3  # la piste se confirme, toujours dedans
        events = counter.observe((track,), 80.0, 2)

        assert len(events) == 1
        assert counter.by_zone["z1"].entries == 1

    def test_une_piste_provisoire_qui_disparait_ne_compte_pas(self) -> None:
        counter = ZonePresenceCounter((ZONE,), min_hits=3)
        track = _track_at(DEHORS, hits=1)

        counter.observe((track,), 0.0, 0)
        _move(track, DEDANS)
        counter.observe((track,), 40.0, 1)

        assert counter.by_zone["z1"].entries == 0

    def test_une_piste_provisoire_compte_quand_meme_comme_presente(self) -> None:
        """L'occupation est ce que l'on **voit** à cet instant.

        Exclure les pistes provisoires ferait retarder le chiffre affiché de
        `minHits` frames par rapport à l'image, ce que l'utilisateur lit comme un
        bug d'affichage.
        """
        counter = ZonePresenceCounter((ZONE,), min_hits=5)
        track = _track_at(DEDANS, hits=1)

        counter.observe((track,), 0.0, 0)

        assert counter.by_zone["z1"].inside == 1
        assert counter.by_zone["z1"].entries == 0


class TestOccupation:
    def test_l_occupation_est_une_lecture_et_non_un_cumul(self) -> None:
        """LE test qui empêche le nombre de présents de croître indéfiniment."""
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        track = _track_at(DEDANS)

        for _ in range(5):
            counter.observe((track,), 0.0, 0)

        assert counter.by_zone["z1"].inside == 1

    def test_l_occupation_redescend_quand_la_piste_sort(self) -> None:
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        track = _track_at(DEDANS)
        counter.observe((track,), 0.0, 0)
        assert counter.by_zone["z1"].inside == 1

        _move(track, DEHORS)
        counter.observe((track,), 40.0, 1)

        assert counter.by_zone["z1"].inside == 0
        # …mais le cumul d'entrées ne bouge pas.
        assert counter.by_zone["z1"].entries == 0

    def test_l_occupation_tombe_a_zero_quand_plus_aucune_piste_n_est_rapportee(self) -> None:
        """Une piste qui disparaît du champ doit vider la zone.

        Sans réécriture complète à chaque frame, le dernier chiffre resterait
        affiché pour toujours.
        """
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        track = _track_at(DEDANS)
        counter.observe((track,), 0.0, 0)

        counter.observe((), 40.0, 1)

        assert counter.by_zone["z1"].inside == 0

    def test_plusieurs_pistes_presentes_sont_toutes_comptees(self) -> None:
        counter = ZonePresenceCounter((ZONE,), min_hits=2)
        tracks = [
            _track_at(DEDANS, track_id=1, global_id=1),
            _track_at((1000.0, 600.0), track_id=2, global_id=2),
            _track_at(DEHORS, track_id=3, global_id=3),
        ]

        counter.observe(tracks, 0.0, 0)

        assert counter.by_zone["z1"].inside == 2


class TestPlusieursZonesEtFormes:
    def test_un_polygone_concave_exclut_son_creux(self) -> None:
        """Une voie tracée à la main est presque toujours concave."""
        u_zone = make_zone(
            "u",
            points=(
                (0.0, 0.0),
                (300.0, 0.0),
                (300.0, 700.0),
                (700.0, 700.0),
                (700.0, 0.0),
                (1000.0, 0.0),
                (1000.0, 1000.0),
                (0.0, 1000.0),
            ),
        )
        counter = ZonePresenceCounter((u_zone,), min_hits=2)
        dans_le_creux = _track_at((500.0, 300.0))

        counter.observe((dans_le_creux,), 0.0, 0)

        assert counter.by_zone["u"].inside == 0

    def test_chaque_zone_a_son_compteur_des_le_depart(self) -> None:
        """Une zone sans entrée doit s'afficher à zéro, pas manquer du tableau."""
        counter = ZonePresenceCounter((make_zone("z1"), make_zone("z2")), min_hits=2)

        assert set(counter.by_zone) == {"z1", "z2"}
        assert counter.by_zone["z2"].entries == 0

    def test_une_piste_dans_deux_zones_qui_se_chevauchent_compte_dans_les_deux(self) -> None:
        """Les zones sont indépendantes : elles ne se partagent pas les pistes."""
        z1 = make_zone("z1", points=((0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)))
        z2 = make_zone(
            "z2", points=((500.0, 0.0), (1500.0, 0.0), (1500.0, 1000.0), (500.0, 1000.0))
        )
        counter = ZonePresenceCounter((z1, z2), min_hits=2)
        track = _track_at((100.0, 500.0))
        counter.observe((track,), 0.0, 0)

        _move(track, (700.0, 500.0))  # entre dans z2 tout en restant dans z1
        events = counter.observe((track,), 40.0, 1)

        assert [event.zone_id for event in events] == ["z2"]
        assert counter.by_zone["z1"].inside == 1
        assert counter.by_zone["z2"].inside == 1


class TestRepartitionParClasse:
    def test_les_entrees_sont_ventilees_par_classe_votee(self) -> None:
        counter = ZonePresenceCounter((ZONE,), min_hits=2)

        for track_id, class_id in ((1, CAR), (2, TRUCK), (3, CAR)):
            observation = track_path(track_id, class_id, [DEHORS])[0]
            track = session_track(observation, hits=5, global_id=track_id)
            counter.observe((track,), 0.0, 0)
            _move(track, DEDANS)
            counter.observe((track,), 40.0, 1)

        tally = counter.by_zone["z1"]
        assert tally.by_class == {"car": 2, "truck": 1}
        assert sum(tally.by_class.values()) == tally.entries
