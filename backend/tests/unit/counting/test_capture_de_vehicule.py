"""Une capture par véhicule, et c'est la meilleure lecture qui gagne.

La règle demandée tient en une phrase : à 0,80 on capture, à 0,90 on remplace, à
0,85 ensuite on ne touche plus à rien. Elle est **monotone stricte**, et ces tests
la verrouillent dans les deux sens — ce qui doit capturer, et surtout ce qui ne doit
**pas** déclencher d'encodage.

Le second point est le plus important : `FakeSnapshotEncoder.calls` compte les
encodages réellement demandés. C'est ce chiffre, et non le contenu du registre, qui
prouve que la règle protège le chemin critique. Un code qui encoderait à chaque image
puis jetterait le résultat rendrait exactement les mêmes captures, deux ordres de
grandeur plus cher — et aucun test portant seulement sur le résultat ne le verrait.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.support.builders import CAR, compose, make_line, straight_line, track_path
from tests.support.engine import (
    FakeEngine,
    FakePlateDetector,
    FakePlateReader,
    FakeSnapshotEncoder,
)
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    PlateDetectOptions,
    PlateOcrOptions,
)

#: Détection et lecture **à chaque image**, pour que la suite de confiances soit
#: consommée image par image et que le test reste déterministe.
#:
#: Les étranglements ont leurs propres tests ; les mêler à celui-ci ferait dépendre
#: le verdict de deux règles à la fois, et un échec ne dirait plus laquelle est en
#: cause.
EVERY_FRAME_OCR = PlateOcrOptions(
    every_n_frames=1,
    skip_above_iou=1.0,
    min_width_px=0.0,
    min_sharpness=0.0,
    stop_when_confident=False,
)
EVERY_FRAME_DETECT = PlateDetectOptions(
    every_n_frames=1, min_vehicle_width_px=0.0, readable_gate=False, stop_when_confident=False
)

if TYPE_CHECKING:
    from pathlib import Path

    from traffic_analysis.features.counting.application.dto import AnalysisResultData
    from traffic_analysis.features.counting.domain.models import TrackObservation

CONFIG = AnalysisJobConfig(
    model_id="yolov8n", lines=(make_line(),), detect_plates=True, read_plate_text=True
)


def _frames(steps: int = 6) -> list[list[TrackObservation]]:
    """Un véhicule qui traverse la ligne, sans se presser."""
    return compose(track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=steps)))


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 16)
    return path


def _run(
    video: Path,
    scores: list[float],
    *,
    read: bool = True,
    fails: bool = False,
    steps: int | None = None,
) -> tuple[AnalysisResultData, FakeSnapshotEncoder]:
    """Analyse un clip où l'OCR rend une confiance **différente à chaque image**.

    `scores` est consommé image par image : c'est ce qui permet d'écrire la
    progression 0,80 → 0,90 → 0,85 telle que l'utilisateur l'a décrite.
    """
    remaining = list(scores)

    def next_score() -> float:
        return remaining.pop(0) if remaining else 0.0

    encoder = FakeSnapshotEncoder(fails=fails)
    service = AnalysisService(
        # Deux images de plus que de confiances : la piste doit être **confirmée**
        # (`min_hits`) pour entrer dans le registre, et les confiances épuisées
        # rendent 0,0 — qui ne bat jamais rien.
        FakeEngine(_frames(steps if steps is not None else len(scores) + 3)),
        FakePlateDetector(),
        FakePlateReader(score_for=next_score) if read else None,
        plate_ocr=EVERY_FRAME_OCR,
        plate_detect=EVERY_FRAME_DETECT,
        snapshot_encoder=encoder,
    )
    config = AnalysisJobConfig(
        model_id="yolov8n",
        lines=(make_line(),),
        detect_plates=True,
        read_plate_text=read,
    )
    return service.run_video("job-1", video, config), encoder


def _captured(result: AnalysisResultData) -> tuple[float | None, float | None]:
    """La confiance et l'instant de la capture du premier véhicule."""
    vehicle = result.vehicles[0]
    return vehicle.snapshot_score, vehicle.snapshot_ms


class TestLaMeilleureLectureGagne:
    def test_la_premiere_lecture_declenche_une_capture(self, video: Path) -> None:
        result, encoder = _run(video, [0.80])

        assert encoder.calls == 1
        assert _captured(result)[0] == pytest.approx(0.80)

    def test_une_lecture_meilleure_remplace_la_capture(self, video: Path) -> None:
        result, encoder = _run(video, [0.80, 0.90])

        assert encoder.calls == 2
        assert _captured(result)[0] == pytest.approx(0.90)

    def test_une_lecture_moins_bonne_ne_declenche_aucun_encodage(self, video: Path) -> None:
        """**Le test qui prouve l'optimisation**, pas seulement le résultat.

        Après 0,90, la lecture à 0,85 ne doit pas seulement perdre : elle ne doit pas
        coûter un encodage. Encoder puis jeter rendrait le même registre pour un coût
        sans rapport, et un test portant sur le seul résultat ne le verrait jamais.
        """
        result, encoder = _run(video, [0.80, 0.90, 0.85, 0.70])

        assert encoder.calls == 2
        assert _captured(result)[0] == pytest.approx(0.90)

    def test_il_n_y_a_jamais_qu_une_capture_par_vehicule(self, video: Path) -> None:
        result, _ = _run(video, [0.70, 0.80, 0.90])

        assert len(result.snapshots) == 1
        assert set(result.snapshots) == {result.vehicles[0].global_id}

    def test_la_capture_porte_l_instant_de_l_image_retenue(self, video: Path) -> None:
        """L'instant est celui de l'image gagnante, pas de la dernière lue.

        C'est lui qui dit où regarder dans la vidéo : le dater à la fin ferait chercher
        le véhicule là où il n'est déjà plus.
        """
        result, _ = _run(video, [0.80, 0.95, 0.60, 0.60])
        score, timestamp = _captured(result)

        assert score == pytest.approx(0.95)
        assert timestamp is not None
        # Deuxième image analysée, à 25 images par seconde.
        assert timestamp == pytest.approx(40.0)


class TestCeQuiNeCapturePas:
    def test_sans_ocr_aucune_capture(self, video: Path) -> None:
        """La capture suit la **lecture**, pas la localisation.

        Un rectangle sans texte ne prouve rien et ne se classe sur rien : il n'y
        aurait ni raison de garder telle image plutôt qu'une autre, ni texte à
        valider en la regardant.
        """
        result, encoder = _run(video, [0.80, 0.90], read=False)

        assert encoder.calls == 0
        assert result.snapshots == {}
        assert _captured(result) == (None, None)

    def test_un_encodeur_absent_ne_change_rien_d_autre(self, video: Path) -> None:
        """Le comptage, les plaques et le registre sont identiques sans encodeur."""
        service = AnalysisService(
            FakeEngine(_frames()),
            FakePlateDetector(),
            FakePlateReader(),
            plate_ocr=EVERY_FRAME_OCR,
            plate_detect=EVERY_FRAME_DETECT,
        )
        result = service.run_video("job-1", video, CONFIG)

        assert result.snapshots == {}
        assert result.vehicles[0].plate_text == "AB-123-CD"
        assert result.stats is not None
        assert result.stats.crossings == 1

    def test_un_encodage_rate_ne_laisse_pas_de_score_orphelin(self, video: Path) -> None:
        """Sinon un véhicule annoncerait une photo qui n'existe pas.

        L'interface afficherait une image cassée, et la seule façon de comprendre
        serait d'aller lire le disque. C'est pourquoi `should_capture` et
        `record_snapshot` sont deux appels et non un.
        """
        result, encoder = _run(video, [0.80, 0.90], fails=True)

        assert encoder.calls > 0
        assert result.snapshots == {}
        assert _captured(result) == (None, None)

    def test_un_encodeur_qui_refuse_est_redemande(self, video: Path) -> None:
        """Et c'est voulu : un refus décrit **cette image**, pas le véhicule.

        `encode` rend `None` quand il n'y a rien d'exploitable à recadrer — une boîte
        de quelques pixels, un véhicule à moitié hors champ. Deux images plus tard, le
        même véhicule peut très bien être recadrable. Mémoriser l'échec le priverait
        d'une photo pour un état passager, et c'est un mode de panne bien pire que
        quelques appels perdus sur un encodeur durablement en panne — appels que
        l'étranglement de l'OCR borne déjà.
        """
        _, encoder = _run(video, [0.80, 0.90, 0.95], fails=True)

        assert encoder.calls >= 3

    def test_la_capture_recadre_le_vehicule_et_sa_plaque(self, video: Path) -> None:
        """Deux boîtes distinctes, et la plaque est **dans** le véhicule.

        Recadrer deux fois la même chose rendrait deux vignettes identiques, ce qui
        ne se verrait qu'à l'écran — jamais dans un compteur.
        """
        _, encoder = _run(video, [0.80])
        vehicle, plate = encoder.boxes[0]

        assert plate.width < vehicle.width
        assert vehicle.x <= plate.x
        assert plate.x + plate.width <= vehicle.x + vehicle.width
