"""Pourquoi une plaque n'est pas publiée.

Sans ces raisons, l'étranglement du détecteur et le plancher de lecture rendent le
silence **plus** fréquent — et le silence est exactement ce que l'utilisateur lit
comme une panne. Une case vide dans le registre ne dit pas s'il faut installer un
modèle, resserrer le plan, stabiliser la caméra, ou ne rien faire du tout.

La raison est **dérivée à la fin** par une fonction pure, jamais accumulée au fil
des images : l'état final donne la cause sans ambiguïté, alors qu'accumuler
obligerait à décider laquelle gagne quand deux causes se succèdent.
"""

from __future__ import annotations

from pathlib import Path

from tests.support.builders import CAR, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine, FakePlateDetector, FakePlateReader
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    AnalysisResultData,
    PlateOcrOptions,
)
from traffic_analysis.features.counting.domain.models import BoundingBox
from traffic_analysis.features.counting.domain.plate_geometry import unread_reason

VIDEO = Path("/inexistant.mp4")
VEHICLE_SIZE = (160.0, 120.0)


class TestFonctionPure:
    """Les cinq raisons, sur la fonction qui les décide."""

    def test_ocr_desactivee(self) -> None:
        """Rien n'a été tenté : **ce n'est pas un échec**, et le dire évite de
        chercher une panne là où il n'y a qu'une option décochée."""
        assert (
            unread_reason(
                ocr_enabled=False,
                plate_seen=True,
                best_width_px=200.0,
                read_attempted=False,
                min_width_px=64.0,
            )
            == "ocr_disabled"
        )

    def test_aucune_plaque_detectee(self) -> None:
        """Angle de vue, occlusion, véhicule vu de côté — pas une affaire de
        résolution, donc pas le même geste que `too_small`."""
        assert (
            unread_reason(
                ocr_enabled=True,
                plate_seen=False,
                best_width_px=None,
                read_attempted=False,
                min_width_px=64.0,
            )
            == "not_detected"
        )

    def test_sous_le_plancher_de_lecture(self) -> None:
        """**La cause dominante sur les vidéos disponibles** — 27 à 88 px pour un
        plancher mesuré à ~64."""
        assert (
            unread_reason(
                ocr_enabled=True,
                plate_seen=True,
                best_width_px=48.0,
                read_attempted=False,
                min_width_px=64.0,
            )
            == "too_small"
        )

    def test_assez_large_mais_jamais_tentee_est_du_flou(self) -> None:
        """Au-dessus du plancher et pourtant jamais lue : la seule garde restante
        est celle de netteté."""
        assert (
            unread_reason(
                ocr_enabled=True,
                plate_seen=True,
                best_width_px=200.0,
                read_attempted=False,
                min_width_px=64.0,
            )
            == "too_blurry"
        )

    def test_lue_sans_majorite(self) -> None:
        """Le refus **honnête** du vote, et non une panne : publier une des lectures
        divergentes ferait apparaître une plaque fausse et plausible."""
        assert (
            unread_reason(
                ocr_enabled=True,
                plate_seen=True,
                best_width_px=200.0,
                read_attempted=True,
                min_width_px=64.0,
            )
            == "no_consensus"
        )


def _run(
    *,
    reader: FakePlateReader | None,
    plate_width_ratio: float = 0.4,
    read_plate_text: bool = True,
) -> AnalysisResultData:
    """Une analyse dont la largeur de plaque est pilotée par le test."""
    detector = FakePlateDetector(
        plates_for=lambda box: (
            (
                BoundingBox(
                    x=box.x + box.width * 0.3,
                    y=box.y + box.height * 0.65,
                    width=box.width * plate_width_ratio,
                    height=box.height * 0.15,
                ),
                0.8,
            ),
        )
    )
    service = AnalysisService(
        FakeEngine(  # type: ignore[arg-type]
            compose(
                track_path(
                    1,
                    CAR,
                    straight_line((700.0, 250.0), (700.0, 800.0), steps=16),
                    box_size=VEHICLE_SIZE,
                )
            )
        ),
        detector,
        reader,
        PlateOcrOptions(min_width_px=64.0),
    )
    return service.run_video(
        "job-raisons",
        VIDEO,
        AnalysisJobConfig(
            model_id="yolov8n",
            lines=(make_line(),),
            detect_plates=True,
            read_plate_text=read_plate_text,
        ),
    )


class TestBoutEnBout:
    """La raison telle qu'elle atteint réellement le registre."""

    def test_une_plaque_sous_le_plancher_donne_too_small_et_sa_largeur(self) -> None:
        """Le couple raison + largeur, qui est ce qui rend le message actionnable :
        « vue à 48 px » dit de resserrer le plan."""
        # 160 × 0,3 = 48 px, sous le plancher de 64.
        result = _run(reader=FakePlateReader(), plate_width_ratio=0.3)

        assert result.vehicles
        for record in result.vehicles:
            assert record.plate_text is None
            assert record.plate_unread_reason == "too_small"
            assert record.plate_best_width_px == 48.0

    def test_aucune_plaque_donne_not_detected(self) -> None:
        detector = FakePlateDetector(plates_for=lambda _box: ())
        service = AnalysisService(
            FakeEngine(  # type: ignore[arg-type]
                compose(
                    track_path(
                        1,
                        CAR,
                        straight_line((700.0, 250.0), (700.0, 800.0), steps=16),
                        box_size=VEHICLE_SIZE,
                    )
                )
            ),
            detector,
            FakePlateReader(),
        )
        result = service.run_video(
            "job-vide",
            VIDEO,
            AnalysisJobConfig(
                model_id="yolov8n",
                lines=(make_line(),),
                detect_plates=True,
                read_plate_text=True,
            ),
        )

        assert result.vehicles
        for record in result.vehicles:
            assert record.plate_unread_reason == "not_detected"
            assert record.plate_best_width_px is None

    def test_sans_lecteur_la_raison_est_ocr_desactivee(self) -> None:
        """Le déploiement neuf : détection présente, lecture absente. Ce n'est pas
        un échec, et le registre ne doit pas le présenter comme tel."""
        result = _run(reader=None)

        assert result.vehicles
        for record in result.vehicles:
            assert record.plate_unread_reason == "ocr_disabled"

    def test_une_plaque_lue_n_a_aucune_raison(self) -> None:
        """La raison n'explique jamais un succès."""
        result = _run(reader=FakePlateReader(), plate_width_ratio=0.6)

        assert result.vehicles
        for record in result.vehicles:
            assert record.plate_text == "AB-123-CD"
            assert record.plate_unread_reason is None

    def test_des_lectures_discordantes_donnent_no_consensus_et_un_candidat(self) -> None:
        """Le registre dit *pourquoi* le silence, et rapporte quand même le meilleur
        candidat vu — sans jamais le confondre avec un texte publié.

        Trois graphies de **longueurs différentes**, et non de même longueur : à
        longueur égale, le consensus par caractère peut trancher là où le vote par
        chaîne entière refuse — c'est son rôle sur une quasi-égalité (voir
        `test_plate_vote.py`). Des longueurs distinctes empêchent les deux voies de
        publier, ce qui isole vraiment le cas que ce test vérifie.
        """
        rotation = ["ab-123-cd", "xy-78-zw", "mn-4567-op"]
        calls = iter(range(1_000))
        result = _run(
            reader=FakePlateReader(text_for=lambda _box: rotation[next(calls) % len(rotation)]),
            plate_width_ratio=0.6,
        )

        assert result.vehicles
        for record in result.vehicles:
            assert record.plate_text is None
            assert record.plate_unread_reason == "no_consensus"
            assert record.plate_best_guess is not None
            assert record.plate_best_guess_score is not None

    def test_un_silence_autre_que_no_consensus_ne_rapporte_aucun_candidat(self) -> None:
        """`plate_best_guess` n'a de sens que sur `no_consensus` : dans les autres
        raisons de silence, aucune lecture n'a eu lieu."""
        result = _run(reader=FakePlateReader(), plate_width_ratio=0.3)

        assert result.vehicles
        for record in result.vehicles:
            assert record.plate_unread_reason == "too_small"
            assert record.plate_best_guess is None
            assert record.plate_best_guess_score is None
