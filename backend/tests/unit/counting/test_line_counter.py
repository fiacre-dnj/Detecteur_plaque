"""Comptage de franchissements — les dix scénarios normatifs de prompt/03 §3.

Chaque test correspond à un bug réellement survenu, et le nom du test dit lequel.
Les quatre plus coûteux à repayer :

- `test_un_va_et_vient_compte_une_fois_dans_chaque_sens` et
  `test_un_tremblement_sur_la_ligne_ne_compte_qu_une_fois` s'opposent : c'est
  pour les concilier que le garde porte sur `(ligne, identité, sens)` et non sur
  `(ligne, identité)` ;
- `test_deux_pistes_successives_de_la_meme_identite_ne_comptent_qu_une_fois` :
  sans garde d'identité, un véhicule occulté puis revenu compte 2 ;
- `test_un_franchissement_hors_zone_met_quand_meme_le_cote_a_jour` : sans cela la
  piste « regarde dans le mauvais sens » et le franchissement suivant compte à
  l'envers.
"""

from __future__ import annotations

from tests.support.builders import (
    CAR,
    TRUCK,
    box_at,
    make_line,
    make_zone,
    session_track,
    straight_line,
    track_path,
)
from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.line_counter import LineCrossingCounter
from traffic_analysis.features.counting.domain.models import SessionTrack

# Ligne horizontale à y = 500. Descendre (y croissant) traverse dans le sens +1.
LINE = make_line("l1")
DESCENDING = +1
ASCENDING = -1


def _advance(track: SessionTrack, centre: tuple[float, float]) -> None:
    """Fait avancer une piste comme la session le ferait.

    `previous_centroid` conserve la position d'avant : c'est ce segment que le
    compteur teste contre la ligne.
    """
    track.previous_centroid = track.centroid
    track.box = box_at(centre)
    track.centroid = track.box.centroid


def _run(
    counter: LineCrossingCounter,
    track: SessionTrack,
    path: list[tuple[float, float]],
    *,
    start_ms: float = 0.0,
    step_ms: float = 40.0,
) -> list[object]:
    """Rejoue une trajectoire frame par frame et rend tous les événements émis."""
    events: list[object] = []
    for index, centre in enumerate(path):
        if index > 0:
            _advance(track, centre)
        timestamp = start_ms + index * step_ms
        track.last_seen_ms = timestamp
        events.extend(counter.observe((track,), timestamp, index))
    return events


class TestFranchissementSimple:
    def test_une_piste_confirmee_qui_traverse_compte_une_fois(self) -> None:
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=10)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert len(events) == 1
        assert counter.by_line["l1"].total == 1
        assert counter.by_line["l1"].positive == 1
        assert counter.by_line["l1"].negative == 0
        assert counter.by_line["l1"].by_class == {"car": 1}

    def test_le_sens_est_le_signe_du_cote_d_arrivee(self) -> None:
        """La convention exposée à l'API et dessinée par l'interface."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        montant = straight_line((900.0, 700.0), (900.0, 300.0), steps=10)
        track = session_track(track_path(1, CAR, montant)[0], hits=5)

        events = _run(counter, track, montant)

        assert len(events) == 1
        assert events[0].direction == ASCENDING  # type: ignore[attr-defined]
        assert counter.by_line["l1"].negative == 1

    def test_l_evenement_porte_l_instant_et_la_frame_du_franchissement(self) -> None:
        """Le temps est du temps de scène, pas l'heure de l'horloge."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=5)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path, step_ms=40.0)

        event = events[0]
        assert event.frame_index == 3  # type: ignore[attr-defined]
        assert event.timestamp_ms == 120.0  # type: ignore[attr-defined]
        assert event.line_id == "l1"  # type: ignore[attr-defined]


class TestFranchissementsRefuses:
    def test_une_piste_qui_passe_au_dela_des_extremites_ne_compte_pas(self) -> None:
        """Le bug que le test d'intersection de segments empêche.

        La ligne va de x=0 à x=1920 ; ce trajet est à x=3000. Il change bien de
        côté de la droite infinie, mais ne coupe jamais le segment tracé.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((3000.0, 300.0), (3000.0, 700.0), steps=10)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert events == []
        assert counter.by_line["l1"].total == 0

    def test_une_piste_apparue_deja_de_l_autre_cote_ne_compte_pas(self) -> None:
        """Elle n'a pas été *observée* franchir.

        Compter ici ajouterait un véhicule à chaque piste née sous la ligne — donc
        à chaque voiture déjà passée quand l'analyse commence.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 700.0), (900.0, 900.0), steps=10)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert events == []

    def test_une_piste_pile_sur_la_ligne_attend_la_frame_suivante(self) -> None:
        """`side_of_line` rend 0 : on n'amorce pas l'état sur cette frame.

        Trancher arbitrairement produirait un faux franchissement à la frame
        suivante, dans un sens choisi au hasard.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = [(900.0, 500.0), (900.0, 500.0), (900.0, 700.0)]
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        # Le premier côté réellement lu est +1 (sous la ligne) : c'est un
        # amorçage, pas un franchissement.
        assert events == []


class TestDeduplication:
    def test_un_va_et_vient_compte_une_fois_dans_chaque_sens(self) -> None:
        """Un aller-retour réel est deux passages, et doit compter deux fois.

        C'est ce scénario qui interdit un garde par `(ligne, identité)` : il n'en
        compterait qu'un.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        aller = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        retour = straight_line((900.0, 700.0), (900.0, 300.0), steps=6)
        track = session_track(track_path(1, CAR, aller)[0], hits=5)

        events = _run(counter, track, [*aller, *retour])

        assert len(events) == 2
        assert {event.direction for event in events} == {DESCENDING, ASCENDING}  # type: ignore[attr-defined]
        tally = counter.by_line["l1"]
        assert tally.total == 2
        assert tally.positive == 1
        assert tally.negative == 1

    def test_un_tremblement_sur_la_ligne_ne_compte_qu_une_fois(self) -> None:
        """Une boîte qui vacille autour de la ligne dans le même sens.

        C'est le pendant du test précédent : le même sens ne compte qu'une fois,
        même si le côté change plusieurs fois.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = [
            (900.0, 480.0),
            (900.0, 520.0),  # franchit +1
            (900.0, 495.0),  # revient
            (900.0, 515.0),  # re-franchit +1 → déjà compté
            (900.0, 700.0),
        ]
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        descendants = [e for e in events if e.direction == DESCENDING]  # type: ignore[attr-defined]
        assert len(descendants) == 1

    def test_deux_pistes_successives_de_la_meme_identite_ne_comptent_qu_une_fois(self) -> None:
        """Le garde d'identité, et la raison de son existence.

        Quand le suivi perd un véhicule plus longtemps que `max_lost_ms`, la piste
        est **détruite** et sa remplaçante démarre avec un état vierge. Un garde
        porté par la piste laisserait donc recompter. Reproduit avant correction :
        un véhicule qui franchit, disparaît 15 frames et revient avec une boîte
        qui tremble sur la ligne comptait **2**.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        premier_passage = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        second_passage = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)

        # Piste 1 : franchit et compte.
        track_a = session_track(track_path(1, CAR, premier_passage)[0], hits=5, global_id=42)
        events_a = _run(counter, track_a, premier_passage)

        # Piste 7 : nouvelle piste, MÊME identité (la galerie l'a reconnue).
        track_b = session_track(track_path(7, CAR, second_passage)[0], hits=5, global_id=42)
        events_b = _run(counter, track_b, second_passage, start_ms=1000.0)

        assert len(events_a) == 1
        assert events_b == []
        assert counter.by_line["l1"].total == 1

    def test_deux_identites_differentes_comptent_chacune(self) -> None:
        """Garde-fou du test précédent : ne pas dédupliquer ce qui est distinct."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)

        for track_id, global_id in ((1, 10), (2, 20)):
            track = session_track(track_path(track_id, CAR, path)[0], hits=5, global_id=global_id)
            _run(counter, track, path)

        assert counter.by_line["l1"].total == 2

    def test_les_identites_comptees_alimentent_le_badge(self) -> None:
        """`counted_identities()` est la source du ✓ de l'interface.

        Le badge dérive du tally et non de la comptabilité d'une piste : un
        franchissement supprimé par le garde ne doit pas peindre ✓, sinon
        l'overlay affirme qu'un véhicule est compté alors que le total n'a pas
        bougé.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5, global_id=42)

        assert counter.counted_identities() == set()
        _run(counter, track, path)
        assert counter.counted_identities() == {42}


class TestReportSousMinHits:
    def test_un_franchissement_pendant_la_montee_en_confiance_est_differe(self) -> None:
        """Il est **différé**, pas jeté.

        Le jeter perd tout véhicule qui franchit dans ses premières frames — cas
        fréquent d'une ligne tracée près du bord de l'image. Le compter tout de
        suite ferait d'une seule boîte parasite un véhicule.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=3)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=8)
        track = session_track(track_path(1, CAR, path)[0], hits=1)

        events: list[object] = []
        for index, centre in enumerate(path):
            if index > 0:
                _advance(track, centre)
            # La piste ne se confirme qu'à la toute fin du trajet.
            track.hits = 1 if index < len(path) - 1 else 3
            events.extend(counter.observe((track,), index * 40.0, index))

        assert len(events) == 1
        # L'événement est émis à la confirmation, pas à l'instant du franchissement.
        assert events[0].frame_index == len(path) - 1  # type: ignore[attr-defined]

    def test_une_piste_qui_meurt_avant_confirmation_ne_compte_pas(self) -> None:
        """Une boîte parasite qui traverse et disparaît n'est pas un véhicule."""
        counter = LineCrossingCounter((LINE,), (), min_hits=3)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=8)
        track = session_track(track_path(1, CAR, path)[0], hits=1)

        events: list[object] = []
        for index, centre in enumerate(path):
            if index > 0:
                _advance(track, centre)
            track.hits = 1  # jamais confirmée
            events.extend(counter.observe((track,), index * 40.0, index))

        assert events == []
        assert counter.by_line["l1"].total == 0


class TestLigneLieeAUneZone:
    ZONE = make_zone(
        "z1", points=((400.0, 200.0), (1500.0, 200.0), (1500.0, 800.0), (400.0, 800.0))
    )
    LIGNE_EN_ZONE = make_line("l1", zone_id="z1")

    def test_un_franchissement_dans_la_zone_compte(self) -> None:
        counter = LineCrossingCounter((self.LIGNE_EN_ZONE,), (self.ZONE,), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert len(events) == 1

    def test_un_franchissement_hors_zone_ne_compte_pas(self) -> None:
        """La zone restreint la portée de la ligne — c'est ce qui permet de
        compter une seule voie d'un carrefour."""
        counter = LineCrossingCounter((self.LIGNE_EN_ZONE,), (self.ZONE,), min_hits=2)
        # x = 200 : hors de la zone, qui commence à x = 400.
        path = straight_line((200.0, 300.0), (200.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert events == []

    def test_un_franchissement_hors_zone_met_quand_meme_le_cote_a_jour(self) -> None:
        """Le piège 11 de prompt/13, et il est vicieux.

        Le côté doit être écrit **même quand le franchissement est rejeté**. Sans
        cela la piste « regarde dans le mauvais sens », et son franchissement
        suivant — légitime, dans la zone — compte à l'envers.
        """
        counter = LineCrossingCounter((self.LIGNE_EN_ZONE,), (self.ZONE,), min_hits=2)
        # D'abord un franchissement descendant hors zone (rejeté)…
        hors_zone = straight_line((200.0, 300.0), (200.0, 700.0), steps=6)
        # …puis un franchissement montant dans la zone (légitime).
        dans_zone = straight_line((900.0, 700.0), (900.0, 300.0), steps=6)
        track = session_track(track_path(1, CAR, hors_zone)[0], hits=5)

        rejetes = _run(counter, track, hors_zone)
        # La piste se téléporte dans la zone : c'est irréaliste mais c'est
        # exactement l'enchaînement de côtés qui révèle le bug.
        track.previous_centroid = track.centroid
        track.box = box_at(dans_zone[0])
        track.centroid = track.box.centroid
        acceptes = _run(counter, track, dans_zone, start_ms=1000.0)

        assert rejetes == []
        assert len(acceptes) == 1
        # Le sens doit être MONTANT. Si l'état de côté n'avait pas été mis à jour
        # hors zone, la piste croirait venir d'au-dessus et compterait +1.
        assert acceptes[0].direction == ASCENDING  # type: ignore[attr-defined]

    def test_une_ligne_dont_la_zone_n_existe_pas_compte_partout(self) -> None:
        """Repli sûr : mieux vaut compter que se taire en silence.

        Le cas est déjà refusé à la validation de l'API ; si une configuration
        ancienne y échappe, sous-compter serait l'erreur la plus difficile à
        remarquer.
        """
        counter = LineCrossingCounter((make_line("l1", zone_id="zone-fantome"),), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        assert len(_run(counter, track, path)) == 1


class TestInvariantsComptables:
    def test_le_total_est_toujours_la_somme_des_deux_sens(self) -> None:
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        aller = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        retour = straight_line((900.0, 700.0), (900.0, 300.0), steps=6)
        track = session_track(track_path(1, TRUCK, aller)[0], hits=5)

        _run(counter, track, [*aller, *retour])

        tally = counter.by_line["l1"]
        assert tally.total == tally.positive + tally.negative

    def test_la_somme_par_classe_egale_le_total(self) -> None:
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)

        for index, class_id in enumerate((CAR, TRUCK, CAR)):
            track = session_track(track_path(index, class_id, path)[0], hits=5, global_id=index + 1)
            _run(counter, track, path)

        tally = counter.by_line["l1"]
        assert sum(tally.by_class.values()) == tally.total
        assert tally.by_class == {"car": 2, "truck": 1}

    def test_le_libelle_du_vote_gagne_sur_la_lecture_de_la_frame(self) -> None:
        """Un véhicule est compté sous `identity_label` quand il existe."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5, identity_label="truck")

        _run(counter, track, path)

        assert counter.by_line["l1"].by_class == {"truck": 1}

    def test_chaque_ligne_a_son_compteur_des_le_depart(self) -> None:
        """Une ligne sans franchissement doit apparaître à zéro, pas manquer.

        L'interface affiche une ligne par ligne de comptage : une clé absente
        produirait un trou dans le tableau au lieu d'un honnête « 0 ».
        """
        counter = LineCrossingCounter((make_line("l1"), make_line("l2")), (), min_hits=2)

        assert set(counter.by_line) == {"l1", "l2"}
        assert counter.by_line["l2"].total == 0


class TestPlusieursLignes:
    def test_une_piste_qui_traverse_deux_lignes_compte_dans_les_deux(self) -> None:
        counter = LineCrossingCounter(
            (
                make_line("haute", a=(0.0, 400.0), b=(1920.0, 400.0)),
                make_line("basse", a=(0.0, 600.0), b=(1920.0, 600.0)),
            ),
            (),
            min_hits=2,
        )
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=12)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert len(events) == 2
        assert counter.by_line["haute"].total == 1
        assert counter.by_line["basse"].total == 1

    def test_la_premiere_frame_sans_centroide_precedent_ne_leve_pas(self) -> None:
        """`previous_centroid` est `None` à la naissance d'une piste.

        Le compteur passe alors deux fois le centroïde courant : le segment est de
        longueur nulle et ne croise rien.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        track = SessionTrack(
            track_id=1,
            class_id=CAR,
            label="car",
            score=0.9,
            box=box_at((900.0, 500.0)),
            centroid=Point(900.0, 500.0),
            previous_centroid=None,
            hits=5,
            global_id=1,
        )

        assert counter.observe((track,), 0.0, 0) == ()
