"""Où l'adaptateur se déplace quand l'analyse est bornée à un début.

Le déplacement lui-même reste hors de portée de la CI — il demande OpenCV, un
vrai fichier et des poids. Ce qui **est** testable, et ce qui compte, est le
calcul de l'index d'arrivée : il doit rendre exactement la première image que
`AnalysisService` aurait gardée, ni une de plus, ni une de moins.

Se tromper d'un cran ne lève rien, et c'est tout le problème. Trop bas,
l'application rejette les premières images décodées : du travail perdu, invisible.
Trop haut, la fenêtre perd une image que l'utilisateur avait demandée, et personne
ne le saura jamais — surtout pas sur une image où il ne se passait rien.

Le test se lit donc en miroir du filtre de l'application : `timestamp_ms >=
start_ms`, avec `timestamp_ms = index / fps × 1000`, restreint aux index
multiples du pas d'analyse.
"""

from __future__ import annotations

from math import ceil

import pytest

from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    _first_analysed_index,
)


def _premier_index_garde_par_l_application(start_ms: float, fps: float, stride: int) -> int:
    """Le filtre d'`AnalysisService`, réécrit ici en toutes lettres.

    Une réimplémentation naïve et volontairement lente : elle décrit la règle, là
    où la fonction testée la calcule. Les deux doivent tomber d'accord.
    """
    for ordinal in range(10_000):
        index = ordinal * stride
        if index / fps * 1000.0 >= start_ms:
            return index
    raise AssertionError("aucune image ne satisfait la borne")


def test_sans_borne_on_part_de_zero() -> None:
    """Le chemin ordinaire garde le chargeur d'Ultralytics : `0` le lui rend."""
    assert _first_analysed_index(0.0, 25.0, 1) == 0


def test_une_cadence_inconnue_desactive_le_deplacement() -> None:
    """Sans cadence, un temps ne se traduit en aucun index.

    Se déplacer « au jugé » vaudrait pire que ne pas se déplacer : les
    horodatages suivraient l'index atteint, donc seraient faux, sans que rien ne
    le signale. L'application, elle, tranchera la fenêtre sur les horodatages.
    """
    assert _first_analysed_index(5_000.0, 0.0, 1) == 0


def test_une_borne_pile_sur_une_image_tombe_sur_cette_image() -> None:
    """À 25 img/s, 200 ms est exactement l'image 5 — pas la 6."""
    assert _first_analysed_index(200.0, 25.0, 1) == 5


def test_une_borne_entre_deux_images_prend_la_suivante() -> None:
    """La règle est `>=` : une image antérieure à la borne n'est pas dans la fenêtre."""
    assert _first_analysed_index(201.0, 25.0, 1) == 6


def test_l_index_est_aligne_sur_le_pas_d_analyse() -> None:
    """Seuls les multiples du pas existent : on remonte au suivant, jamais au précédent.

    Redescendre au multiple inférieur analyserait une image d'avant la borne — un
    véhicule qui passe juste avant le début demandé serait compté.
    """
    assert _first_analysed_index(200.0, 25.0, 3) == 6
    assert _first_analysed_index(240.0, 25.0, 3) == 6
    assert _first_analysed_index(280.0, 25.0, 3) == 9


@pytest.mark.parametrize("fps", [23.976, 25.0, 29.97, 30.0, 60.0])
@pytest.mark.parametrize("stride", [1, 2, 3, 5])
@pytest.mark.parametrize("start_ms", [1.0, 40.0, 333.0, 1_000.0, 34_000.0])
def test_l_adaptateur_et_l_application_choisissent_la_meme_image(
    fps: float, stride: int, start_ms: float
) -> None:
    """La propriété qui compte, sur les cadences réelles du terrain.

    `23.976` et `29.97` sont là exprès : ce sont elles qui produisent des
    horodatages non ronds, donc les arrondis où un `int()` au lieu d'un `ceil()`
    se serait glissé sans conséquence visible.
    """
    assert _first_analysed_index(start_ms, fps, stride) == _premier_index_garde_par_l_application(
        start_ms, fps, stride
    )


def test_le_calcul_est_un_plafond_et_non_un_arrondi() -> None:
    """Un cas nommé pour la régression exacte qu'on redoute.

    À 29,97 img/s, 1 000 ms tombe entre les images 29 et 30 : `int()` rendrait 29,
    donc une image **avant** la borne demandée.
    """
    assert 29 < 1_000.0 * 29.97 / 1000.0 < 30
    assert _first_analysed_index(1_000.0, 29.97, 1) == ceil(29.97) == 30
