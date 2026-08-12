"""Une analyse repart d'un suivi vierge — sinon elle hérite de la précédente.

**Le bug que ces tests verrouillent ne lève rien et ne se voit qu'en comptant.**

`persist=True` fait d'une suite d'images un flux, ce qu'on veut *à l'intérieur*
d'une vidéo. Mais Ultralytics l'interprète aussi **entre deux appels** :
`register_tracker` sort immédiatement quand des trackers existent déjà. Or le
registre garde l'instance de modèle d'un job à l'autre — c'est tout l'intérêt de
la résidence mémoire. La deuxième analyse héritait donc des pistes, du filtre de
Kalman et du compteur d'images de la première.

Mesuré sur un même fichier **octet pour octet**, analysé trois fois de suite dans
le même processus : 19, puis 26, puis 33 véhicules uniques. Parfaitement
reproductible d'une exécution à l'autre — ce n'était donc pas du bruit, mais une
dérive, et elle allait toujours dans le même sens.

Ces tests n'importent pas ultralytics : `reset_trackers` est écrite pour un objet
au canard typé, et c'est ce qui la rend vérifiable ici. La CI tourne sans GPU,
sans poids et sans ultralytics.
"""

from __future__ import annotations

from typing import Any

from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    reset_trackers,
)


class _Tracker:
    """Un tracker qui note qu'on l'a remis à zéro."""

    def __init__(self) -> None:
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1


class _Predictor:
    def __init__(self, trackers: list[_Tracker]) -> None:
        self.trackers = trackers


class _Model:
    def __init__(self, predictor: Any = None) -> None:  # noqa: ANN401
        if predictor is not None:
            self.predictor = predictor


def test_chaque_tracker_est_remis_a_zero() -> None:
    """Le cas qui compte : une instance de modèle déjà utilisée par une analyse."""
    trackers = [_Tracker(), _Tracker()]

    reset_trackers(_Model(_Predictor(trackers)))

    assert [tracker.resets for tracker in trackers] == [1, 1]


def test_un_modele_jamais_utilise_ne_leve_pas() -> None:
    """Au premier appel du processus, il n'y a pas encore de prédicteur.

    Ce n'est pas une anomalie : c'est l'état normal d'un modèle fraîchement
    chargé. Lever ici ferait échouer la toute première analyse après un
    démarrage — c'est-à-dire exactement le cas qui n'a aucun état à nettoyer.
    """
    reset_trackers(_Model())


def test_un_predicteur_sans_tracker_ne_leve_pas() -> None:
    """Un prédicteur existe dès la première prédiction, ses trackers non.

    `predict()` sans `track()` laisse un prédicteur nu. Le rencontrer est normal
    et ne demande aucun nettoyage.
    """

    class _Bare:
        pass

    reset_trackers(_Model(_Bare()))


def test_une_liste_de_trackers_vide_ne_leve_pas() -> None:
    reset_trackers(_Model(_Predictor([])))
