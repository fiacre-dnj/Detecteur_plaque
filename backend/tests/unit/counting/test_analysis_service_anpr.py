"""La passe ANPR et la passe OCR, pilotées par le service.

**Aucun test ne pilotait jusqu'ici `run_video` avec `detect_plates=True`.** Ce fichier
comble le trou, et il couvre les trois choses que ni le domaine ni l'adaptateur ne
peuvent démontrer seuls :

- l'**invariant 8** — le snapshot est pris après les deux passes. Testé par sa
  conséquence observable : du texte présent dans la timeline. Un snapshot est une
  copie, donc du texte dedans ne peut venir que d'une OCR exécutée *avant* la copie ;
- la **dégradation indépendante** — un lecteur absent ne doit pas emporter la
  détection avec lui. C'est le mode de panne d'un déploiement neuf, où seul le modèle
  de détection est présent ;
- l'**étranglement** — mesuré en nombre d'inférences, jamais en durée. Un test dont le
  verdict dépend de la vitesse de la machine ne prouve rien.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.builders import CAR, TRUCK, compose, make_line, straight_line, track_path
from tests.support.engine import FakeEngine, FakePlateDetector, FakePlateReader
from traffic_analysis.features.counting.application.analysis_service import AnalysisService
from traffic_analysis.features.counting.application.dto import (
    AnalysisJobConfig,
    AnalysisResultData,
    PlateOcrOptions,
)

VIDEO = Path("/inexistant.mp4")  # `FakeEngine` ne lit jamais le disque.


def _frames(steps: int = 16) -> list[list[object]]:
    return compose(
        track_path(1, CAR, straight_line((700.0, 250.0), (700.0, 800.0), steps=steps)),
        track_path(2, TRUCK, straight_line((1200.0, 800.0), (1200.0, 250.0), steps=steps)),
    )


def _run(
    *,
    detect_plates: bool = True,
    read_plate_text: bool = True,
    detector: FakePlateDetector | None = None,
    reader: FakePlateReader | None = None,
    ocr: PlateOcrOptions | None = None,
    steps: int = 16,
    plate_confidence: float | None = None,
) -> AnalysisResultData:
    service = AnalysisService(
        FakeEngine(_frames(steps)),  # type: ignore[arg-type]
        detector if detector is not None else FakePlateDetector(),
        reader,
        ocr,
    )
    config = AnalysisJobConfig(
        model_id="yolov8n",
        lines=(make_line(),),
        detect_plates=detect_plates,
        read_plate_text=read_plate_text,
        plate_confidence=plate_confidence,
    )
    return service.run_video("job-anpr", VIDEO, config)


def _texts(result: AnalysisResultData) -> list[str]:
    return [
        plate.text
        for row in result.timeline
        for track in row.tracks
        for plate in track.plates
        if plate.text is not None
    ]


class TestPasseComplete:
    def test_les_deux_passes_tournent(self) -> None:
        detector, reader = FakePlateDetector(), FakePlateReader()
        _run(detector=detector, reader=reader)

        assert detector.calls > 0
        assert reader.calls > 0

    def test_la_timeline_porte_le_texte_normalise(self) -> None:
        """L'invariant 8, testé par sa conséquence observable.

        Un snapshot est une **copie** : du texte dedans ne peut venir que d'une OCR
        exécutée avant la copie. Et que ce texte soit `AB-123-CD` alors que le lecteur
        rend `ab-123-cd` prouve du même coup que la normalisation du domaine a tourné.
        """
        result = _run(reader=FakePlateReader(text="ab-123-cd"))

        assert _texts(result)
        assert set(_texts(result)) == {"AB-123-CD"}

    def test_le_registre_porte_le_texte_vote(self) -> None:
        result = _run(reader=FakePlateReader(text="ab-123-cd"))

        assert result.vehicles
        assert all(record.plate_text == "AB-123-CD" for record in result.vehicles)
        assert all(record.plate_text_score == pytest.approx(0.93) for record in result.vehicles)

    def test_le_lot_regroupe_les_plaques_d_une_frame(self) -> None:
        """`crops >= calls` : la preuve que plusieurs plaques partent en un appel.

        Le détecteur factice rend une plaque par piste, donc l'égalité stricte est
        attendue ici — mais l'assertion porte sur l'inégalité, qui est ce que le port
        promet réellement.
        """
        reader = FakePlateReader()
        _run(reader=reader)

        assert reader.crops >= reader.calls

    def test_le_lot_regroupe_les_pistes_d_une_frame_pour_la_detection(self) -> None:
        """La mosaïque, mesurée là où elle compte : **une inférence par frame**.

        Deux pistes traversent ces images ; sans empaquetage le détecteur serait
        appelé deux fois par frame. `crops == 2 × calls` prouve que les deux
        recadrages sont partis ensemble — et c'était le poste dominant du coût de
        l'ANPR, une inférence de 640×640 par piste et par frame.
        """
        detector = FakePlateDetector()
        _run(detector=detector)

        assert detector.calls > 0
        assert detector.crops == 2 * detector.calls

    def test_le_seuil_de_la_requete_atteint_l_adaptateur(self) -> None:
        """`plateConfidence` a été annoncé dans l'API et ignoré pendant tout un lot.

        Un réglage qui figure au contrat et ne fait rien est pire qu'un réglage
        absent : l'utilisateur le déplace, les chiffres ne bougent pas, et il conclut
        que la détection est mauvaise. Rien ne le signalait — d'où ce test.
        """
        detector = FakePlateDetector()
        _run(detector=detector, plate_confidence=0.6)

        assert detector.last_confidence == pytest.approx(0.6)

    def test_sans_seuil_de_requete_l_adaptateur_garde_le_sien(self) -> None:
        """`None` signifie « garde ta configuration », pas « seuil zéro »."""
        detector = FakePlateDetector()
        _run(detector=detector, plate_confidence=None)

        assert detector.last_confidence is None


class TestDegradationGracieuse:
    def test_sans_lecteur_la_detection_continue(self) -> None:
        detector = FakePlateDetector()
        result = _run(detector=detector, reader=None)

        assert detector.calls > 0
        assert _texts(result) == []
        # Les rectangles sont bien là : c'est l'option de l'option qui manque.
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_un_lecteur_indisponible_n_emporte_pas_la_detection(self) -> None:
        """Le mode de panne d'un déploiement neuf : détecteur présent, lecteur absent.

        L'OCR est une option **de** l'option. Si son absence désactivait la détection,
        un serveur sans modèle de lecture perdrait aussi les boîtes qu'il sait
        produire — une régression pour tout le monde au profit de personne.
        """
        detector, reader = FakePlateDetector(), FakePlateReader(available=False)
        result = _run(detector=detector, reader=reader)

        assert detector.calls > 0
        # Jamais appelé : le garde de disponibilité écarte le lecteur en amont.
        assert reader.calls == 0
        assert _texts(result) == []
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_sans_read_plate_text_le_lecteur_n_est_pas_appele(self) -> None:
        detector, reader = FakePlateDetector(), FakePlateReader()
        result = _run(detector=detector, reader=reader, read_plate_text=False)

        assert detector.calls > 0
        assert reader.calls == 0
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_sans_detect_plates_rien_ne_tourne(self) -> None:
        """Lire sans détecter n'a pas de sens : il n'y aurait aucune boîte."""
        detector, reader = FakePlateDetector(), FakePlateReader()
        _run(detector=detector, reader=reader, detect_plates=False, read_plate_text=True)

        assert detector.calls == 0
        assert reader.calls == 0

    def test_un_lecteur_qui_viole_son_contrat_ne_casse_pas_l_analyse(self) -> None:
        """Longueur de retour inattendue : on renonce au texte, pas au comptage."""
        result = _run(reader=FakePlateReader(bad_length=True))

        assert _texts(result) == []
        assert result.stats.crossings == 2
        assert any(track.plates for row in result.timeline for track in row.tracks)

    def test_une_plaque_illisible_garde_sa_boite(self) -> None:
        """« Vue mais illisible » : l'état que l'interface rate le plus facilement."""
        result = _run(reader=FakePlateReader(is_readable=lambda _box: False))

        assert _texts(result) == []
        assert any(track.plates for row in result.timeline for track in row.tracks)
        assert all(record.plate_text is None for record in result.vehicles)
        assert all(record.best_plate_score is not None for record in result.vehicles)


class TestEtranglement:
    def test_un_vote_etabli_arrete_les_inferences(self) -> None:
        """La plus grosse économie du dispositif, mesurée.

        16 frames × 2 pistes = 32 occasions. La cadence en écarte les deux tiers, et
        l'arrêt sur confiance le reste dès que chaque véhicule a trois lectures
        concordantes. La borne est un **compte**, jamais une durée.
        """
        reader = FakePlateReader()
        _run(reader=reader, steps=16)

        assert reader.crops <= 8

    def test_la_cadence_seule_ecarte_deja_des_inferences(self) -> None:
        reader = FakePlateReader()
        _run(
            reader=reader,
            ocr=PlateOcrOptions(every_n_frames=4, stop_when_confident=False, skip_above_iou=1.0),
            steps=16,
        )

        assert 0 < reader.crops < 32

    def test_sans_etranglement_chaque_piste_est_lue_a_chaque_frame(self) -> None:
        """Le témoin : il donne son sens aux bornes des deux tests précédents."""
        reader = FakePlateReader()
        _run(
            reader=reader,
            ocr=PlateOcrOptions(every_n_frames=1, stop_when_confident=False, skip_above_iou=1.0),
            steps=16,
        )

        assert reader.crops > 20
