"""Le vocabulaire du domaine, et surtout `snapshot()`.

`test_snapshot_ne_partage_rien_avec_l_original` est une non-régression : sans
`snapshot()`, chaque ligne de la timeline afficherait l'état **final** des
véhicules, et la relecture montrerait les boîtes immobiles à leur position de
sortie pendant tout le clip.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.domain.geometry import Point
from traffic_analysis.features.counting.domain.models import (
    VEHICLE_CLASS_IDS,
    BoundingBox,
    PlateDetection,
    SessionTrack,
    VideoInfo,
)


def _track() -> SessionTrack:
    box = BoundingBox(100.0, 200.0, 80.0, 60.0)
    return SessionTrack(
        track_id=3,
        class_id=2,
        label="car",
        score=0.87,
        box=box,
        centroid=box.centroid,
    )


class TestBoundingBox:
    def test_le_centroide_est_le_centre_de_la_boite(self) -> None:
        assert BoundingBox(100.0, 200.0, 80.0, 60.0).centroid == Point(140.0, 230.0)

    def test_une_boite_de_taille_nulle_a_un_centroide_defini(self) -> None:
        """Une détection dégénérée ne doit pas faire lever le comptage."""
        assert BoundingBox(50.0, 50.0, 0.0, 0.0).centroid == Point(50.0, 50.0)

    def test_l_aire(self) -> None:
        assert BoundingBox(0.0, 0.0, 4.0, 5.0).area == 20.0


class TestSessionTrackSnapshot:
    def test_le_snapshot_reproduit_l_etat_courant(self) -> None:
        track = _track()
        track.hits = 5
        track.global_id = 7
        track.identity_label = "truck"
        track.counted = True
        track.speed_px_s = 412.5

        copy = track.snapshot()

        assert copy.hits == 5
        assert copy.global_id == 7
        assert copy.identity_label == "truck"
        assert copy.counted is True
        assert copy.speed_px_s == 412.5

    def test_snapshot_ne_partage_rien_avec_l_original(self) -> None:
        """LE test de non-régression du piège d'aliasing de la timeline.

        La session mute la même instance d'une frame à l'autre. Si le snapshot
        partageait l'état, faire avancer la piste modifierait rétroactivement
        toutes les frames déjà enregistrées.
        """
        track = _track()
        track.hits = 1
        frame_zero = track.snapshot()

        # La session fait avancer la piste, comme à la frame suivante.
        track.box = BoundingBox(900.0, 900.0, 80.0, 60.0)
        track.centroid = track.box.centroid
        track.hits = 42
        track.counted = True

        assert frame_zero.hits == 1
        assert frame_zero.counted is False
        assert frame_zero.centroid == Point(140.0, 230.0)

    def test_la_liste_de_plaques_est_copiee_et_non_partagee(self) -> None:
        """Le même bug, un niveau plus bas.

        Partager la liste ferait apparaître dans la frame 0 une plaque détectée à
        la frame 300.
        """
        track = _track()
        track.plates.append(PlateDetection(BoundingBox(1.0, 1.0, 10.0, 5.0), 0.71))

        copy = track.snapshot()
        track.plates.append(PlateDetection(BoundingBox(2.0, 2.0, 10.0, 5.0), 0.42))

        assert len(copy.plates) == 1
        assert len(track.plates) == 2


class TestCountingLabel:
    def test_le_vote_de_la_galerie_gagne_sur_la_lecture_de_la_frame(self) -> None:
        """Un véhicule est compté sous la classe qu'il a eue le plus souvent.

        Sinon une camionnette lue « car » sur une image et « truck » sur la
        suivante changerait de compteur au gré des frames.
        """
        track = _track()
        track.label = "car"
        track.identity_label = "truck"

        assert track.counting_label == "truck"

    def test_sans_vote_la_lecture_courante_sert_de_repli(self) -> None:
        """Les premières frames d'une piste, avant que la galerie ait tranché."""
        track = _track()
        track.identity_label = ""

        assert track.counting_label == "car"


class TestVideoInfo:
    def test_la_duree_en_millisecondes_de_scene(self) -> None:
        assert VideoInfo(1920, 1080, 25.0, 750).duration_ms == pytest.approx(30_000.0)

    def test_un_fps_nul_ne_fait_pas_lever(self) -> None:
        """Un conteneur mal formé annonce parfois 0 image par seconde.

        Une durée inconnue n'empêche pas de compter : rendre 0 plutôt que lever.
        """
        assert VideoInfo(1920, 1080, 0.0, 750).duration_ms == 0.0

    def test_la_diagonale_sert_de_reference_au_gate_de_deplacement(self) -> None:
        assert VideoInfo(1920, 1080, 25.0, 1).diagonal == pytest.approx(2202.9, abs=0.1)


def test_les_quatre_classes_comptees_sont_les_classes_coco_attendues() -> None:
    """car (2), motorcycle (3), bus (5), truck (7) — traitées à l'identique.

    Le tuple est passé tel quel à `model.track(classes=…)` : une valeur erronée
    ferait compter des personnes ou ignorer les camions, sans aucune erreur.
    """
    assert VEHICLE_CLASS_IDS == (2, 3, 5, 7)
