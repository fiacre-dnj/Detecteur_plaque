"""Estimation de vitesse par identité — prompt/03 §6.

Le test le plus important est `test_sans_echelle_la_conversion_rend_none` :
convertir des pixels par seconde en kilomètres par heure sans échelle fournie par
l'utilisateur serait une **invention**. Un chiffre inventé dans un rapport de
comptage est pire qu'une case vide.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.speed import SpeedEstimator, to_kmh


class TestObservation:
    def test_la_premiere_observation_ne_donne_pas_de_vitesse(self) -> None:
        """Une seule position ne décrit aucun déplacement.

        Rendre `0.0` serait un mensonge : un véhicule à l'arrêt et un véhicule
        qu'on vient de voir seraient indiscernables.
        """
        estimator = SpeedEstimator()

        assert estimator.observe(1, Point(0.0, 0.0), 0.0) is None

    def test_une_vitesse_constante_est_mesuree_correctement(self) -> None:
        """100 px en 1000 ms de scène = 100 px/s.

        Le lissage exponentiel converge vers la valeur réelle : on laisse passer
        assez d'observations pour le vérifier.
        """
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)
        for step in range(1, 40):
            speed = estimator.observe(1, Point(step * 100.0, 0.0), step * 1000.0)

        assert speed == pytest.approx(100.0, rel=0.01)

    def test_le_lissage_amortit_un_tremblement_d_un_pixel(self) -> None:
        """Une boîte qui vacille ne doit pas faire osciller la vitesse affichée.

        Sans lissage, un tremblement d'un pixel entre deux frames à 40 ms produit
        une pointe de 25 px/s sur un véhicule immobile.
        """
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)
        estimator.observe(1, Point(0.0, 0.0), 40.0)
        estimator.observe(1, Point(0.0, 0.0), 80.0)

        avec_tremblement = estimator.observe(1, Point(1.0, 0.0), 120.0)

        assert avec_tremblement is not None
        # La pointe brute serait de 25 px/s ; le lissage la ramène très en dessous.
        assert avec_tremblement < 10.0

    def test_deux_identites_ne_se_melangent_pas(self) -> None:
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)
        estimator.observe(2, Point(1000.0, 1000.0), 0.0)

        lente = estimator.observe(1, Point(10.0, 0.0), 1000.0)
        rapide = estimator.observe(2, Point(1500.0, 1000.0), 1000.0)

        assert lente is not None
        assert rapide is not None
        assert rapide > lente * 10


class TestTrouDeScene:
    def test_un_trou_de_plus_d_une_seconde_reamorce_sans_integrer(self) -> None:
        """Une occlusion ne décrit pas un déplacement continu.

        Le véhicule a peut-être tourné, ralenti, ou été confondu avec un autre.
        Intégrer la distance parcourue pendant le trou inventerait une
        trajectoire rectiligne qui n'a pas été observée.
        """
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)

        apres_le_trou = estimator.observe(1, Point(5000.0, 0.0), 3000.0)

        assert apres_le_trou is None

    def test_apres_un_reamorcage_la_mesure_reprend(self) -> None:
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)
        estimator.observe(1, Point(5000.0, 0.0), 3000.0)  # trou → ré-amorçage

        reprise = estimator.observe(1, Point(5100.0, 0.0), 4000.0)

        assert reprise == pytest.approx(100.0, rel=0.5)

    def test_le_trou_n_est_pas_integre_a_la_moyenne(self) -> None:
        """La moyenne du registre ne doit pas hériter du saut.

        Sinon un véhicule occulté une fois affiche une vitesse moyenne
        spectaculaire dans le registre, et le lecteur croit à un bug de mesure.
        """
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)
        estimator.observe(1, Point(100.0, 0.0), 1000.0)
        estimator.observe(1, Point(9000.0, 0.0), 5000.0)  # trou de 4 s
        estimator.observe(1, Point(9100.0, 0.0), 6000.0)

        moyenne = estimator.average_px_s(1)

        assert moyenne is not None
        assert moyenne == pytest.approx(100.0, rel=0.1)


class TestMoyenne:
    def test_la_moyenne_est_la_distance_totale_sur_la_duree_totale(self) -> None:
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)
        estimator.observe(1, Point(200.0, 0.0), 1000.0)  # 200 px/s
        estimator.observe(1, Point(200.0, 0.0), 2000.0)  # à l'arrêt

        assert estimator.average_px_s(1) == pytest.approx(100.0)

    def test_une_identite_inconnue_n_a_pas_de_moyenne(self) -> None:
        assert SpeedEstimator().average_px_s(999) is None

    def test_une_identite_vue_une_seule_fois_n_a_pas_de_moyenne(self) -> None:
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 0.0), 0.0)

        assert estimator.average_px_s(1) is None


class TestConversionEnKmH:
    def test_sans_echelle_la_conversion_rend_none(self) -> None:
        """Honnêteté avant tout.

        Sans échelle px/m fournie par l'utilisateur, la vitesse reste en pixels
        par seconde. La convertir serait inventer une distance réelle.
        """
        assert to_kmh(100.0, None) is None

    def test_une_echelle_nulle_ou_negative_est_refusee(self) -> None:
        """Un slider laissé à 0 signifie « non définie », pas « 0 pixel par mètre »."""
        assert to_kmh(100.0, 0.0) is None
        assert to_kmh(100.0, -5.0) is None

    def test_avec_une_echelle_la_conversion_est_exacte(self) -> None:
        # 50 px/s à 10 px/m = 5 m/s = 18 km/h.
        assert to_kmh(50.0, 10.0) == pytest.approx(18.0)

    def test_une_vitesse_absente_reste_absente(self) -> None:
        assert to_kmh(None, 10.0) is None
