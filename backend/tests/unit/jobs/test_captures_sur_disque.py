"""Les captures sur disque : où elles vivent, et surtout **quand elles meurent**.

Le test qui compte ici est celui de la purge. `delete_input` existe parce que « la
vidéo est la donnée la plus lourde **et la plus sensible** — une scène de trafic
contient des plaques réelles et des visages » : elle a donc un TTL plus court que le
résultat.

Un recadrage sur une voiture et sa plaque est exactement cette donnée-là, en plus
concentré. Le laisser survivre à la vidéo dont il est extrait inverserait la règle
que ce TTL existe pour appliquer — sans qu'aucun test ne tombe, et sans que rien ne
se voie à l'écran.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from traffic_analysis.features.counting.application.dto import VehicleSnapshot
from traffic_analysis.features.jobs.infrastructure.result_store import (
    SNAPSHOT_DIRNAME,
    FileResultStore,
)

if TYPE_CHECKING:
    from pathlib import Path

JOB = "0123456789abcdef0123456789abcdef"
SNAPSHOTS = {
    7: VehicleSnapshot(vehicle_jpeg=b"voiture-7", plate_jpeg=b"plaque-7"),
    12: VehicleSnapshot(vehicle_jpeg=b"voiture-12", plate_jpeg=b"plaque-12"),
}


def _store(tmp_path: Path) -> FileResultStore:
    return FileResultStore(tmp_path)


class TestEcriture:
    def test_deux_fichiers_par_vehicule(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        assert store.write_snapshots(JOB, SNAPSHOTS) == 4

        directory = tmp_path / "jobs" / JOB / SNAPSHOT_DIRNAME
        assert sorted(path.name for path in directory.iterdir()) == [
            "12-plate.jpg",
            "12-vehicle.jpg",
            "7-plate.jpg",
            "7-vehicle.jpg",
        ]

    def test_les_octets_sont_rendus_tels_quels(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write_snapshots(JOB, SNAPSHOTS)

        vehicle = store.snapshot_path_for(JOB, 7, "vehicle")
        plate = store.snapshot_path_for(JOB, 7, "plate")

        assert vehicle is not None
        assert plate is not None
        assert vehicle.read_bytes() == b"voiture-7"
        assert plate.read_bytes() == b"plaque-7"

    def test_aucune_capture_n_ecrit_aucun_repertoire(self, tmp_path: Path) -> None:
        """Le cas courant : la plupart des analyses ne lisent aucune plaque.

        Créer un répertoire vide pour chacune polluerait le volume de données sans
        rien apporter.
        """
        store = _store(tmp_path)

        assert store.write_snapshots(JOB, {}) == 0
        assert not (tmp_path / "jobs" / JOB / SNAPSHOT_DIRNAME).exists()


class TestRelecture:
    def test_une_capture_absente_rend_none_sans_lever(self, tmp_path: Path) -> None:
        """`None` est un état **normal** : ce véhicule n'a peut-être jamais eu de photo.

        Lever ici obligerait chaque appelant à distinguer « pas de capture » d'une
        panne, alors que c'est le cas le plus fréquent.
        """
        store = _store(tmp_path)

        assert store.snapshot_path_for(JOB, 7, "vehicle") is None

    def test_un_job_inconnu_rend_none(self, tmp_path: Path) -> None:
        assert _store(tmp_path).snapshot_path_for("inexistant", 7, "plate") is None


class TestPurge:
    def test_la_purge_de_la_video_emporte_les_captures(self, tmp_path: Path) -> None:
        """**Le test de confidentialité.**

        Les captures suivent le TTL de la vidéo, pas celui du résultat : ce sont des
        plaques et des visages, la donnée même que ce TTL court efface.
        """
        store = _store(tmp_path)
        store.input_path(JOB, ".mp4").write_bytes(b"\x00" * 8)
        store.write_snapshots(JOB, SNAPSHOTS)
        store.write(JOB, {"jobId": JOB})

        assert store.delete_input(JOB) is True

        assert store.snapshot_path_for(JOB, 7, "vehicle") is None
        assert not (tmp_path / "jobs" / JOB / SNAPSHOT_DIRNAME).exists()
        # Le résultat, lui, reste : ses chiffres n'ont rien de sensible.
        assert store.path_for(JOB) is not None

    def test_la_purge_est_rejouable(self, tmp_path: Path) -> None:
        """Idempotence : un incident partiel ne doit pas bloquer la purge pour toujours."""
        store = _store(tmp_path)
        store.write_snapshots(JOB, SNAPSHOTS)

        assert store.delete_input(JOB) is True
        assert store.delete_input(JOB) is False

    def test_la_purge_du_job_emporte_tout(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write_snapshots(JOB, SNAPSHOTS)
        store.write(JOB, {"jobId": JOB})

        store.delete(JOB)

        assert not (tmp_path / "jobs" / JOB).exists()
