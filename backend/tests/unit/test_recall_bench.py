"""Ce que le banc de rappel garantit, sans poids, sans GPU et sans vidéo.

Un banc dont on ne vérifie rien mesure ce qu'il veut — et celui-ci va servir à
trancher des correctifs qui changent des comptages. Cinq propriétés, dont la
dernière est la seule qui ne porte pas sur l'arithmétique :

1. **il démarre** — `test_pipeline_bench.py` existe parce que son banc ne le faisait
   plus, et personne ne s'en était aperçu avant d'en avoir besoin ;
2. **l'appariement est un IoU, pas une containment** — c'est le piège propre à ce
   dépôt : `BoundingBox.containment` existe, divise par la plus petite aire, et
   apparierait une boîte de 20 px posée dans une boîte de 200 px avec un score de 1,0.
   Un rappel de moto parfait et complètement faux ;
3. **un candidat parfait rend un rappel de 1,0** — le contrôle du banc par lui-même.
   Toute autre valeur est un bug d'appariement, pas une mesure ;
4. **une classe rendue sous une autre étiquette n'est pas un manqué de détection** —
   c'est le cas que ce banc existe pour séparer (`nms.py:126 conf, j = cls.max(1)`), et
   les fondre enverrait régler le seuil de confiance au lieu du NMS ;
5. **le banc appelle le détecteur avec les arguments de la production** — sinon
   `--stage detector` mesure une chaîne qui n'existe pas. Test de texte, étroit mais
   réel, sur le patron assumé de `test_engine_arguments.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from traffic_analysis.features.counting.domain.models import BoundingBox

_SPEC = importlib.util.spec_from_file_location(
    "recall_bench",
    Path(__file__).resolve().parents[2] / "scripts" / "recall_bench.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
recall_bench = importlib.util.module_from_spec(_SPEC)
sys.modules["recall_bench"] = recall_bench
_SPEC.loader.exec_module(recall_bench)


def box(x: float, y: float, width: float, height: float) -> BoundingBox:
    return BoundingBox(x=x, y=y, width=width, height=height)


def detection(
    label: str, class_id: int, score: float, geometry: BoundingBox
) -> recall_bench.Detection:
    return recall_bench.Detection(class_id=class_id, label=label, score=score, box=geometry)


class TestLeBancDemarre:
    def test_le_module_expose_son_analyseur_d_arguments(self) -> None:
        """La panne qu'a connue `pipeline_bench` : un banc qui ne se lance plus."""
        parser = recall_bench.build_parser()
        args = parser.parse_args(["--videos", "clip.mp4", "--classes", "0,3"])
        assert args.stage == "tracked"
        assert args.classes == "0,3"
        assert args.truth_model == recall_bench.DEFAULT_TRUTH_MODEL


class TestIoU:
    """L'IoU et pas la containment — le piège propre à ce dépôt."""

    def test_deux_boites_identiques_valent_un(self) -> None:
        same = box(10, 10, 100, 100)
        assert recall_bench.iou(same, same) == pytest.approx(1.0)

    def test_deux_boites_disjointes_valent_zero(self) -> None:
        assert recall_bench.iou(box(0, 0, 10, 10), box(50, 50, 10, 10)) == 0.0

    def test_une_boite_degeneree_ne_leve_pas(self) -> None:
        assert recall_bench.iou(box(0, 0, 0, 0), box(0, 0, 10, 10)) == 0.0

    def test_le_recouvrement_est_calcule_sur_l_union(self) -> None:
        # Deux carrés de 100 décalés de 50 : intersection 50×100 = 5 000,
        # union 2 × 10 000 − 5 000 = 15 000, donc 1/3.
        assert recall_bench.iou(box(0, 0, 100, 100), box(50, 0, 100, 100)) == pytest.approx(1 / 3)

    def test_une_petite_boite_posee_dans_une_grande_n_est_PAS_appariee(self) -> None:
        """La propriété qui distingue l'IoU de `containment`, et elle vaut un bug.

        `BoundingBox.containment` rendrait `1,0` ici — elle divise par la plus petite
        aire, ce qui est exactement ce qu'il faut pour attraper une cabine dans un semi
        (`_drop_contained`) et exactement ce qu'il ne faut pas pour dire « ces deux
        rectangles désignent le même objet ». Une moto de 20 px appariée à la boîte du
        camion qui la masque rendrait un rappel parfait sur la classe qu'on cherche
        justement à récupérer.
        """
        moto = box(100, 100, 20, 20)
        camion = box(50, 50, 200, 200)
        assert moto.containment(camion) == pytest.approx(1.0)
        assert recall_bench.iou(moto, camion) < recall_bench.DEFAULT_MATCH_IOU

        truth = [detection("motorcycle", 3, 1.0, moto)]
        candidate = [detection("truck", 7, 0.9, camion)]
        assert recall_bench.match(truth, candidate) == {}


class TestAppariement:
    def test_un_candidat_parfait_rend_un_rappel_de_un(self) -> None:
        """Le contrôle du banc par lui-même : sans lui, aucun chiffre n'est croyable."""
        boxes = [box(0, 0, 60, 90), box(300, 120, 40, 80), box(700, 400, 150, 120)]
        truth = [detection("motorcycle", 3, 1.0, geometry) for geometry in boxes]
        candidate = [detection("motorcycle", 3, 0.8, geometry) for geometry in boxes]

        pairs = recall_bench.match(truth, candidate)
        assert len(pairs) == len(truth)

        tally = recall_bench.Tally()
        for index, reference in enumerate(truth):
            tally.record(reference, candidate[pairs[index]])
        report = tally.report()
        assert report["recall"] == pytest.approx(1.0)
        assert report["spatialRecall"] == pytest.approx(1.0)
        assert sum(report["missedByWidth"].values()) == 0

    def test_le_candidat_le_mieux_score_choisit_en_premier(self) -> None:
        """Glouton par score décroissant : la convention d'évaluation de la détection.

        Les deux candidats recouvrent la même boîte de vérité au-dessus du seuil. Un
        appariement qui prendrait le premier venu rendrait le même rappel ici et un
        rappel différent dès qu'il y a deux boîtes de vérité — donc un chiffre qui
        dépend de l'ordre de sortie du modèle.
        """
        reference = box(100, 100, 100, 100)
        truth = [detection("car", 2, 1.0, reference)]
        faible = detection("car", 2, 0.30, box(105, 105, 100, 100))
        fort = detection("car", 2, 0.90, box(102, 102, 100, 100))

        pairs = recall_bench.match(truth, [faible, fort])
        assert pairs == {0: 1}

    def test_une_boite_de_verite_n_est_apparie_qu_une_fois(self) -> None:
        truth = [detection("person", 0, 1.0, box(0, 0, 40, 100))]
        candidate = [
            detection("person", 0, 0.9, box(0, 0, 40, 100)),
            detection("person", 0, 0.8, box(1, 1, 40, 100)),
        ]
        pairs = recall_bench.match(truth, candidate)
        assert pairs == {0: 0}

    def test_rien_ne_s_apparie_sous_le_seuil(self) -> None:
        truth = [detection("motorcycle", 3, 1.0, box(0, 0, 100, 100))]
        candidate = [detection("motorcycle", 3, 0.9, box(80, 0, 100, 100))]
        assert recall_bench.match(truth, candidate) == {}


class TestClasseContreEmplacement:
    def test_une_moto_rendue_person_n_est_pas_un_manque_de_detection(self) -> None:
        """Le cas que ce banc existe pour séparer.

        `nms.py:126` garde le seul top-1 de l'ancre : un deux-roues dont l'évidence
        `person` domine sort sous « person », à la bonne place. Le compter comme un
        manqué enverrait baisser « Confiance véhicules », alors que la cause est le
        NMS et que le geste est ailleurs.
        """
        geometry = box(500, 400, 70, 120)
        reference = detection("motorcycle", 3, 1.0, geometry)
        rendu = detection("person", 0, 0.55, box(505, 402, 68, 118))

        pairs = recall_bench.match([reference], [rendu])
        assert pairs == {0: 0}

        tally = recall_bench.Tally()
        tally.record(reference, rendu)
        report = tally.report()
        assert report["recall"] == pytest.approx(0.0)
        assert report["spatialRecall"] == pytest.approx(1.0)
        assert report["classConfusion"] == {"person": 1}

    def test_un_objet_jamais_rendu_tombe_dans_none(self) -> None:
        reference = detection("motorcycle", 3, 1.0, box(500, 400, 70, 120))
        tally = recall_bench.Tally()
        tally.record(reference, None)
        report = tally.report()
        assert report["spatialRecall"] == pytest.approx(0.0)
        assert report["classConfusion"] == {"none": 1}


class TestSeauxDeLargeur:
    @pytest.mark.parametrize(
        ("width", "expected"),
        [(0.0, "<32"), (31.9, "<32"), (32.0, "32-64"), (64.0, "64-128"), (128.0, ">=128")],
    )
    def test_les_bornes_sont_inclusives_a_gauche(self, width: float, expected: str) -> None:
        assert recall_bench.bucket_of(width) == expected

    def test_les_manques_par_largeur_somment_exactement_aux_manques(self) -> None:
        """L'égalité, et pas les valeurs : c'est elle qui empêche deux compteurs de diverger.

        Un manqué doit apparaître dans un seau et un seul, qu'il soit absent ou rendu
        sous une autre classe. Sans cette propriété, `missedByWidth` dirait une histoire
        plausible et fausse sur l'endroit où la chaîne perd les petits objets — c'est-à-dire
        exactement le chiffre pour lequel ce banc est écrit.
        """
        petite = box(10, 10, 20, 40)
        moyenne = box(200, 10, 50, 90)
        grande = box(400, 10, 200, 160)
        tally = recall_bench.Tally()
        tally.record(detection("motorcycle", 3, 1.0, petite), None)
        tally.record(
            detection("motorcycle", 3, 1.0, moyenne),
            detection("person", 0, 0.5, moyenne),
        )
        tally.record(
            detection("motorcycle", 3, 1.0, grande),
            detection("motorcycle", 3, 0.9, grande),
        )

        report = tally.report()
        assert report["truth"] == 3
        assert report["matched"] == 1
        assert report["spatialMatched"] == 2
        assert sum(report["missedByWidth"].values()) == report["truth"] - report["matched"]
        assert sum(report["truthByWidth"].values()) == report["truth"]
        assert report["missedByWidth"]["<32"] == 1
        assert report["missedByWidth"]["32-64"] == 1
        assert report["missedByWidth"][">=128"] == 0

    def test_une_classe_sous_le_minimum_est_marquee(self) -> None:
        """Un rappel sur sept motos est du bruit : le banc doit le dire, pas l'imprimer nu."""
        tally = recall_bench.Tally()
        tally.record(detection("motorcycle", 3, 1.0, box(0, 0, 60, 90)), None)
        assert tally.report()["enoughInstances"] is False


class TestLeBancMesureLaProduction:
    """Le doublon d'arguments est assumé — donc il doit être verrouillé.

    `_candidate_boxes` recopie les arguments de détection de `_track_batches`, parce
    que le vrai chemin passe par `model.track()`, dont l'étage `detector` veut
    justement retirer le tracker. Si l'un des deux change sans l'autre, le banc mesure
    une chaîne qui n'existe pas — et il continuera de rendre des chiffres plausibles.

    Test de texte, comme `test_engine_arguments.py` : étroit, et réel.
    """

    BENCH = Path(__file__).resolve().parents[2] / "scripts" / "recall_bench.py"
    ENGINE = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "traffic_analysis"
        / "features"
        / "models_registry"
        / "infrastructure"
        / "ultralytics_engine.py"
    )

    @pytest.mark.parametrize(
        "argument",
        [
            "conf=detector_floor(",
            "agnostic_nms=True",
            "iou=spec.iou",
            "classes=list(spec.class_ids)",
        ],
    )
    def test_le_banc_et_le_moteur_passent_les_memes_arguments(self, argument: str) -> None:
        bench = self.BENCH.read_text(encoding="utf-8")
        engine = self.ENGINE.read_text(encoding="utf-8")
        assert argument in engine, f"le moteur ne passe plus {argument} : le banc est à corriger"
        assert argument in bench, (
            f"le banc ne passe plus {argument} : il ne mesure plus la production"
        )

    def test_la_verite_ne_subit_pas_la_suppression_inter_classes(self) -> None:
        """La référence ne doit surtout pas subir ce que le banc est censé mesurer."""
        bench = self.BENCH.read_text(encoding="utf-8")
        truth_call = bench.split("def _truth_boxes")[1].split("def ")[0]
        assert "agnostic_nms=False" in truth_call
        assert "classes=None" in truth_call
