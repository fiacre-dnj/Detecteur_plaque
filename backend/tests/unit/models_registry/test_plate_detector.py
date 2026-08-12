"""L'adaptateur de détection de plaques, **sans poids et sans ultralytics**.

Deux choses valent d'être démontrées ici, et elles ne se ressemblent pas.

La première est l'**aller-retour de coordonnées** de la mosaïque. Plusieurs
recadrages de véhicules entrent dans une seule image de 640×640, et une boîte
trouvée en ressort après trois changements de repère : cellule → recadrage →
image complète. Une erreur dans cette chaîne ne lève rien. Elle décale tous les
rectangles, et un rectangle décalé se lit comme un défaut de détection — jamais
comme un défaut de repère (invariant 14 : le serveur ne peut pas détecter ce que
le client voit). Les tests reconstruisent donc la boîte attendue à la main et
exigent l'égalité au pixel près.

La seconde est le **filtre de plausibilité**. Il ne peut que retirer des
détections, donc il ne peut pas améliorer le rappel ; tout son intérêt est de ne
pas retirer les bonnes. Chaque test nomme la boîte absurde qu'il écarte.

Le modèle n'est jamais chargé : `_pack`, `_locate`, `_to_crop` et `_is_plausible`
sont des fonctions de géométrie pure, et c'est délibérément là qu'est la logique
risquée.
"""

from __future__ import annotations

import numpy as np
import pytest

from traffic_analysis.features.counting.application.dto import BoundingBox
from traffic_analysis.features.models_registry.infrastructure.plate_detector import (
    DEFAULT_MOSAIC_SIDE,
    MOSAIC_GUTTER_PX,
    NET_SIZE,
    PAD_VALUE,
    PlateGeometry,
    UltralyticsPlateDetector,
)

_MISSING = "modele-absent.onnx"


def _detector(**kwargs: object) -> UltralyticsPlateDetector:
    from pathlib import Path

    return UltralyticsPlateDetector(Path(_MISSING), 0.25, **kwargs)  # type: ignore[arg-type]


def _crop(width: int, height: int, fill: int = 200) -> np.ndarray:
    """Un recadrage texturé : une image unie ne prouverait pas l'orientation."""
    crop = np.full((height, width, 3), fill, dtype=np.uint8)
    crop[:, : max(1, width // 4)] = 40
    return crop


class TestEmpaquetage:
    def test_la_mosaique_est_desactivee_par_defaut(self) -> None:
        """**Le rappel ne se troque pas contre du débit sans qu'on le demande.**

        L'empaquetage n'est pas gratuit, contrairement à ce que suggère l'intuition
        « sur-échantillonner n'apporte pas d'information ». Ce qui décide qu'une
        plaque est trouvée est sa taille dans l'entrée du réseau, et elle ne dépend
        que de la cellule : `plaque ≈ 0,15 × côté_de_cellule`. Mesuré sur 657
        véhicules de vraie circulation — côté 1 : 100 % de rappel ; côté 2 : 84 %
        pour 3,4× ; côté 3 : 56 % pour 6,6×.

        Ce test existe pour qu'un futur réglage de performance ne fasse pas glisser
        ce défaut sans que la mesure soit refaite.
        """
        assert DEFAULT_MOSAIC_SIDE == 1
        assert _detector()._mosaic_side == 1

    def test_une_seule_piste_occupe_une_grille_1x1(self) -> None:
        """Pas de mosaïque quand il n'y a rien à empaqueter."""
        detector = _detector()
        tile, placements = detector._pack([(0, _crop(200, 150), 10, 20)])

        assert tile.shape == (NET_SIZE, NET_SIZE, 3)
        assert len(placements) == 1
        cell = NET_SIZE - 2 * MOSAIC_GUTTER_PX
        # Le recadrage est 4:3, donc c'est la largeur qui bute sur la cellule.
        assert placements[0].scale == pytest.approx(cell / 200)

    def test_quatre_pistes_tiennent_dans_une_grille_2x2(self) -> None:
        """La grille est la plus petite qui contienne le paquet, jamais la plus grande.

        Une grille 3×3 pour quatre recadrages rétrécirait les cellules de 308 à
        202 px sans rien empaqueter de plus.
        """
        detector = _detector()
        _, placements = detector._pack([(i, _crop(200, 150), 0, 0) for i in range(4)])

        cell = (NET_SIZE - 3 * MOSAIC_GUTTER_PX) // 2
        offsets = {(p.offset_x, p.offset_y) for p in placements}
        assert offsets == {
            (MOSAIC_GUTTER_PX, MOSAIC_GUTTER_PX),
            (2 * MOSAIC_GUTTER_PX + cell, MOSAIC_GUTTER_PX),
            (MOSAIC_GUTTER_PX, 2 * MOSAIC_GUTTER_PX + cell),
            (2 * MOSAIC_GUTTER_PX + cell, 2 * MOSAIC_GUTTER_PX + cell),
        }

    def test_les_cellules_ne_se_touchent_jamais(self) -> None:
        """La gouttière n'est pas cosmétique.

        Sans elle, le champ récepteur du réseau déborde d'une cellule sur l'autre et
        fabrique des détections à cheval sur deux véhicules — une plaque attribuée au
        voisin, ce qu'aucune couche en aval ne peut rattraper.
        """
        detector = _detector()
        _, placements = detector._pack([(i, _crop(180, 180), 0, 0) for i in range(9)])

        for first in placements:
            for second in placements:
                if first is second:
                    continue
                separated_x = (
                    first.offset_x + first.placed_width <= second.offset_x
                    or second.offset_x + second.placed_width <= first.offset_x
                )
                separated_y = (
                    first.offset_y + first.placed_height <= second.offset_y
                    or second.offset_y + second.placed_height <= first.offset_y
                )
                assert separated_x or separated_y

    def test_le_fond_est_le_gris_neutre_du_letterbox(self) -> None:
        """114 et non 0 : le réseau a vu ce gris à chaque image de son entraînement.

        Du noir serait un signal fort sur une bande entière de l'image.
        """
        detector = _detector()
        tile, _ = detector._pack([(0, _crop(100, 100), 0, 0)])
        assert tile[0, 0].tolist() == [PAD_VALUE] * 3

    def test_le_rapport_d_aspect_est_conserve(self) -> None:
        """Étirer un véhicule déformerait la plaque au-delà de ce que le modèle connaît."""
        detector = _detector()
        _, placements = detector._pack([(0, _crop(300, 100), 0, 0)])
        placement = placements[0]
        assert placement.placed_width / placement.placed_height == pytest.approx(3.0, abs=0.02)


class TestAllerRetourDeCoordonnees:
    def test_une_boite_revient_exactement_a_sa_place(self) -> None:
        """Le test central de tout ce fichier.

        On part d'une boîte *connue* dans le recadrage, on la projette dans la
        mosaïque comme le ferait le réseau, et on exige que le chemin retour rende
        l'originale. C'est l'aller-retour complet : cellule, échelle, origine.
        """
        detector = _detector()
        crop_origin_x, crop_origin_y = 640, 360
        _, placements = detector._pack([(0, _crop(240, 180), crop_origin_x, crop_origin_y)])
        placement = placements[0]

        # Une plaque plausible dans le repère du recadrage.
        expected = BoundingBox(x=60.0, y=120.0, width=100.0, height=25.0)
        # Projetée dans la mosaïque, exactement comme le réseau la verrait.
        scale = placement.scale
        projected = (
            expected.x * scale + placement.offset_x,
            expected.y * scale + placement.offset_y,
            (expected.x + expected.width) * scale + placement.offset_x,
            (expected.y + expected.height) * scale + placement.offset_y,
        )

        recovered = detector._to_crop(placement, *projected)

        assert recovered is not None
        assert recovered.x == pytest.approx(expected.x, abs=0.01)
        assert recovered.y == pytest.approx(expected.y, abs=0.01)
        assert recovered.width == pytest.approx(expected.width, abs=0.01)
        assert recovered.height == pytest.approx(expected.height, abs=0.01)

    def test_la_cellule_est_designee_par_le_centre_de_la_boite(self) -> None:
        """Par le centre et non par un chevauchement.

        Un critère de chevauchement attribuerait une boîte débordant légèrement de sa
        cellule à **deux** véhicules à la fois.
        """
        detector = _detector()
        _, placements = detector._pack([(i, _crop(200, 200), 0, 0) for i in range(4)])

        for placement in placements:
            centre_x = placement.offset_x + placement.placed_width / 2
            centre_y = placement.offset_y + placement.placed_height / 2
            assert detector._locate(placements, centre_x, centre_y) is placement

    def test_une_boite_tombee_dans_la_gouttiere_n_appartient_a_personne(self) -> None:
        """Mieux vaut perdre une détection que l'attribuer au mauvais véhicule."""
        detector = _detector()
        _, placements = detector._pack([(i, _crop(200, 200), 0, 0) for i in range(4)])
        assert detector._locate(placements, 1.0, 1.0) is None

    def test_une_boite_debordant_de_sa_cellule_est_decoupee_aux_bornes(self) -> None:
        """Sans découpage, elle rendrait des coordonnées hors du véhicule.

        Le sérialiseur les publierait telles quelles et le canvas dessinerait un
        rectangle à côté de la voiture.
        """
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 150), 0, 0)])
        placement = placements[0]

        recovered = detector._to_crop(
            placement,
            placement.offset_x - 50.0,
            placement.offset_y - 50.0,
            placement.offset_x + placement.placed_width + 50.0,
            placement.offset_y + placement.placed_height + 50.0,
        )

        assert recovered is not None
        assert recovered.x == 0.0
        assert recovered.y == 0.0
        assert recovered.width == pytest.approx(200.0, abs=1.0)
        assert recovered.height == pytest.approx(150.0, abs=1.0)

    def test_une_boite_entierement_hors_cellule_est_ecartee(self) -> None:
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 150), 0, 0)])
        placement = placements[0]
        assert (
            detector._to_crop(
                placement,
                placement.offset_x - 80.0,
                placement.offset_y - 80.0,
                placement.offset_x - 40.0,
                placement.offset_y - 40.0,
            )
            is None
        )

    def test_l_origine_du_recadrage_est_bien_rajoutee(self) -> None:
        """Le contrat du port : des coordonnées de l'image **complète**.

        Un adaptateur qui oublie de réexprimer rendrait des coordonnées relatives au
        recadrage, plausibles et fausses de plusieurs centaines de pixels.
        """
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 150), 800, 400)])
        placement = placements[0]

        selected = detector._select(
            [(placement, BoundingBox(x=10.0, y=100.0, width=80.0, height=20.0), 0.9)],
            _crop(1920, 1080),
        )

        assert selected[0].box.x == pytest.approx(810.0)
        assert selected[0].box.y == pytest.approx(500.0)


class TestPlausibilite:
    @staticmethod
    def _placement(detector: UltralyticsPlateDetector, width: int = 200, height: int = 160):  # noqa: ANN205
        _, placements = detector._pack([(0, _crop(width, height), 0, 0)])
        return placements[0]

    def test_une_plaque_ordinaire_passe(self) -> None:
        detector = _detector()
        placement = self._placement(detector)
        plate = BoundingBox(x=60.0, y=110.0, width=80.0, height=20.0)
        assert detector._is_plausible(plate, placement)

    def test_une_boite_plus_haute_que_large_est_ecartee(self) -> None:
        """Une plaque est plus large que haute. Verticale, c'est un montant de portière."""
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=60.0, y=110.0, width=20.0, height=40.0), placement
        )

    def test_une_boite_aussi_large_que_le_vehicule_est_ecartee(self) -> None:
        """C'est le véhicule lui-même, pas sa plaque."""
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=0.0, y=110.0, width=198.0, height=30.0), placement
        )

    def test_un_ecusson_est_ecarte(self) -> None:
        """Trop petit par rapport au véhicule pour être sa plaque."""
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=90.0, y=110.0, width=4.0, height=2.0), placement
        )

    def test_un_reflet_de_pare_brise_est_ecarte(self) -> None:
        """Le haut du véhicule ne porte pas de plaque.

        Le garde est très permissif — 12 % de la hauteur — parce qu'un plan plongeant
        sur un camion place la plaque plus haut qu'on ne le croit.
        """
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=60.0, y=2.0, width=80.0, height=18.0), placement
        )

    def test_une_plaque_de_moto_passe(self) -> None:
        """~1,4:1 : presque carrée, et parfaitement légitime."""
        detector = _detector()
        placement = self._placement(detector)
        assert detector._is_plausible(
            BoundingBox(x=80.0, y=120.0, width=28.0, height=20.0), placement
        )


class TestSelection:
    def test_seule_la_meilleure_est_gardee_par_defaut(self) -> None:
        """Un véhicule a **une** plaque visible.

        En garder plusieurs multiplie les rectangles à l'écran et le coût d'OCR sans
        rien apprendre — et laisse le vote arbitrer entre deux lectures d'objets
        différents.
        """
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 160), 0, 0)])
        placement = placements[0]

        selected = detector._select(
            [
                (placement, BoundingBox(x=10.0, y=110.0, width=80.0, height=20.0), 0.42),
                (placement, BoundingBox(x=60.0, y=112.0, width=82.0, height=21.0), 0.91),
                (placement, BoundingBox(x=20.0, y=118.0, width=70.0, height=18.0), 0.55),
            ],
            _crop(1920, 1080),
        )

        assert len(selected) == 1
        assert selected[0].score == pytest.approx(0.91)

    def test_le_plafond_par_vehicule_est_reglable(self) -> None:
        detector = _detector(geometry=PlateGeometry(max_per_vehicle=2))
        _, placements = detector._pack([(0, _crop(200, 160), 0, 0)])
        placement = placements[0]

        selected = detector._select(
            [
                (placement, BoundingBox(x=10.0, y=110.0, width=80.0, height=20.0), 0.42),
                (placement, BoundingBox(x=60.0, y=112.0, width=82.0, height=21.0), 0.91),
                (placement, BoundingBox(x=20.0, y=118.0, width=70.0, height=18.0), 0.55),
            ],
            _crop(1920, 1080),
        )

        assert [round(detection.score, 2) for detection in selected] == [0.91, 0.55]


class TestDegradationGracieuse:
    def test_un_modele_absent_rend_un_tuple_par_boite(self) -> None:
        """Le contrat d'alignement positionnel tient même quand rien ne fonctionne.

        Rendre une liste plus courte obligerait l'appelant à deviner à quelle piste
        appartient quel résultat.
        """
        detector = _detector()
        boxes = [BoundingBox(x=0.0, y=0.0, width=100.0, height=100.0)] * 3
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        assert detector.detect_many(image, boxes) == ((), (), ())

    def test_un_lot_vide_rend_un_lot_vide(self) -> None:
        """`np.stack([])` lève : le cas vide se traite avant tout le reste."""
        detector = _detector()
        assert detector.detect_many(np.zeros((10, 10, 3), dtype=np.uint8), []) == ()

    def test_deux_appels_ne_journalisent_pas_deux_fois(self) -> None:
        """Le latch `_checked` : sinon des milliers de lignes identiques par vidéo."""
        detector = _detector()
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        box = BoundingBox(x=0.0, y=0.0, width=100.0, height=100.0)
        assert detector.detect(image, box) == ()
        assert detector.detect(image, box) == ()
        assert detector._checked is True

    def test_un_recadrage_minuscule_ne_coute_aucune_inference(self) -> None:
        """Sous 32 px, l'inférence coûterait sans jamais rien trouver."""
        detector = _detector()
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        assert detector.detect(image, BoundingBox(x=0.0, y=0.0, width=8.0, height=8.0)) == ()
