"""Comptage de franchissements — les scénarios normatifs de prompt/03 §3.

**Un seul mode : chaque franchissement observé compte.** Le compteur a compté des
*véhicules* (ADR 0009), puis des *passages* avec un garde débranché mais conservé
(ADR 0014). ADR 0016 supprime le garde : `dedupe_by_identity` n'existe plus, et la
clé `(identité, génération)` a disparu avec `reid_count`.

Ce que cela signifie, écrit noir sur blanc pour que personne ne le découvre en
comparant deux tableaux : un aller-retour compte 2, deux lignes en travers d'une
même voie comptent 2, et une occlusion qui coupe une piste compte 2.

Deux tests valent d'être lus en premier, parce qu'ils tiennent chacun un bug
réellement survenu :

- `test_un_franchissement_hors_zone_met_quand_meme_le_cote_a_jour` : sans cela la
  piste « regarde dans le mauvais sens » et le franchissement suivant compte à
  l'envers (piège 11 de prompt/13) ;
- `test_le_badge_reste_alimente_sans_deduplication` : le ✓ de l'overlay et
  `crossed_unique` partagent le même ensemble, et en supprimant le refus il aurait
  été facile de cesser de le remplir.
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
from traffic_analysis.features.counting.domain.models import (
    CrossingEvent,
    SessionTrack,
)

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
        assert counter.by_line["l1"].positive.total == 1
        assert counter.by_line["l1"].negative.total == 0
        assert counter.by_line["l1"].by_class == {"car": 1}

    def test_le_sens_est_le_signe_du_cote_d_arrivee(self) -> None:
        """La convention exposée à l'API et dessinée par l'interface."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        montant = straight_line((900.0, 700.0), (900.0, 300.0), steps=10)
        track = session_track(track_path(1, CAR, montant)[0], hits=5)

        events = _run(counter, track, montant)

        assert len(events) == 1
        assert events[0].direction == ASCENDING  # type: ignore[attr-defined]
        assert counter.by_line["l1"].negative.total == 1

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


class TestComptageDesPassages:
    """Chaque franchissement observé compte (ADR 0014, puis ADR 0016).

    Ces trois scénarios sont exactement ceux que le garde d'ADR 0009 refusait de
    compter deux fois. Ils décrivent donc, à eux seuls, tout ce que la suppression du
    garde a changé — et ils échoueront si quelqu'un le réintroduit sans écrire d'ADR.
    """

    def test_un_aller_retour_compte_deux_fois(self) -> None:
        """Deux franchissements observés, deux passages — un dans chaque sens."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        aller = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        retour = straight_line((900.0, 700.0), (900.0, 300.0), steps=6)
        track = session_track(track_path(1, CAR, aller)[0], hits=5)

        events = _run(counter, track, [*aller, *retour])

        assert len(events) == 2
        tally = counter.by_line["l1"]
        assert tally.total == 2
        # Le sens reste distingué : c'est ce qui permet de lire « 1 montant,
        # 1 descendant » plutôt qu'un « 2 » qui ne dit pas de quoi il est fait.
        assert tally.positive.total == 1
        assert tally.negative.total == 1

    def test_deux_pistes_de_la_meme_identite_comptent_chacune(self) -> None:
        """Une occlusion longue coupe la piste : les deux moitiés comptent.

        C'est la contrepartie assumée de l'abandon du garde. Le véhicule est le
        même, mais on ne compte plus des véhicules — on compte des passages, et
        deux passages ont été observés.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)

        for track_id in (1, 7):
            track = session_track(track_path(track_id, CAR, path)[0], hits=5, global_id=42)
            _run(counter, track, path, start_ms=1000.0 * track_id)

        assert counter.by_line["l1"].total == 2

    def test_le_badge_reste_alimente_sans_deduplication(self) -> None:
        """`counted_identities()` doit continuer de rendre les identités comptées.

        Le garde et le badge partagent le même ensemble. En supprimant le refus, il
        aurait été facile de cesser de le remplir : le ✓ aurait alors disparu de
        l'overlay alors que les compteurs, eux, montaient — ce qui se lit comme une
        panne de comptage et non comme un effet de bord d'optimisation.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5, global_id=42)

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
        assert tally.total == tally.positive.total + tally.negative.total

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
        # Les deux sens existent aussi dès le départ, et vides : « aucun passage »
        # doit se lire « 0 », jamais `None`.
        assert counter.by_line["l2"].positive.total == 0
        assert counter.by_line["l2"].positive.first_ms is None


class TestDetailParSens:
    """Ce que chaque sens sait de lui-même — la question que pose un carrefour.

    « 240 franchissements » ne dit pas si la rue se remplit ou se vide. Ces
    compteurs-là le disent, et par type, et sur quelle plage de temps.
    """

    def test_chaque_sens_porte_sa_propre_repartition_par_type(self) -> None:
        """La matrice type × sens, sans aucun compteur supplémentaire.

        C'est ce qui permet de répondre à « combien de camions **entrent** », qu'un
        `by_class` fusionné ne sait pas distinguer d'un camion qui sort.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        descendant = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        montant = straight_line((900.0, 700.0), (900.0, 300.0), steps=6)

        for index, (class_id, path) in enumerate(
            ((CAR, descendant), (TRUCK, descendant), (CAR, montant))
        ):
            track = session_track(track_path(index, class_id, path)[0], hits=5, global_id=index + 1)
            _run(counter, track, path, start_ms=1000.0 * index)

        tally = counter.by_line["l1"]
        assert tally.positive.by_class == {"car": 1, "truck": 1}
        assert tally.negative.by_class == {"car": 1}
        # Le `by_class` de la ligne reste la fusion des deux — dérivé, pas accumulé.
        assert tally.by_class == {"car": 2, "truck": 1}

    def test_chaque_sens_retient_son_premier_et_son_dernier_passage(self) -> None:
        """En temps de **scène**, jamais l'horloge murale (invariant 1)."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)

        for index, start in enumerate((0.0, 5000.0, 12_000.0)):
            track = session_track(track_path(index, CAR, path)[0], hits=5, global_id=index + 1)
            _run(counter, track, path, start_ms=start)

        positive = counter.by_line["l1"].positive
        assert positive.total == 3
        assert positive.first_ms == 120.0, "le franchissement tombe à la 4e frame du trajet"
        assert positive.last_ms == 12_120.0
        # Le sens jamais emprunté ne prétend pas avoir vu quelque chose.
        assert counter.by_line["l1"].negative.first_ms is None
        assert counter.by_line["l1"].negative.last_ms is None


class TestPlusieursLignes:
    def test_en_passages_chaque_ligne_franchie_compte(self) -> None:
        """Le **défaut** : deux lignes traversées, deux passages.

        C'est l'autre face de la décision d'ADR 0014, et elle mérite d'être écrite
        noir sur blanc : deux lignes en travers de la même voie **doublent**
        désormais le total. Qui trace deux lignes pour *situer* un passage doit donc
        savoir qu'il en compte deux — c'est la conséquence la plus facile à subir
        sans l'avoir voulue.
        """
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

        assert [event.line_id for event in events] == ["haute", "basse"]  # type: ignore[attr-defined]
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


class TestBandeMorte:
    """La bande morte autour du trait — ADR 0018, et les doublons qu'elle supprime.

    Les deux premiers tests rejouent des cas **mesurés** sur `video_7.mp4`, pas des
    cas imaginés : un véhicule arrêté sur un trait dont le côté basculait au dixième
    de pixel, et un véhicule dont la boîte s'effondrait puis se rétablissait. Les
    deux produisaient **trois** passages là où il n'y en avait qu'un.

    Le troisième test est celui qui garde la correction honnête : la bande ne doit
    pas *avaler* un franchissement, seulement le retarder jusqu'à ce qu'il soit
    crédible. C'est lui qui a imposé `settled_centroid`.

    La boîte par défaut fait 80×60, donc une demi-boîte vaut 40 px et la bande
    s'étend à ±10 px du trait.
    """

    def _hover(
        self, counter: LineCrossingCounter, offsets: list[float], *, size: tuple[float, float]
    ) -> list[object]:
        """Rejoue une piste dont le centroïde suit ces écarts au trait, en y."""
        track = session_track(
            track_path(1, CAR, [(900.0, 500.0 + offsets[0])], box_size=size)[0], hits=5
        )
        events: list[object] = []
        for index, offset in enumerate(offsets):
            if index > 0:
                track.previous_centroid = track.centroid
                track.box = box_at((900.0, 500.0 + offset), size=size)
                track.centroid = track.box.centroid
            events.extend(counter.observe((track,), index * 33.0, index))
        return events

    def test_un_vehicule_arrete_sur_le_trait_ne_compte_pas_trois_fois(self) -> None:
        """Le cas mesuré : 0,4 s d'arrêt sur la ligne, le signe bascule sur du bruit.

        Relevé sur `video_7.mp4` — trois passages comptés aux distances +0,1 / −0,1
        / +0,2 px. Ici le véhicule repart **du côté d'où il venait** : il n'a jamais
        franchi, et le compteur ne doit rien émettre du tout.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)

        events = self._hover(
            counter,
            [-30.0, -20.0, -12.0, -0.4, +0.1, -0.1, +0.2, -0.2, +0.1, -12.0, -25.0, -40.0],
            size=(80.0, 60.0),
        )

        assert events == []
        assert counter.by_line["l1"].total == 0

    def test_une_boite_qui_s_effondre_sur_le_trait_ne_compte_pas(self) -> None:
        """L'autre cas mesuré : la boîte perd puis retrouve son étendue.

        Le véhicule ne bouge pas ; c'est **sa boîte** qui rétrécit de 140 à 75 px de
        haut et son centre qui glisse de quelques pixels. Le côté bascule trois
        fois. La bande suit la boîte, donc elle rétrécit avec elle — et couvre
        quand même l'excursion, parce que le bruit est proportionnel à la boîte.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        track = session_track(
            track_path(1, CAR, [(900.0, 470.0)], box_size=(120.0, 140.0))[0], hits=5
        )
        events: list[object] = []
        # (écart au trait, hauteur de boîte) — le relevé de `#21`, transposé.
        for index, (offset, height) in enumerate(
            [
                (-30.0, 140.0),
                (-12.0, 138.0),
                (-0.9, 138.0),
                (+4.6, 94.0),
                (+5.7, 75.0),
                (-1.3, 122.0),
                (-2.9, 132.0),
                (-5.2, 137.0),
                (-20.0, 140.0),
            ]
        ):
            if index > 0:
                track.previous_centroid = track.centroid
                track.box = box_at((900.0, 500.0 + offset), size=(120.0, height))
                track.centroid = track.box.centroid
            events.extend(counter.observe((track,), index * 33.0, index))

        assert events == []
        assert counter.by_line["l1"].total == 0

    def test_un_vehicule_qui_traverse_la_bande_compte_une_fois(self) -> None:
        """**Le test qui garde la correction honnête.**

        Le véhicule s'arrête sur le trait puis repart de l'autre côté : c'est un
        vrai franchissement, simplement lent. La bande le retarde, elle ne
        l'efface pas.

        Sans `settled_centroid`, ce test échoue : à la sortie de bande, l'image
        précédente est du même côté que la piste, le segment ne coupe rien, et le
        franchissement disparaît. C'est exactement le mode de panne qu'une bande
        morte naïve introduit — plus grave que les doublons qu'elle corrige, parce
        qu'il fait *manquer* des véhicules.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)

        events = self._hover(
            counter,
            [-40.0, -25.0, -3.0, +1.0, -1.0, +2.0, +9.0, +25.0, +45.0],
            size=(80.0, 60.0),
        )

        assert len(events) == 1, "un franchissement lent reste un franchissement"
        event = events[0]
        assert isinstance(event, CrossingEvent)
        assert event.direction == DESCENDING
        assert counter.by_line["l1"].positive.total == 1

    def test_une_piste_nee_dans_la_bande_qui_traverse_compte_une_fois(self) -> None:
        """**Le franchissement que la bande morte avalait en silence.**

        La piste naît à 3 px du trait — dans la bande de ±10 px d'une boîte 80×60 —
        puis descend franchement de l'autre côté. Avant le rattrapage, son premier
        côté *tranché* servait d'amorçage et le franchissement disparaissait : le
        compteur rendait 0 pour un véhicule qui traverse à l'écran.

        Ce n'est pas un cas de laboratoire. La bande vaut un quart de demi-boîte,
        donc ±50 px pour un poids lourd de 400 px : tout véhicule qui entre dans le
        champ près du trait, et toute piste recréée après une occlusion à cet
        endroit, tombait dedans. C'est le cas dominant en trafic dense.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)

        events = self._hover(counter, [-3.0, +20.0, +45.0, +70.0], size=(80.0, 60.0))

        assert len(events) == 1, "une piste née dans la bande franchit quand même"
        event = events[0]
        assert isinstance(event, CrossingEvent)
        assert event.direction == DESCENDING

    def test_une_piste_nee_dans_la_bande_du_meme_cote_ne_compte_pas(self) -> None:
        """Le pendant du test précédent, et la borne qui l'empêche d'inventer.

        La piste naît à +2 px — sous le trait — et s'en éloigne toujours plus. Elle
        n'a jamais changé de côté : le rattrapage compare les deux côtés et ne
        trouve rien à compter. Sans cette comparaison, toute piste née dans la
        bande produirait un franchissement à sa sortie.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)

        assert self._hover(counter, [+2.0, +90.0, +150.0], size=(80.0, 60.0)) == []
        assert counter.by_line["l1"].total == 0

    def test_le_rattrapage_respecte_les_extremites_du_segment(self) -> None:
        """Le rattrapage n'est pas une porte dérobée : il exige la même intersection.

        Même trajet que le rattrapage nominal, mais à x=3000 — au-delà de
        l'extrémité de la ligne, qui s'arrête à x=1920. Le côté de la *droite*
        bascule, le segment tracé n'est jamais coupé, et rien ne doit être compté
        (piège 7 de prompt/13).
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        track = session_track(track_path(1, CAR, [(3000.0, 497.0)])[0], hits=5)
        events: list[object] = []
        for index, y in enumerate([497.0, 520.0, 545.0]):
            if index > 0:
                track.previous_centroid = track.centroid
                track.box = box_at((3000.0, y))
                track.centroid = track.box.centroid
            events.extend(counter.observe((track,), index * 33.0, index))

        assert events == []

    def test_la_bande_suit_la_taille_du_vehicule(self) -> None:
        """Un écart de 15 px : dans la bande d'un camion, hors de celle d'une moto.

        C'est la propriété qui rend le seuil transposable — même image, deux
        échelles ; et d'une résolution à l'autre, même raisonnement.
        """
        petit = LineCrossingCounter((LINE,), (), min_hits=2)
        gros = LineCrossingCounter((LINE,), (), min_hits=2)

        trajet = [-40.0, -15.0, +15.0, +40.0]
        # Moto : demi-boîte 20 px, bande ±5 px. Les deux points sont tranchés.
        assert len(self._hover(petit, trajet, size=(30.0, 40.0))) == 1
        # Camion : demi-boîte 200 px, bande ±50 px. Le trajet entier tient dedans,
        # et rien n'est encore décidé — ce qui est le bon comportement : à cette
        # échelle, 15 px ne prouvent pas de quel côté est le véhicule.
        assert self._hover(gros, trajet, size=(400.0, 200.0)) == []


class TestIdentifiantDePisteRecycle:
    """Un `track_id` réémis ne doit **rien** hériter du véhicule précédent.

    L'état géométrique du compteur est volontairement conservé au-delà de la mort
    d'une piste (piège 11 de prompt/13) : une piste réactivée sous `max_lost_ms`
    doit retrouver son côté, sinon elle repart en amorçage et son premier
    franchissement au retour est perdu.

    Mais la clé était `(track_id, ligne)`, et Ultralytics **recycle** ses
    identifiants. Au-delà de `max_lost_ms` la session donne un numéro de véhicule
    neuf au même `track_id` : le compteur, lui, retrouvait le côté et la dernière
    position de l'ancien occupant. Le segment testé reliait alors le dernier point
    du véhicule A au premier point du véhicule B — un bond qui traverse le trait —
    et un **franchissement fantôme** était émis pour un véhicule qui n'avait rien
    franchi.

    Le numéro de véhicule entre donc dans la clé. Une réactivation courte garde le
    même numéro, donc la même mémoire ; un recyclage en donne un neuf, donc un
    amorçage — ce qui est le comportement juste, puisque c'est un autre véhicule.
    """

    def _drive(
        self,
        counter: LineCrossingCounter,
        *,
        track_id: int,
        global_id: int,
        ys: list[float],
        start_frame: int,
    ) -> list[object]:
        track = session_track(
            track_path(track_id, CAR, [(900.0, ys[0])])[0], hits=5, global_id=global_id
        )
        events: list[object] = []
        for index, y in enumerate(ys):
            if index > 0:
                track.previous_centroid = track.centroid
                track.box = box_at((900.0, y))
                track.centroid = track.box.centroid
            frame = start_frame + index
            events.extend(counter.observe((track,), frame * 33.0, frame))
        return events

    def test_un_identifiant_recycle_n_emet_pas_de_franchissement_fantome(self) -> None:
        """Aucun des deux véhicules ne franchit ; le total doit rester à zéro.

        A longe la ligne par au-dessus et s'arrête ; B — même `track_id`, numéro
        neuf — naît **en dessous** et s'en éloigne. Avant la correction, B héritait
        du côté de A et le compteur émettait un passage descendant.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)

        self._drive(
            counter, track_id=7, global_id=1, ys=[380.0, 400.0, 420.0, 440.0], start_frame=0
        )
        assert counter.by_line["l1"].total == 0

        fantome = self._drive(
            counter, track_id=7, global_id=2, ys=[620.0, 660.0, 700.0], start_frame=10
        )

        assert fantome == [], "un identifiant recyclé ne franchit pas pour son prédécesseur"
        assert counter.by_line["l1"].total == 0

    def test_une_piste_reactivee_garde_sa_memoire(self) -> None:
        """La contrepartie : même numéro de véhicule, donc mémoire conservée.

        C'est la raison d'être d'un état non purgé (piège 11). La piste s'amorce
        au-dessus du trait, disparaît le temps d'une occlusion courte — la session
        lui rend le **même** numéro — et franchit au retour. Le franchissement doit
        être compté : sans mémoire, elle repartirait en amorçage et il serait perdu.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)

        self._drive(counter, track_id=7, global_id=1, ys=[380.0, 420.0], start_frame=0)
        retour = self._drive(counter, track_id=7, global_id=1, ys=[560.0, 620.0], start_frame=8)

        assert len(retour) == 1, "une piste réactivée franchit encore"
        assert counter.by_line["l1"].positive.total == 1


class TestQuasiFranchissements:
    """Le diagnostic qui explique une ligne à zéro.

    Il est né d'un cas réel : sur `video_7.mp4`, trois pistes s'éteignaient à ~33 px
    d'une ligne tracée à 60 px du bord droit de l'image, et la ligne affichait `0`
    exactement comme une ligne que personne n'emprunte. Les deux situations
    appellent des gestes opposés — attendre, ou déplacer le trait — et rien à
    l'écran ne permettait de les distinguer.

    **Ce n'est pas un comptage.** Un quasi-franchissement ne s'ajoute à aucun total
    et n'affirme pas qu'un véhicule est passé : il dit que le tracé et le suivi se
    sont manqués de peu. La boîte par défaut des scénarios fait 80×60, donc une
    demi-boîte vaut 40 px — c'est l'échelle à laquelle lire les distances ci-dessous.
    """

    def test_une_piste_eteinte_a_portee_de_la_ligne_est_signalee(self) -> None:
        """30 px de la ligne pour une demi-boîte de 40 : la boîte la recouvrait."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 470.0), steps=8)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert events == [], "aucun franchissement : la piste s'arrête avant la ligne"
        assert counter.by_line["l1"].total == 0
        assert counter.near_misses() == {"l1": 1}

    def test_une_piste_eteinte_loin_de_la_ligne_n_est_pas_signalee(self) -> None:
        """100 px pour une demi-boîte de 40 : le véhicule n'a jamais touché le trait.

        Sans ce refus, toute piste de l'image finirait par être signalée et le
        diagnostic ne désignerait plus rien.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 200.0), (900.0, 400.0), steps=8)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        _run(counter, track, path)

        assert counter.near_misses() == {"l1": 0}

    def test_une_piste_qui_a_franchi_n_est_jamais_signalee(self) -> None:
        """Franchir puis revenir se garer sur le trait ne fabrique pas de quasi.

        Le franchissement est un fait acquis ; le rappeler comme un manque ferait
        douter d'un chiffre pourtant juste.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=10)
        path += straight_line((900.0, 700.0), (900.0, 530.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        assert len(events) == 1
        assert counter.near_misses() == {"l1": 0}

    def test_une_piste_encore_vivante_n_est_pas_signalee(self) -> None:
        """Approcher n'est pas manquer.

        Sans ce filtre, l'aperçu live afficherait un quasi-franchissement par
        véhicule en approche puis le retirerait au franchissement — un chiffre qui
        clignote ne se lit pas. La session passe ses pistes vivantes en `ignore`.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 470.0), steps=8)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        _run(counter, track, path)

        assert counter.near_misses(ignore={1}) == {"l1": 0}
        assert counter.near_misses(ignore={2}) == {"l1": 1}, "une autre piste ne masque rien"

    def test_au_dela_de_l_extremite_du_trait_n_est_pas_a_portee(self) -> None:
        """La distance se mesure au **segment**, jamais à sa droite support.

        Le pendant exact de `test_une_piste_qui_passe_au_dela_des_extremites_ne_compte_pas`
        pour le diagnostic : sans cela, tout véhicule circulant dans le prolongement
        d'une ligne serait annoncé comme un franchissement manqué.
        """
        short_line = make_line("l1", a=(0.0, 500.0), b=(400.0, 500.0))
        counter = LineCrossingCounter((short_line,), (), min_hits=2)
        path = straight_line((1500.0, 300.0), (1500.0, 470.0), steps=8)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        _run(counter, track, path)

        assert counter.near_misses() == {"l1": 0}

    def test_chaque_ligne_a_son_compte_des_le_depart(self) -> None:
        """Une ligne sans quasi-franchissement est présente à zéro, jamais absente.

        Même discipline que `by_line` : une clé manquante se lirait « pas
        d'information » alors que zéro est une information.
        """
        counter = LineCrossingCounter(
            (make_line("haute", a=(0.0, 400.0), b=(1920.0, 400.0)), make_line("basse")),
            (),
            min_hits=2,
        )

        assert counter.near_misses() == {"haute": 0, "basse": 0}


class TestTexteDePlaqueTamponne:
    """Le texte voté que le compteur recopie sur ses événements.

    `test_une_plaque_lue_apres_le_franchissement_ne_figure_pas_sur_la_ligne` affirme
    **volontairement une limite** : c'est la conséquence de l'ordonnancement de
    `feed()`, pas un défaut. L'écrire est ce qui empêchera qu'on le signale comme un
    bug dans six mois. Voir ADR 0007.
    """

    def test_un_franchissement_porte_le_texte_vote_de_la_piste(self) -> None:
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5)
        track.plate_text = "AB-123-CD"
        track.plate_text_score = 0.88

        events = _run(counter, track, path)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, CrossingEvent)
        assert event.plate_text == "AB-123-CD"
        assert event.plate_text_score == 0.88

    def test_une_piste_sans_texte_tamponne_none_et_non_une_chaine_vide(self) -> None:
        """« Pas encore lu » est une information ; une plaque vide n'en est pas une."""
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        event = events[0]
        assert isinstance(event, CrossingEvent)
        assert event.plate_text is None
        assert event.plate_text_score is None

    def test_une_plaque_lue_apres_le_franchissement_ne_figure_pas_sur_la_ligne(self) -> None:
        """La limite d'ordonnancement, affirmée exprès.

        Les franchissements de la frame N sortent de `feed()` **avant** la passe OCR
        de la frame N. Une plaque lue pour la première fois sur la frame même du
        franchissement n'apparaît donc pas sur cette ligne — elle apparaît dans le
        registre, qui agrège toute la vie du véhicule. Un franchissement dit ce que
        le serveur savait quand il a compté ; le registre dit ce qu'il sait à la fin.
        """
        counter = LineCrossingCounter((LINE,), (), min_hits=2)
        path = straight_line((900.0, 300.0), (900.0, 700.0), steps=6)
        track = session_track(track_path(1, CAR, path)[0], hits=5)

        events = _run(counter, track, path)

        # La plaque n'est lue qu'après coup : l'événement déjà émis est immuable.
        track.plate_text = "AB-123-CD"
        track.plate_text_score = 0.88

        event = events[0]
        assert isinstance(event, CrossingEvent)
        assert event.plate_text is None
