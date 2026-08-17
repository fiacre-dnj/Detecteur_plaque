"""L'échelle pixels/mètre locale, et la vitesse en km/h qu'elle rend mesurable.

Le cas qui justifie le module : une caméra inclinée. Un mètre y vaut quelques
pixels au fond de l'image et quelques dizaines au premier plan, donc une échelle
unique est juste à une profondeur et fausse partout ailleurs.

Le test qui compte le plus est le dernier : **sans ligne calibrée, rien ne
change**. C'est lui qui garantit qu'une configuration existante rend exactement
les mêmes chiffres qu'avant.
"""

from __future__ import annotations

from tests.support.builders import make_line
from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import CountingLineDef
from traffic_analysis.features.counting.domain.scale_field import ScaleField
from traffic_analysis.features.counting.domain.speed import SpeedEstimator, to_kmh


def calibrated(
    line_id: str, *, a: tuple[float, float], b: tuple[float, float], metres: float
) -> CountingLineDef:
    """Une ligne portant sa longueur réelle."""
    return CountingLineDef(
        id=line_id,
        name=f"Ligne {line_id}",
        a=Point(*a),
        b=Point(*b),
        length_m=metres,
    )


class TestEchelleDUneLigne:
    def test_l_echelle_est_le_rapport_pixels_sur_metres(self) -> None:
        # 400 px de long pour 8 m de large : 50 px/m à cette profondeur.
        line = calibrated("l1", a=(100.0, 500.0), b=(500.0, 500.0), metres=8.0)
        assert line.px_per_meter() == 50.0

    def test_une_ligne_sans_longueur_n_echantillonne_rien(self) -> None:
        assert make_line("l1").px_per_meter() is None

    def test_une_longueur_absurde_ne_produit_pas_d_infini(self) -> None:
        """Un trait dégénéré rendrait `inf`, qui s'affiche comme un chiffre."""
        degenerate = calibrated("l1", a=(10.0, 10.0), b=(10.0, 10.0), metres=5.0)
        assert degenerate.px_per_meter() is None


class TestChampDEchelle:
    def test_la_ligne_la_plus_proche_gouverne(self) -> None:
        """Le gradient de perspective, échantillonné par deux lignes.

        Au fond de l'image (y=200) un mètre vaut 10 px ; au premier plan (y=900)
        il en vaut 50. Un point proche de l'une doit prendre **son** échelle, pas
        une moyenne des deux : entre les deux traits, personne n'a mesuré quoi que
        ce soit.
        """
        loin = calibrated("fond", a=(0.0, 200.0), b=(100.0, 200.0), metres=10.0)
        pres = calibrated("proche", a=(0.0, 900.0), b=(500.0, 900.0), metres=10.0)
        field = ScaleField((loin, pres))

        assert field.px_per_meter_at(Point(50.0, 210.0)) == 10.0
        assert field.px_per_meter_at(Point(50.0, 890.0)) == 50.0

    def test_la_distance_est_mesuree_au_segment_pas_a_la_droite(self) -> None:
        """Une ligne dont on s'est éloigné le long de son prolongement est loin.

        Même distinction que `segments_intersect` face à `side_of_line`, et pour
        la même raison : la droite support déborde très au-delà du trait dessiné.
        """
        courte = calibrated("courte", a=(0.0, 500.0), b=(50.0, 500.0), metres=5.0)
        longue = calibrated("longue", a=(0.0, 900.0), b=(1000.0, 900.0), metres=10.0)
        field = ScaleField((courte, longue))

        # x=900 est très au-delà de l'extrémité de « courte » (qui s'arrête à 50)
        # mais pile sur « longue » : c'est cette dernière qui doit gouverner.
        assert field.px_per_meter_at(Point(900.0, 890.0)) == 100.0

    def test_la_mesure_locale_l_emporte_sur_l_echelle_globale(self) -> None:
        """Sinon, calibrer une ligne ne changerait rien tant que le curseur est posé."""
        line = calibrated("l1", a=(0.0, 500.0), b=(400.0, 500.0), metres=8.0)
        field = ScaleField((line,), global_px_per_meter=12.0)

        assert field.px_per_meter_at(Point(200.0, 500.0)) == 50.0

    def test_sans_ligne_calibree_le_champ_rend_l_echelle_globale(self) -> None:
        """**Le test de non-régression.** Une configuration existante est intacte."""
        field = ScaleField((make_line("l1"),), global_px_per_meter=12.0)

        assert not field.is_calibrated
        assert field.px_per_meter_at(Point(10.0, 10.0)) == 12.0

    def test_sans_rien_du_tout_le_champ_se_tait(self) -> None:
        field = ScaleField(())
        assert field.px_per_meter_at(Point(10.0, 10.0)) is None


class TestVitesseMesuree:
    def test_la_vitesse_en_kmh_suit_l_echelle_locale(self) -> None:
        """36 km/h = 10 m/s. À 50 px/m, cela fait 500 px/s."""
        line = calibrated("l1", a=(0.0, 500.0), b=(400.0, 500.0), metres=8.0)
        estimator = SpeedEstimator(ScaleField((line,)))

        # 500 px en 1 s, le long de la ligne : 10 m/s exactement.
        estimator.observe(1, Point(0.0, 500.0), 0.0)
        estimator.observe(1, Point(500.0, 500.0), 1000.0)

        kmh = estimator.average_kmh(1)
        assert kmh is not None
        assert abs(kmh - 36.0) < 0.01

    def test_deux_vehicules_a_deux_profondeurs_ne_partagent_pas_l_echelle(self) -> None:
        """**Ce que l'échelle unique ne sait pas faire.**

        Deux véhicules parcourent *exactement* la même distance en pixels — 100 px
        en 1 s — l'un au fond de l'image, l'autre au premier plan. En px/s ils sont
        identiques, et une échelle unique leur donnerait donc la même vitesse.

        Or au fond un mètre vaut 10 px et devant il en vaut 50 : le premier a
        réellement parcouru 10 m, le second 2 m. Le rapport de leurs vitesses doit
        être exactement le rapport des deux échelles, soit 5.
        """
        loin = calibrated("fond", a=(0.0, 100.0), b=(100.0, 100.0), metres=10.0)
        pres = calibrated("proche", a=(0.0, 900.0), b=(500.0, 900.0), metres=10.0)
        estimator = SpeedEstimator(ScaleField((loin, pres)))

        estimator.observe(1, Point(0.0, 100.0), 0.0)
        estimator.observe(1, Point(100.0, 100.0), 1000.0)
        estimator.observe(2, Point(0.0, 900.0), 0.0)
        estimator.observe(2, Point(100.0, 900.0), 1000.0)

        # Identiques en pixels : c'est bien la calibration, et rien d'autre, qui
        # les sépare.
        assert estimator.average_px_s(1) == estimator.average_px_s(2) == 100.0

        au_fond, devant = estimator.average_kmh(1), estimator.average_kmh(2)
        assert au_fond is not None and devant is not None
        assert abs(au_fond - 36.0) < 0.01, "100 px = 10 m en 1 s = 36 km/h"
        assert abs(devant - 7.2) < 0.01, "100 px = 2 m en 1 s = 7,2 km/h"
        assert abs(au_fond / devant - 5.0) < 1e-9

    def test_sans_calibration_la_vitesse_mesuree_se_tait(self) -> None:
        """Elle se tait **au lieu** de retomber en douce sur l'échelle globale.

        Le repli existe, mais il appartient à l'appelant (`tracking_session`), qui
        sait qu'il s'agit d'un repli. Le rendre ici masquerait la différence entre
        « mesuré » et « estimé depuis un curseur ».
        """
        estimator = SpeedEstimator(ScaleField((make_line("l1"),)))
        estimator.observe(1, Point(0.0, 500.0), 0.0)
        estimator.observe(1, Point(500.0, 500.0), 1000.0)

        assert estimator.average_kmh(1) is None
        assert estimator.average_px_s(1) == 500.0

    def test_l_estimateur_sans_champ_se_comporte_comme_avant(self) -> None:
        """**Le second test de non-régression** : aucun champ, aucun changement."""
        estimator = SpeedEstimator()
        estimator.observe(1, Point(0.0, 500.0), 0.0)
        estimator.observe(1, Point(500.0, 500.0), 1000.0)

        assert estimator.average_px_s(1) == 500.0
        assert estimator.average_kmh(1) is None
        assert to_kmh(estimator.average_px_s(1), 50.0) == 36.0
