"""L'encodeur de captures OpenCV — le seul étage que la doublure ne traverse jamais.

Ces tests existent à cause d'une panne **mesurée sur le vrai moteur** : le plancher
d'existence d'un recadrage vaut 16 px dans `vehicle_crop`, parce que c'est celui d'une
entrée de réseau. Or une plaque localisée sur une vue de circulation réelle fait 27 à
88 px de large pour **9 à 28 px de haut** — donc `crop` rendait `None`, donc `encode`
refusait la capture **entière**, véhicule compris, exactement dans le cas qu'ADR 0051
existe pour servir. Rien ne levait, rien n'était journalisé, et l'analyse se terminait
sans une photo.

Aucune doublure ne pouvait le voir : `FakeSnapshotEncoder` rend des octets quelconques
sans regarder une seule dimension. C'est le quatrième exemplaire du défaut que
`CLAUDE.md` décrit — vert en CI, faux en production.
"""

from __future__ import annotations

import numpy as np
import pytest

from traffic_analysis.features.counting.domain.models import BoundingBox
from traffic_analysis.features.counting.infrastructure.opencv_snapshot_encoder import (
    MIN_PLATE_CROP_SIDE_PX,
    OpenCvSnapshotEncoder,
)


@pytest.fixture
def image() -> np.ndarray:
    """Une image 1080p, texturée : un aplat uni s'encode en JPEG dégénéré."""
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[:, :, 0] = np.tile(np.arange(1920, dtype=np.uint8), (1080, 1))
    frame[:, :, 1] = 128
    return frame


VEHICLE = BoundingBox(x=800.0, y=400.0, width=160.0, height=120.0)


class TestUnePlaqueBasseEstEncodable:
    def test_une_plaque_de_vue_de_circulation_donne_ses_deux_faces(self, image: np.ndarray) -> None:
        """27 × 9 px : les dimensions **mesurées** sur une vue réelle.

        Sous l'ancien plancher de 16 px, cette capture était refusée en entier — et
        c'est le cas dominant de la cause `plate_box`.
        """
        plate = BoundingBox(x=850.0, y=480.0, width=27.0, height=9.0)

        snapshot = OpenCvSnapshotEncoder().encode(image, VEHICLE, plate)

        assert snapshot is not None
        assert len(snapshot.vehicle_jpeg) > 0
        assert snapshot.plate_jpeg is not None
        assert len(snapshot.plate_jpeg) > 0

    def test_un_artefact_de_quelques_pixels_refuse_toute_la_capture(
        self, image: np.ndarray
    ) -> None:
        """6 × 3 px n'est pas une plaque, c'est du bruit du détecteur.

        Le refus **total** est voulu : il n'y a rien à montrer, donc pas de photo à
        garder. Et il ne peut pas mentir sur le contrat — une capture annoncée « plaque
        lue » sans plaque à montrer serait un écran qui se contredit.
        """
        plate = BoundingBox(x=850.0, y=480.0, width=6.0, height=3.0)

        assert OpenCvSnapshotEncoder().encode(image, VEHICLE, plate) is None

    def test_le_plancher_de_la_plaque_est_plus_bas_que_celui_du_vehicule(self) -> None:
        """Sinon la constante ne servirait à rien, et personne ne le verrait."""
        from traffic_analysis.features.counting.infrastructure.vehicle_crop import (
            MIN_CROP_SIDE_PX,
        )

        assert MIN_PLATE_CROP_SIDE_PX < MIN_CROP_SIDE_PX


class TestUneCaptureSansPlaque:
    def test_sans_boite_de_plaque_la_capture_n_a_qu_une_face(self, image: np.ndarray) -> None:
        """Le cas d'une photo retenue pour la ressemblance du véhicule (ADR 0051)."""
        snapshot = OpenCvSnapshotEncoder().encode(image, VEHICLE, None)

        assert snapshot is not None
        assert len(snapshot.vehicle_jpeg) > 0
        assert snapshot.plate_jpeg is None

    def test_un_vehicule_hors_champ_refuse_sans_lever(self, image: np.ndarray) -> None:
        """« Ne lève jamais » : `None` est un refus honnête, pas une exception."""
        outside = BoundingBox(x=5000.0, y=5000.0, width=160.0, height=120.0)

        assert OpenCvSnapshotEncoder().encode(image, outside, None) is None
