"""Le filtre qui sépare une plaque d'un pare-chocs.

**Ces tests n'existaient pas, et ne pouvaient pas exister.** Le filtre vivait dans
`OnnxPlateDetector`, donc derrière `ultralytics`, donc jamais traversé par une CI
qui tourne sans GPU, sans poids et sans ultralytics. Le cas qui a motivé l'ADR
0008 — une boîte « véhicule entier » à 0,87 de confiance, inatteignable par un
seuil — n'était vérifié par rien.

Les chiffres rejoués ici sont ceux de la mesure : sur 538 détections réelles, 112
étaient la boîte du véhicule entier, et les 426 restantes de vraies plaques. Une
plaque occupe 11 à 25 % de la largeur de son véhicule, une fausse détection 98 à
100 % — c'est cette séparation que les tests verrouillent, sans un seul pixel.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.domain.models import BoundingBox
from traffic_analysis.features.counting.domain.plate_geometry import (
    PlateGeometry,
    is_plausible,
    select_best,
)

#: Un recadrage de véhicule typique sur un plan 1920×1080.
CROP_WIDTH = 240.0
CROP_HEIGHT = 180.0

GEOMETRY = PlateGeometry()


def _plate(
    *, x: float = 90.0, y: float = 130.0, width: float = 50.0, height: float = 12.0
) -> BoundingBox:
    """Une plaque plausible par défaut : 21 % de la largeur, dans le bas du véhicule."""
    return BoundingBox(x=x, y=y, width=width, height=height)


class TestBoitesRejetees:
    def test_la_boite_du_vehicule_entier_est_rejetee_malgre_une_confiance_elevee(self) -> None:
        """**Le cas d'ADR 0008.** 112 détections sur 538, certaines à 0,87.

        Aucun seuil de confiance ne les attrape — c'est tout l'intérêt du filtre :
        la confiance dit « le modèle est sûr », la géométrie dit « de quoi ». Sans
        lui, ces boîtes partaient à l'OCR, qui y lisait le lettrage de carrosserie.
        """
        entier = BoundingBox(x=0.0, y=0.0, width=CROP_WIDTH, height=CROP_HEIGHT)

        assert not is_plausible(entier, CROP_WIDTH, CROP_HEIGHT, GEOMETRY)

    def test_un_ecusson_est_trop_petit(self) -> None:
        # 2 % de la largeur : sous `min_relative_width`.
        assert not is_plausible(_plate(width=4.0, height=3.0), CROP_WIDTH, CROP_HEIGHT, GEOMETRY)

    def test_un_phare_carre_est_rejete_par_son_rapport(self) -> None:
        # 1,05:1 — sous `min_aspect`. Un logo ou un reflet, pas une plaque.
        assert not is_plausible(_plate(width=21.0, height=20.0), CROP_WIDTH, CROP_HEIGHT, GEOMETRY)

    def test_un_bandeau_de_calandre_est_rejete_par_son_rapport(self) -> None:
        # 10:1 — au-dessus de `max_aspect`.
        assert not is_plausible(_plate(width=100.0, height=10.0), CROP_WIDTH, CROP_HEIGHT, GEOMETRY)

    def test_un_reflet_de_pare_brise_est_trop_haut_dans_le_vehicule(self) -> None:
        """`min_vertical_centre` écarte le haut du véhicule : pare-brise, feux de toit."""
        assert not is_plausible(_plate(y=2.0, height=12.0), CROP_WIDTH, CROP_HEIGHT, GEOMETRY)

    def test_une_boite_couvrant_un_demi_vehicule_en_hauteur_est_rejetee(self) -> None:
        assert not is_plausible(
            _plate(y=80.0, width=50.0, height=95.0), CROP_WIDTH, CROP_HEIGHT, GEOMETRY
        )

    @pytest.mark.parametrize(
        ("width", "height"),
        [(0.0, 12.0), (50.0, 0.0), (-5.0, 12.0)],
        ids=["largeur nulle", "hauteur nulle", "largeur négative"],
    )
    def test_une_boite_degeneree_est_rejetee_sans_lever(self, width: float, height: float) -> None:
        """Rejetée plutôt que source d'une division par zéro : la passe ANPR est une
        option, elle ne doit jamais faire échouer un comptage."""
        assert not is_plausible(
            BoundingBox(x=90.0, y=130.0, width=width, height=height),
            CROP_WIDTH,
            CROP_HEIGHT,
            GEOMETRY,
        )

    def test_un_recadrage_degenere_est_rejete_sans_lever(self) -> None:
        assert not is_plausible(_plate(), 0.0, CROP_HEIGHT, GEOMETRY)


class TestBoitesGardees:
    @pytest.mark.parametrize("fraction", [0.11, 0.15, 0.20, 0.25])
    def test_une_plaque_de_11_a_25_pourcent_de_largeur_est_gardee(self, fraction: float) -> None:
        """L'intervalle **mesuré** sur de la vraie circulation.

        C'est la borne haute qui compte : à 25 % on garde, à 98 % on rejette, et
        aucune détection réelle ne s'est jamais trouvée entre les deux.
        """
        width = fraction * CROP_WIDTH

        assert is_plausible(
            _plate(width=width, height=width / 4.5), CROP_WIDTH, CROP_HEIGHT, GEOMETRY
        )

    def test_une_plaque_de_moto_a_1_4_pour_1_est_gardee(self) -> None:
        """**Le cas que `min_aspect` a été baissé pour accepter.** Une plaque de moto
        est presque carrée ; un seuil à 2:1 les supprimerait toutes."""
        assert is_plausible(_plate(width=28.0, height=20.0), CROP_WIDTH, CROP_HEIGHT, GEOMETRY)

    def test_une_plaque_de_camion_vu_en_plongee_reste_gardee(self) -> None:
        """`min_vertical_centre` est large **délibérément** : le resserrer gagnerait
        un peu de précision et perdrait les camions en plongée."""
        assert is_plausible(_plate(y=25.0, height=10.0), CROP_WIDTH, CROP_HEIGHT, GEOMETRY)


class TestSelection:
    def test_la_meilleure_est_retenue_et_max_per_vehicle_respecte(self) -> None:
        candidates = [
            (_plate(x=10.0), 0.40),
            (_plate(x=90.0), 0.91),
            (_plate(x=150.0), 0.65),
        ]

        best = select_best(candidates, PlateGeometry())

        assert len(best) == 1
        assert best[0][1] == 0.91

    def test_max_per_vehicle_superieur_garde_le_bon_ordre(self) -> None:
        candidates = [(_plate(x=10.0), 0.40), (_plate(x=90.0), 0.91), (_plate(x=150.0), 0.65)]

        best = select_best(candidates, PlateGeometry(max_per_vehicle=2))

        assert [score for _, score in best] == [0.91, 0.65]

    def test_deux_scores_egaux_gardent_leur_ordre_d_arrivee(self) -> None:
        """**Le tri doit être stable.** Un tri instable ferait publier une plaque
        différente d'une relecture à l'autre du même clip, ce que l'invariant 4
        existe précisément pour empêcher."""
        premiere = _plate(x=10.0)
        seconde = _plate(x=90.0)

        best = select_best([(premiere, 0.80), (seconde, 0.80)], PlateGeometry())

        assert best[0][0] is premiere

    def test_aucune_candidate_rend_un_tuple_vide(self) -> None:
        assert select_best([], PlateGeometry()) == ()
