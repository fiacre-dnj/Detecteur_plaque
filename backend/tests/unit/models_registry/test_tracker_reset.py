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

from typing import TYPE_CHECKING, Any

import yaml

from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    reset_trackers,
)

if TYPE_CHECKING:
    from pathlib import Path


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


# ── Le seuil de la requête, reposé sur un tracker déjà construit ──────────────
#
# **Deuxième panne silencieuse de la même sortie anticipée d'Ultralytics.**
# `register_tracker` ne relit le fichier de suivi à aucun moment une fois ses
# trackers en place, donc le `tracker=…` passé à `track()` est ignoré. Or c'est là
# que voyage « Confiance véhicules » (`track_high_thresh` / `new_track_thresh`,
# ADR 0024) : toutes les analyses d'un processus tournaient au seuil de la
# **première**. Le curseur bougeait, le fichier dérivé était écrit, son chemin
# journalisé, et aucun chiffre ne changeait.


class _Args:
    """Le `IterableSimpleNamespace` d'Ultralytics, réduit à ce qui nous concerne."""

    def __init__(self, high: float) -> None:
        self.track_high_thresh = high
        self.new_track_thresh = high
        self.track_low_thresh = 0.1
        self.gmc_method = "none"


class _ConfiguredTracker(_Tracker):
    def __init__(self, high: float) -> None:
        super().__init__()
        self.args = _Args(high)


def _tracker_file(tmp_path: Path, high: float) -> Path:
    path = tmp_path / f"botsort-hi-{high:.2f}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "tracker_type": "botsort",
                "track_high_thresh": high,
                "new_track_thresh": high,
                "track_low_thresh": 0.1,
                "gmc_method": "none",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_le_seuil_du_fichier_est_repose_sur_un_tracker_deja_construit(tmp_path: Path) -> None:
    """**Le test de la panne.** Analyse 1 à 0,35, analyse 2 à 0,60.

    Sans ce report, la seconde compterait avec le seuil de la première — et rien à
    l'écran, dans les journaux ou dans les chiffres ne le dirait.
    """
    tracker = _ConfiguredTracker(0.35)

    reset_trackers(_Model(_Predictor([tracker])), _tracker_file(tmp_path, 0.60))

    assert tracker.args.track_high_thresh == 0.60
    assert tracker.args.new_track_thresh == 0.60


def test_le_report_precede_aucune_remise_a_zero_perdue(tmp_path: Path) -> None:
    """Reposer le seuil ne remplace pas le nettoyage d'état : les deux ont lieu."""
    tracker = _ConfiguredTracker(0.35)

    reset_trackers(_Model(_Predictor([tracker])), _tracker_file(tmp_path, 0.60))

    assert tracker.resets == 1


def test_sans_fichier_rien_n_est_repose() -> None:
    """L'appelant qui n'a que l'état à nettoyer garde exactement l'ancien comportement."""
    tracker = _ConfiguredTracker(0.35)

    reset_trackers(_Model(_Predictor([tracker])))

    assert tracker.args.track_high_thresh == 0.35


def test_un_tracker_sans_arguments_ne_leve_pas(tmp_path: Path) -> None:
    """Une forme inattendue rend le comportement d'avant le correctif, jamais un échec.

    Un comptage ne doit pas tomber parce qu'Ultralytics a changé la forme de ses
    trackers : on renonce au report, on le journalise, et l'analyse continue.
    """
    reset_trackers(_Model(_Predictor([_Tracker()])), _tracker_file(tmp_path, 0.60))


def test_un_modele_neuf_avec_un_fichier_ne_leve_pas(tmp_path: Path) -> None:
    """Premier appel du processus : Ultralytics lira le fichier lui-même.

    C'est le seul cas où il le lit, et c'est pour cela que la panne ne se voyait
    jamais sur la première analyse — celle qu'on regarde en développement.
    """
    reset_trackers(_Model(), _tracker_file(tmp_path, 0.60))
