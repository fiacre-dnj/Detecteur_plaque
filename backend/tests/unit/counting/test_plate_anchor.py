"""L'ancre de plaque — ce qui rend l'étranglement du détecteur invisible.

L'objection qui interdisait d'étrangler le détecteur était que ses rectangles
clignoteraient. Elle tombe si les images sautées reçoivent une estimation continue
plutôt que rien. Ces tests portent sur la propriété qui rend cette estimation
utilisable : **une ancre relative suit son véhicule**, là où une position absolue
mémorisée décrocherait dès l'image suivante.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.domain.models import BoundingBox
from traffic_analysis.features.counting.domain.plate_anchor import PlateAnchor, anchor_from

#: Un véhicule et sa plaque, tels qu'une détection réelle les rend.
VEHICLE = BoundingBox(x=100.0, y=200.0, width=200.0, height=150.0)
PLATE = BoundingBox(x=180.0, y=310.0, width=40.0, height=10.0)


class TestMemorisation:
    def test_une_plaque_est_memorisee_en_fractions_de_son_vehicule(self) -> None:
        anchor = anchor_from(VEHICLE, PLATE, 0.82)

        assert anchor is not None
        assert anchor.rx == pytest.approx(0.4)
        assert anchor.ry == pytest.approx(110.0 / 150.0)
        assert anchor.rw == pytest.approx(0.2)
        assert anchor.score == pytest.approx(0.82)
        assert anchor.age == 0

    def test_une_plaque_hors_de_son_vehicule_n_est_pas_memorisee(self) -> None:
        """Un désalignement promènerait un rectangle à côté de la voiture pendant
        `max_anchor_age` images. Ne rien dessiner vaut mieux que dessiner faux."""
        ailleurs = BoundingBox(x=800.0, y=200.0, width=40.0, height=10.0)

        assert anchor_from(VEHICLE, ailleurs, 0.82) is None

    @pytest.mark.parametrize(
        "vehicle",
        [
            BoundingBox(x=100.0, y=200.0, width=0.0, height=150.0),
            BoundingBox(x=100.0, y=200.0, width=200.0, height=0.0),
        ],
        ids=["largeur nulle", "hauteur nulle"],
    )
    def test_un_vehicule_degenere_ne_definit_aucun_repere(self, vehicle: BoundingBox) -> None:
        assert anchor_from(vehicle, PLATE, 0.82) is None

    def test_un_leger_depassement_est_tolere(self) -> None:
        """La borne est lâche **délibérément** : une boîte de véhicule est
        elle-même approximative, et refuser un dépassement d'un pixel perdrait des
        ancres parfaitement utiles."""
        debordante = BoundingBox(x=95.0, y=310.0, width=40.0, height=10.0)

        assert anchor_from(VEHICLE, debordante, 0.82) is not None


class TestReprojection:
    def test_l_ancre_suit_une_translation_du_vehicule(self) -> None:
        """**Le cas nominal** : un véhicule qui avance dans le plan image."""
        anchor = anchor_from(VEHICLE, PLATE, 0.82)
        assert anchor is not None

        deplace = BoundingBox(x=140.0, y=230.0, width=200.0, height=150.0)
        projected = anchor.project(deplace)

        assert projected.x == pytest.approx(PLATE.x + 40.0)
        assert projected.y == pytest.approx(PLATE.y + 30.0)
        assert projected.width == pytest.approx(PLATE.width)

    def test_l_ancre_suit_un_grossissement_du_vehicule(self) -> None:
        """Un véhicule qui s'approche grossit ; sa plaque grossit avec lui.

        C'est ce qu'une position absolue mémorisée ne pourrait pas faire, et la
        raison pour laquelle l'ancre est relative et non absolue.
        """
        anchor = anchor_from(VEHICLE, PLATE, 0.82)
        assert anchor is not None

        grossi = BoundingBox(x=100.0, y=200.0, width=400.0, height=300.0)
        projected = anchor.project(grossi)

        assert projected.width == pytest.approx(PLATE.width * 2)
        assert projected.height == pytest.approx(PLATE.height * 2)

    def test_reprojeter_sur_la_boite_d_origine_rend_la_plaque_d_origine(self) -> None:
        """La propriété de fermeture : mémoriser puis reprojeter sans mouvement ne
        doit rien déplacer, sinon l'ancre introduirait une dérive à chaque image."""
        anchor = anchor_from(VEHICLE, PLATE, 0.82)
        assert anchor is not None

        projected = anchor.project(VEHICLE)

        assert projected.x == pytest.approx(PLATE.x)
        assert projected.y == pytest.approx(PLATE.y)
        assert projected.width == pytest.approx(PLATE.width)
        assert projected.height == pytest.approx(PLATE.height)


class TestVieillissement:
    def test_l_age_s_incremente_sans_toucher_a_la_geometrie(self) -> None:
        anchor = PlateAnchor(rx=0.4, ry=0.7, rw=0.2, rh=0.07, score=0.82)

        aged = anchor.aged()

        assert aged.age == 1
        assert (aged.rx, aged.ry, aged.rw, aged.rh) == (0.4, 0.7, 0.2, 0.07)
        # Le score est reproduit **tel quel** : le raboter laisserait croire que le
        # modèle hésite, alors qu'il n'a rien mesuré du tout. C'est `stale` qui porte
        # « ceci n'est pas une mesure ».
        assert aged.score == pytest.approx(0.82)

    def test_l_ancre_d_origine_n_est_pas_mutee(self) -> None:
        """Immuable : deux pistes ne doivent jamais partager un compteur d'âge."""
        anchor = PlateAnchor(rx=0.4, ry=0.7, rw=0.2, rh=0.07, score=0.82)

        anchor.aged().aged()

        assert anchor.age == 0
