"""Ce que le banc de pipeline garantit, sans poids ni GPU.

Un banc dont on ne vérifie rien mesure ce qu'il veut. Ces tests portent sur les
propriétés dont dépend la validité de **toutes** les mesures qu'il produit :

1. **il démarre** — la version précédente ne le faisait plus. `_tracker_settings`
   appelait `resolved_tracker_config` avec un seul argument depuis qu'ADR 0024 lui
   avait ajouté le seuil de la requête, et le banc échouait donc sur un `TypeError`
   avant la première image. Un outil de mesure cassé n'est pas un outil dégradé :
   c'est l'absence de mesure, et c'est ce qui rend une optimisation un pari ;
2. **les postes sont des millisecondes par image analysée**, y compris ceux dont le
   service appelle la frontière plusieurs fois par image (l'OCR, une fois par
   piste). Sinon la colonne annonce une unité qu'elle ne porte pas ;
3. **le partage ne dépasse jamais le total** mesuré au poignet ;
4. **l'échelle de résolution ne change que la résolution** — même contenu, même
   cadence, largeur paire, sinon un écart de cadence ne se lit plus comme un écart
   de coût.

Ce que ces tests ne couvrent pas : la mesure elle-même, qui demande des poids et une
vraie vidéo. C'est le rôle des courses appariées lancées à la main, dont les tableaux
partent dans les ADR.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from traffic_analysis.features.counting.domain.models import (
    AnalysisStats,
    Diagnostics,
    DirectionTally,
    LineTally,
)
from traffic_analysis.features.models_registry.infrastructure.registry import ModelRegistry
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    TRACKER_CONFIG,
    UltralyticsEngine,
)

_SPEC = importlib.util.spec_from_file_location(
    "pipeline_bench",
    Path(__file__).resolve().parents[2] / "scripts" / "pipeline_bench.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
pipeline_bench = importlib.util.module_from_spec(_SPEC)
sys.modules["pipeline_bench"] = pipeline_bench
_SPEC.loader.exec_module(pipeline_bench)

#: Ce que porte le fichier de suivi versionné, donc le couple qui ne dérive rien.
_BASE = yaml.safe_load(TRACKER_CONFIG.read_text(encoding="utf-8"))


def _engine(tmp_path: Path) -> UltralyticsEngine:
    """Un moteur réel, mais qui ne servira qu'à `probe()`.

    `probe()` n'ouvre qu'OpenCV : aucun poids n'est touché, aucun modèle n'est
    chargé, donc la CI traverse ce chemin. C'est le seul morceau du moteur dont
    l'échelle de résolution a besoin.
    """
    return UltralyticsEngine(
        ModelRegistry(tmp_path, max_loaded=1, device="cpu", half=False),
        gmc_method=str(_BASE["gmc_method"]),
    )


def _write_video(path: Path, *, width: int, height: int, frames: int, fps: float = 25.0) -> None:
    """Une vraie vidéo minuscule, écrite par OpenCV.

    Un dégradé qui se déplace, et non des images fixes : un encodeur inter-images
    réduirait une suite d'images identiques à presque rien, et la vidéo n'aurait plus
    la propriété qu'on veut lui faire porter — être décodable image par image.
    """
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    assert writer.isOpened(), "OpenCV n'a pas d'encodeur mp4v : ce test ne peut rien vérifier."
    try:
        for index in range(frames):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:, (index * 7) % width : ((index * 7) % width) + max(1, width // 8)] = 255
            writer.write(frame)
    finally:
        writer.release()


class TestLeBancDemarre:
    def test_le_fichier_de_tracker_est_lu_avec_le_seuil_de_la_course(self) -> None:
        """**La régression qui tenait le banc hors service.**

        Deux arguments et non un : le seuil de la requête descend jusqu'au tracker
        depuis ADR 0024. Le test vérifie aussi que le rapport porte ce que le fichier
        dit, parce qu'un rapport qui annoncerait autre chose que ce qui a tourné
        serait pire qu'un rapport sans cette ligne.
        """
        reported = pipeline_bench._tracker_settings(
            str(_BASE["gmc_method"]), float(_BASE["track_high_thresh"])
        )

        assert reported["gmc"] == _BASE["gmc_method"]
        assert reported["trackHighThresh"] == _BASE["track_high_thresh"]
        assert reported["withReid"] == _BASE["with_reid"]
        # Le couple du fichier versionné ne dérive rien : c'est bien lui qui tourne.
        assert reported["trackerFile"] == TRACKER_CONFIG.name

    def test_le_seuil_par_defaut_vient_du_contrat_et_non_du_banc(self) -> None:
        """Recopier « 0,35 » ici se serait désynchronisé au premier changement."""
        from traffic_analysis.features.counting.application.dto import AnalysisJobConfig

        assert (
            AnalysisJobConfig(model_id="yolov8n").confidence_threshold
            == pipeline_bench.DEFAULT_CONFIDENCE
        )


class TestUnitesDuPartage:
    def test_un_poste_appele_plusieurs_fois_par_image_reste_en_ms_par_image(self) -> None:
        """C'est le cas de l'OCR : un appel **par piste**, plusieurs par image.

        Une moyenne des échantillons donnerait 10 ms — le coût d'une lecture — là où
        l'image en a payé trois. La colonne annonce des millisecondes par image ; elle
        doit en porter.
        """
        stage = pipeline_bench.Stage("ocr")
        for _ in range(3):
            stage.add(10.0)

        assert stage.per_frame_ms(2) == pytest.approx(15.0)
        assert stage.calls == 3

    def test_aucune_image_ne_rend_zero_plutot_qu_une_division_par_zero(self) -> None:
        """Une vidéo plus courte que le rodage : le banc doit rendre un rapport, pas
        lever au moment d'écrire le JSON."""
        assert pipeline_bench.Stage("ocr").per_frame_ms(0) == 0.0

    def test_les_deux_etages_de_plaques_entrent_dans_le_partage(self) -> None:
        """Sinon ils tomberaient dans `decodeAndOther`, poste obtenu par différence.

        Le résultat serait de loin le plus cher du tableau, sans qu'aucune ligne ne
        nomme l'OCR — donc en envoyant chercher un problème de décodage.
        """
        timings = pipeline_bench.Timings()
        timings.frames = 2
        timings.wall_ms = 1_000.0
        timings.plate_detect.add(100.0)
        timings.ocr.add(300.0)

        stages = timings.as_json()["stages"]

        assert timings.measured_ms() == pytest.approx(400.0)
        assert stages["plateDetect"] == pytest.approx(50.0)
        assert stages["ocr"] == pytest.approx(150.0)
        assert stages["decodeAndOther"] == pytest.approx(300.0)

    def test_le_partage_ne_depasse_jamais_le_total_mesure_au_poignet(self) -> None:
        """Un `decodeAndOther` négatif se lirait comme une erreur de mesure, et c'en
        serait une : les chronomètres internes peuvent se recouvrir de quelques
        dixièmes, jamais le tout ne peut être plus petit que ses parties."""
        timings = pipeline_bench.Timings()
        timings.frames = 1
        timings.wall_ms = 10.0
        timings.ocr.add(50.0)

        assert timings.as_json()["stages"]["decodeAndOther"] == 0.0

    def test_le_volume_soumis_est_compte_par_image(self) -> None:
        """Le chiffre qui explique l'échelle de résolution : à seuils en pixels
        absolus, le nombre de recadrages et de vignettes monte avec la résolution,
        et c'est ce nombre — pas le coût unitaire — qui écroule la cadence."""
        timings = pipeline_bench.Timings()
        timings.frames = 4
        timings.plate_crops = 14
        timings.ocr_plates = 6

        work = timings.as_json()["work"]

        assert work["plateCropsPerFrame"] == pytest.approx(3.5)
        assert work["ocrPlatesPerFrame"] == pytest.approx(1.5)


class TestGardeFouDeJustesse:
    @staticmethod
    def _stats() -> AnalysisStats:
        """Le **vrai** type publié, et non une doublure.

        Une doublure duck-typée passerait un renommage de champ sans broncher, et le
        banc écrirait alors un rapport amputé du compteur qu'on lui demande de
        surveiller — sans que rien ne lève.
        """
        return AnalysisStats(
            tracked_vehicles=3,
            tracked_by_class={"car": 3},
            crossings=2,
            crossed_unique=2,
            by_class={"car": 2},
            by_line={
                "l": LineTally(
                    positive=DirectionTally(total=1, by_class={"car": 1}),
                    negative=DirectionTally(total=1, by_class={"car": 1}),
                )
            },
            by_zone={},
            vehicles_per_minute=6.0,
            active_tracks=1,
            elapsed_ms=20_000.0,
            analysed_scene_ms=20_000.0,
            diagnostics=Diagnostics(near_misses={"l": 1}),
        )

    def test_sans_registre_le_bloc_ne_parle_pas_de_plaques(self) -> None:
        """Le chemin sans ANPR ne publie aucune plaque : annoncer « 0 publiée »
        laisserait croire que la chaîne a essayé et échoué."""
        assert "platesPublished" not in pipeline_bench._counts(self._stats())

    def test_les_textes_sont_rendus_tries_et_pas_seulement_comptes(self) -> None:
        """Un levier qui publie autant de plaques mais deux d'entre elles
        différentes n'est pas neutre, et un compte égal le cacherait.

        Triés parce que l'ordre du registre suit les identités, qui bougent au
        moindre changement de suivi : sans tri, `--compare` crierait à la régression
        sur une simple permutation.
        """
        counts = pipeline_bench._counts(
            self._stats(),
            (
                _Vehicle("ZZ-999-ZZ"),
                _Vehicle(None),
                _Vehicle("AR606L"),
            ),
        )

        assert counts["platesPublished"] == ["AR606L", "ZZ-999-ZZ"]


class TestEchelleDeResolution:
    def test_un_palier_garde_le_contenu_et_ne_change_que_la_taille(self, tmp_path: Path) -> None:
        """La propriété dont dépend toute l'échelle.

        Le contenu doit rester le même d'un palier à l'autre — c'est ce qui rend les
        **comptages** comparables, donc ce qui permet d'attribuer un écart de cadence
        à un écart de coût plutôt qu'à un écart de scène. Ne sont vérifiables sans
        modèle que les invariants de forme : la hauteur demandée, le rapport d'aspect,
        la cadence, et le nombre d'images.
        """
        import cv2

        source = tmp_path / "input.mp4"
        _write_video(source, width=320, height=240, frames=12)
        engine = _engine(tmp_path)

        produced = pipeline_bench._ladder(
            engine, source, [120], frames_needed=8, cache=tmp_path / "ladder"
        )

        assert len(produced) == 1
        path, codec = produced[0]
        assert codec in {"avc1", "mp4v"}
        # Nommé d'après le **dossier** : toutes les vidéos déposées s'appellent
        # `input.mp4`, et un palier par job les écraserait l'un l'autre.
        assert path.name == f"{tmp_path.name}-120p.mp4"
        info = engine.probe(path)
        assert (info.width, info.height) == (160, 120)
        assert info.fps == pytest.approx(25.0, abs=0.01)
        # `frames_needed` et non la vidéo entière : réencoder six minutes de 4K pour
        # en mesurer deux cents coûterait des gigaoctets.
        assert info.frame_count == 8
        capture = cv2.VideoCapture(str(path))
        try:
            assert capture.isOpened()
        finally:
            capture.release()

    def test_un_palier_deja_present_n_est_pas_reecrit(self, tmp_path: Path) -> None:
        """Le cache est ce qui rend une échelle rejouable en quelques secondes.

        Il porte aussi sa contrepartie, et elle mérite d'être connue : changer
        `--frames` ne réécrit pas un palier existant. C'est pourquoi le codec rendu
        vaut alors « cache » — le rapport ne doit pas affirmer un réencodage qui n'a
        pas eu lieu.
        """
        source = tmp_path / "clip.mp4"
        _write_video(source, width=160, height=120, frames=6)
        engine = _engine(tmp_path)
        cache = tmp_path / "ladder"

        first = pipeline_bench._ladder(engine, source, [120], frames_needed=4, cache=cache)
        stamp = first[0][0].stat().st_mtime_ns
        second = pipeline_bench._ladder(engine, source, [120], frames_needed=4, cache=cache)

        assert second[0][1] == "cache"
        assert second[0][0].stat().st_mtime_ns == stamp


class TestSelectionDesSources:
    def test_sans_echelle_les_fichiers_passent_tels_quels(self, tmp_path: Path) -> None:
        """Et leur codec reste inconnu : l'inventer serait pire que de se taire."""
        videos = [tmp_path / "a.mp4", tmp_path / "b.mp4"]

        assert pipeline_bench._sources(None, videos, _Args(ladder=None)) == [
            (videos[0], ""),
            (videos[1], ""),
        ]

    def test_une_echelle_vide_est_refusee(self, tmp_path: Path) -> None:
        """`--ladder ,,` produirait une course sans aucune source, donc un rapport
        vide qui ne se distingue pas d'une vidéo introuvable."""
        with pytest.raises(SystemExit):
            pipeline_bench._sources(None, [tmp_path / "a.mp4"], _Args(ladder=",,"))


class _Vehicle:
    """Le strict nécessaire de `VehicleRecord` pour `_counts` : son texte voté."""

    def __init__(self, plate_text: str | None) -> None:
        self.plate_text = plate_text


class _Args:
    """Les seuls champs de la ligne de commande que `_sources` lit.

    Le moteur passé à `_sources` vaut `None` dans ces tests, et c'est légitime : sans
    `--ladder`, aucun `probe()` n'a lieu. Le dire ici évite qu'on « corrige » l'appel
    en construisant un moteur dont le test n'a pas besoin.
    """

    def __init__(
        self,
        *,
        ladder: str | None,
        warmup: int = 2,
        frames: int = 4,
        stride: int = 1,
        start: float = 0.0,
    ) -> None:
        self.ladder = ladder
        self.ladder_dir = Path("out/ladder")
        self.warmup = warmup
        self.frames = frames
        self.stride = stride
        self.start = start


class TestQueueDeDistribution:
    """Un coût et une **pause** ne se lisent pas de la même façon, et le banc ne
    distinguait pas les deux.

    L'étage de plaques a affiché 99 ms par image pendant toute une session : sa médiane
    valait 27 ms, et six appels sur 90 dépassaient la seconde en pesant 73 % du poste.
    La moyenne seule envoyait chercher un travail trop lourd là où il fallait chercher
    ce qui bloquait — l'autotune cuDNN, qui réétalonnait à chaque nouvelle forme
    d'entrée (ADR 0033).
    """

    def test_la_mediane_et_le_maximum_separent_la_pause_du_cout(self) -> None:
        """Le cas réel, reproduit : dix-neuf appels normaux et un qui stalle."""
        stage = pipeline_bench.Stage("plateDetect")
        for _ in range(19):
            stage.add(30.0)
        stage.add(1_200.0)

        spread = stage.spread()

        assert spread["p50"] == pytest.approx(30.0)
        assert spread["max"] == pytest.approx(1_200.0)
        # La moyenne, elle, décrit un étage « à 88 ms » qui n'a jamais existé.
        assert spread["mean"] == pytest.approx(88.5)

    def test_un_poste_sans_echantillon_ne_leve_pas(self) -> None:
        """Les postes de plaques restent vides sans `--anpr` : le rapport doit
        s'écrire quand même."""
        assert pipeline_bench.Stage("ocr").spread() == {
            "mean": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "max": 0.0,
        }

    def test_le_rapport_porte_la_queue_de_chaque_poste(self) -> None:
        """Dans le JSON, donc dans `--compare` : c'est ce qui rend une régression de
        queue visible d'une course à l'autre, et pas seulement une régression de
        moyenne."""
        timings = pipeline_bench.Timings()
        timings.frames = 2
        timings.wall_ms = 1_000.0
        timings.plate_detect.add(30.0)
        timings.plate_detect.add(900.0)

        per_call = timings.as_json()["perCall"]

        assert per_call["plateDetect"]["p50"] == pytest.approx(465.0)
        assert per_call["plateDetect"]["max"] == pytest.approx(900.0)
        assert per_call["ocr"]["max"] == 0.0
