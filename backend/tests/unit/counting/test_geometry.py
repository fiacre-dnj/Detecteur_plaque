"""Géométrie du comptage — écrit **avant** l'implémentation.

Ces tests sont la spécification de `prompt/03` §1. Deux d'entre eux valent seuls
la lecture de tout le fichier :

- `test_une_piste_qui_passe_au_dela_des_extremites_ne_croise_pas` : sans le test
  d'intersection de segments, un véhicule passant hors des extrémités tracées est
  compté, parce qu'il change bien de côté de la ligne **infinie** ;
- `test_un_polygone_concave_en_u_exclut_le_creux` : une voie tracée à la main est
  presque toujours concave, et un test d'appartenance naïf y échoue.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.domain.geometry import (
    Point,
    distance,
    point_in_polygon,
    point_segment_distance,
    segments_intersect,
    side_of_line,
    signed_line_offset,
)

# Ligne horizontale orientée vers la droite : A à gauche, B à droite.
A = Point(0.0, 100.0)
B = Point(200.0, 100.0)


class TestSideOfLine:
    """La convention de sens est LE contrat partagé avec le frontend.

    `+1` et `-1` sont exposés tels quels dans l'API et libellés « A→B » / « B→A »
    dans l'interface, qui s'en sert pour dessiner les flèches du registre. Si le
    signe change ici, les flèches affichées mentent.
    """

    def test_un_point_sous_la_ligne_est_du_cote_positif(self) -> None:
        # « Sous » à l'écran : y croissant vers le bas en coordonnées image.
        assert side_of_line(A, B, Point(100.0, 150.0)) == 1

    def test_un_point_au_dessus_de_la_ligne_est_du_cote_negatif(self) -> None:
        assert side_of_line(A, B, Point(100.0, 50.0)) == -1

    def test_un_point_exactement_sur_la_ligne_ne_choisit_pas_de_cote(self) -> None:
        """`0` signifie « on attend la frame suivante », pas « côté positif ».

        Le compteur ignore cette frame. Trancher arbitrairement produirait un
        faux franchissement à chaque fois qu'un centroïde effleure la ligne.
        """
        assert side_of_line(A, B, Point(100.0, 100.0)) == 0

    def test_un_point_sur_le_prolongement_de_la_ligne_est_aussi_a_zero(self) -> None:
        """Le côté est défini par rapport à la droite, pas au segment.

        C'est précisément pourquoi `side_of_line` ne suffit pas à décider d'un
        franchissement : il faut en plus l'intersection de segments.
        """
        assert side_of_line(A, B, Point(500.0, 100.0)) == 0

    def test_inverser_l_orientation_inverse_le_signe(self) -> None:
        point = Point(100.0, 150.0)

        assert side_of_line(A, B, point) == -side_of_line(B, A, point)


class TestSegmentsIntersect:
    def test_deux_segments_qui_se_croisent(self) -> None:
        assert segments_intersect(Point(100.0, 50.0), Point(100.0, 150.0), A, B)

    def test_une_piste_qui_passe_au_dela_des_extremites_ne_croise_pas(self) -> None:
        """Le cas qui justifie l'existence de cette fonction.

        Ce trajet change bel et bien de côté de la ligne **infinie** : le seul
        test de signe le compterait. Il ne coupe pourtant jamais le segment
        tracé par l'utilisateur, donc il ne doit pas compter.
        """
        avant = Point(500.0, 50.0)
        apres = Point(500.0, 150.0)

        assert side_of_line(A, B, avant) != side_of_line(A, B, apres)
        assert not segments_intersect(avant, apres, A, B)

    def test_deux_segments_disjoints(self) -> None:
        assert not segments_intersect(Point(0.0, 0.0), Point(10.0, 0.0), A, B)

    def test_deux_segments_colineaires_ne_se_croisent_pas(self) -> None:
        """Comportement documenté et figé.

        Un véhicule qui longe exactement la ligne ne la franchit pas. Compter ce
        cas ferait exploser les compteurs sur une ligne mal placée, parallèle à
        la voie.
        """
        assert not segments_intersect(Point(10.0, 100.0), Point(50.0, 100.0), A, B)

    def test_un_segment_qui_touche_l_autre_par_une_extremite(self) -> None:
        """Le contact par une extrémité compte comme une intersection.

        Le franchissement réel a lieu : refuser ce cas perdrait le véhicule dont
        le centroïde atterrit pile sur la ligne à une frame, puis passe au-delà.
        """
        assert segments_intersect(Point(100.0, 50.0), Point(100.0, 100.0), A, B)

    def test_un_segment_de_longueur_nulle_ne_croise_rien(self) -> None:
        """Le cas de la première frame d'une piste.

        `previous_centroid` valant `None`, le compteur passe deux fois le même
        point : cela ne doit jamais produire d'intersection.
        """
        point = Point(100.0, 100.0)

        assert not segments_intersect(point, point, A, B)


class TestPointInPolygon:
    CARRE = (
        Point(0.0, 0.0),
        Point(100.0, 0.0),
        Point(100.0, 100.0),
        Point(0.0, 100.0),
    )

    # Un U ouvert vers le haut : le creux central est DEHORS.
    U = (
        Point(0.0, 0.0),
        Point(30.0, 0.0),
        Point(30.0, 70.0),
        Point(70.0, 70.0),
        Point(70.0, 0.0),
        Point(100.0, 0.0),
        Point(100.0, 100.0),
        Point(0.0, 100.0),
    )

    def test_un_point_au_centre_est_dedans(self) -> None:
        assert point_in_polygon(Point(50.0, 50.0), self.CARRE)

    def test_un_point_a_l_exterieur_est_dehors(self) -> None:
        assert not point_in_polygon(Point(150.0, 50.0), self.CARRE)

    def test_un_polygone_concave_en_u_exclut_le_creux(self) -> None:
        """Une voie tracée à la main est presque toujours concave.

        Le creux du U est géométriquement dehors alors qu'il est *entouré* par la
        boîte englobante du polygone : un test naïf par boîte le dirait dedans.
        """
        assert not point_in_polygon(Point(50.0, 30.0), self.U)
        assert point_in_polygon(Point(15.0, 30.0), self.U)
        assert point_in_polygon(Point(50.0, 85.0), self.U)

    def test_moins_de_trois_sommets_n_est_pas_un_polygone(self) -> None:
        """Une zone en cours de tracé n'a pas encore de surface.

        Rendre `True` pendant le tracé ferait clignoter le masque « ignorer hors
        zone » à chaque clic.
        """
        assert not point_in_polygon(Point(1.0, 1.0), ())
        assert not point_in_polygon(Point(1.0, 1.0), (Point(0.0, 0.0),))
        assert not point_in_polygon(Point(1.0, 1.0), (Point(0.0, 0.0), Point(10.0, 10.0)))

    @pytest.mark.parametrize(
        ("point", "expected"),
        [
            # Comportement figé sur les arêtes : le lancer de rayon inclut
            # l'arête gauche et supérieure, exclut la droite et l'inférieure.
            # La valeur exacte importe moins que sa STABILITÉ : un basculement
            # ferait entrer et sortir une piste immobile sur un bord, et chaque
            # front produirait une entrée de zone.
            (Point(0.0, 50.0), True),  # arête gauche
            (Point(100.0, 50.0), False),  # arête droite
        ],
    )
    def test_un_point_sur_une_arete_a_un_comportement_fige(
        self, point: Point, expected: bool
    ) -> None:
        assert point_in_polygon(point, self.CARRE) is expected

    def test_le_meme_point_donne_toujours_la_meme_reponse(self) -> None:
        """Non-régression de la stabilité, indépendamment de la convention.

        C'est cette propriété qui compte pour le comptage : une piste arrêtée sur
        un bord ne doit pas produire une entrée de zone par frame.
        """
        for corner in self.CARRE:
            first = point_in_polygon(corner, self.CARRE)
            assert all(point_in_polygon(corner, self.CARRE) is first for _ in range(5))


class TestDistance:
    def test_distance_euclidienne(self) -> None:
        assert distance(Point(0.0, 0.0), Point(3.0, 4.0)) == pytest.approx(5.0)

    def test_distance_a_soi_meme_est_nulle(self) -> None:
        assert distance(Point(7.0, 7.0), Point(7.0, 7.0)) == 0.0


class TestSignedLineOffset:
    """La distance signée à la droite : `side_of_line` en garde le signe seul.

    Le côté suffit à décider d'un franchissement ; il ne suffit pas à décider qu'un
    franchissement est **crédible**, et c'est pour cela que la quantité complète
    existe (ADR 0018).
    """

    def test_le_signe_est_celui_du_cote(self) -> None:
        for point in (Point(100.0, 130.0), Point(100.0, 70.0), Point(-500.0, 130.0)):
            offset = signed_line_offset(A, B, point)
            sign = 0 if offset == 0.0 else (1 if offset > 0 else -1)
            assert sign == side_of_line(A, B, point)

    def test_la_valeur_est_la_distance_perpendiculaire(self) -> None:
        assert signed_line_offset(A, B, Point(100.0, 130.0)) == pytest.approx(30.0)
        assert signed_line_offset(A, B, Point(100.0, 70.0)) == pytest.approx(-30.0)

    def test_au_dela_des_extremites_la_droite_reste_la_droite(self) -> None:
        """Contrairement à `point_segment_distance`, la droite est infinie.

        Les deux mesures répondent à deux questions et ne s'échangent pas : le côté
        se juge sur la droite, la proximité du **trait** sur le segment.
        """
        assert signed_line_offset(A, B, Point(9000.0, 130.0)) == pytest.approx(30.0)

    def test_une_ligne_degeneree_rend_zero(self) -> None:
        assert signed_line_offset(A, A, Point(50.0, 50.0)) == 0.0


class TestPointSegmentDistance:
    """La distance au **segment**, qui n'est pas la distance à sa droite.

    C'est la même distinction que celle entre `side_of_line` et
    `segments_intersect`, et elle sert au même endroit : au-delà des extrémités
    tracées, un point peut être à trois pixels de la droite et très loin du trait.
    """

    def test_en_face_du_segment_la_distance_est_perpendiculaire(self) -> None:
        assert point_segment_distance(Point(100.0, 130.0), A, B) == pytest.approx(30.0)

    def test_au_dela_de_l_extremite_la_distance_est_celle_du_bout(self) -> None:
        """Le point qui compte est **l'extrémité**, pas le pied de la perpendiculaire.

        Sans le bornage de la projection, ce point serait annoncé à 30 px du trait
        alors qu'il en est à 300 : c'est ce qui fabriquerait des quasi-franchissements
        pour des véhicules passant hors du tracé.
        """
        far = Point(500.0, 130.0)
        assert point_segment_distance(far, A, B) == pytest.approx(distance(far, B))
        assert point_segment_distance(far, A, B) > 300.0

    def test_sur_le_segment_la_distance_est_nulle(self) -> None:
        assert point_segment_distance(Point(120.0, 100.0), A, B) == pytest.approx(0.0)

    def test_un_segment_degenere_rend_la_distance_a_son_point(self) -> None:
        """Deux clics au même endroit : rendre la distance au point plutôt que lever.

        Le cas est refusé à la validation de l'API, mais une configuration ancienne
        peut y échapper — et une division par zéro dans le diagnostic ferait échouer
        une analyse par ailleurs valable.
        """
        assert point_segment_distance(Point(0.0, 0.0), A, A) == pytest.approx(100.0)
