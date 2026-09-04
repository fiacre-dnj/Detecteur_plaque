"""Le NMS découpé par famille de classes, contre le **vrai** `non_max_suppression`.

`test_engine_arguments.py` lit le texte du module parce qu'exécuter l'appel demanderait
un modèle. Ici on n'en a pas besoin : `postprocess` ne touche que `self.args`,
`self.model` et `construct_results`, donc une instance créée par `object.__new__` suffit
à faire tourner la vraie fonction d'Ultralytics sur un tenseur fabriqué à la main. Pas
de poids, pas de GPU, pas de vidéo, et un verdict déterministe.

Quatre propriétés, et la première est celle qui rend ADR 0057 livrable :

1. **une seule famille ⇒ sortie identique au parent, au bit près.** C'est le cas du jeu
   de classes par défaut : aucune analyse existante ne change de chiffre ;
2. **un pilote et sa moto survivent tous les deux** — la correction elle-même, montrée
   à côté de son témoin, qui est le comportement d'avant ;
3. **le piège 5 est intégralement préservé** : une camionnette scorée `car` et `truck`
   reste dédupliquée, **même quand `person` est cochée**. C'est ce point qui distingue
   le découpage par famille d'un simple `agnostic_nms=False` ;
4. **la fusion est triée et tronquée par score**, jamais par famille.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from traffic_analysis.features.models_registry.infrastructure import ultralytics_engine

if TYPE_CHECKING:
    import torch

torch = pytest.importorskip("torch")
nms = pytest.importorskip("ultralytics.utils.nms")
detect_predict = pytest.importorskip("ultralytics.models.yolo.detect.predict")

PERSON = 0
CAR = 2
MOTORCYCLE = 3
BUS = 5
TRUCK = 7

#: COCO. La largeur du tenseur brut est `4 + nc`.
NUM_CLASSES = 80


def raw_predictions(entries: list[tuple[tuple[float, float, float, float], dict[int, float]]]):
    """Un tenseur brut `(1, 4 + nc, n)` — la forme que le modèle rend avant NMS.

    Les boîtes sont en **centre-x, centre-y, largeur, hauteur** : c'est ce que
    `xywh2xyxy` attend au début de `non_max_suppression`. S'y tromper donnerait des
    recouvrements plausibles et faux, donc des tests qui passent pour la mauvaise raison.
    """
    tensor = torch.zeros((1, 4 + NUM_CLASSES, len(entries)), dtype=torch.float32)
    for index, ((cx, cy, width, height), scores) in enumerate(entries):
        tensor[0, 0, index] = cx
        tensor[0, 1, index] = cy
        tensor[0, 2, index] = width
        tensor[0, 3, index] = height
        for class_id, score in scores.items():
            tensor[0, 4 + class_id, index] = score
    return tensor


def predictor(*, classes: list[int], iou: float = 0.45, max_det: int = 300) -> Any:  # noqa: ANN401
    """Une instance de notre prédicteur, sans modèle ni `__init__`.

    `construct_results` est remplacé par l'identité : ce qu'on veut observer est la
    liste de tenseurs que le NMS a produite, pas des `Results` reconstruits.
    """
    instance = object.__new__(ultralytics_engine._group_aware_predictor())
    instance.args = SimpleNamespace(
        classes=classes,
        conf=0.10,
        iou=iou,
        agnostic_nms=True,
        max_det=max_det,
        task="detect",
    )
    instance.model = SimpleNamespace(end2end=False, names={})
    instance.construct_results = lambda preds, *_args, **_kwargs: preds
    return instance


def labels_of(rows: torch.Tensor) -> list[int]:
    """Les classes retenues, dans l'ordre rendu."""
    return [int(value) for value in rows[:, 5].tolist()]


def scores_of(rows: torch.Tensor) -> list[float]:
    return [round(float(value), 4) for value in rows[:, 4].tolist()]


#: Deux boîtes qui se recouvrent à IoU 0,667 — bien au-dessus du seuil de 0,45 du
#: contrat. Le pilote et sa machine, cadrés serré.
PILOTE = (100.0, 100.0, 100.0, 100.0)
MACHINE = (120.0, 100.0, 100.0, 100.0)


class TestLeTemoin:
    """Le comportement d'avant, montré pour que la correction se lise contre lui."""

    def test_un_nms_agnostique_unique_efface_la_moto(self) -> None:
        preds = raw_predictions([(PILOTE, {PERSON: 0.55}), (MACHINE, {MOTORCYCLE: 0.48})])
        kept = nms.non_max_suppression(preds.clone(), 0.10, 0.45, [PERSON, MOTORCYCLE], True, nc=0)
        assert labels_of(kept[0]) == [PERSON]

    def test_le_recouvrement_est_bien_au_dessus_du_seuil(self) -> None:
        """La prémisse : sans elle le test précédent passerait sans rien prouver."""
        # (50,50)-(150,150) contre (70,50)-(170,150) : intersection 80x100 = 8 000,
        # union 10 000 + 10 000 - 8 000 = 12 000.
        assert 8000 / 12000 > 0.45


class TestLaCorrection:
    def test_le_pilote_et_sa_moto_survivent_tous_les_deux(self) -> None:
        preds = raw_predictions([(PILOTE, {PERSON: 0.55}), (MACHINE, {MOTORCYCLE: 0.48})])

        merged = predictor(classes=[PERSON, MOTORCYCLE]).postprocess(preds, None, [None])

        assert sorted(labels_of(merged[0])) == [PERSON, MOTORCYCLE]

    def test_la_correction_vaut_dans_les_deux_sens(self) -> None:
        """Le NMS est symétrique : quand le véhicule score le plus haut, c'est la
        personne qui tombait. La moitié « personnes » du symptôme rapporté."""
        preds = raw_predictions([(PILOTE, {PERSON: 0.40}), (MACHINE, {MOTORCYCLE: 0.62})])

        temoin = nms.non_max_suppression(
            preds.clone(), 0.10, 0.45, [PERSON, MOTORCYCLE], True, nc=0
        )
        merged = predictor(classes=[PERSON, MOTORCYCLE]).postprocess(preds, None, [None])

        assert labels_of(temoin[0]) == [MOTORCYCLE]
        assert sorted(labels_of(merged[0])) == [PERSON, MOTORCYCLE]


class TestLePiege5EstPreserve:
    def test_la_camionnette_reste_dedupliquee_meme_avec_personne_cochee(self) -> None:
        """**Ce qui distingue le découpage par famille d'un `agnostic_nms=False`.**

        `car` et `truck` sont du même groupe, donc ils entrent dans le même appel
        agnostique et l'un des deux tombe — exactement comme aujourd'hui. Un simple
        passage en class-aware les aurait laissés survivre tous les deux : deux pistes,
        deux véhicules, deux franchissements.
        """
        preds = raw_predictions([(PILOTE, {CAR: 0.52}), (MACHINE, {TRUCK: 0.41})])

        merged = predictor(classes=[PERSON, CAR, MOTORCYCLE, BUS, TRUCK]).postprocess(
            preds, None, [None]
        )

        assert labels_of(merged[0]) == [CAR]

    def test_un_nms_class_aware_aurait_garde_les_deux(self) -> None:
        """Le témoin de l'alternative écartée, pour que le choix reste lisible."""
        preds = raw_predictions([(PILOTE, {CAR: 0.52}), (MACHINE, {TRUCK: 0.41})])
        kept = nms.non_max_suppression(preds.clone(), 0.10, 0.45, [CAR, TRUCK], False, nc=0)
        assert sorted(labels_of(kept[0])) == [CAR, TRUCK]


class TestUneSeuleFamilleNeChangeRien:
    def test_le_jeu_par_defaut_rend_exactement_ce_que_le_parent_rend(self) -> None:
        """La propriété qui rend le changement livrable : aucune analyse ne bouge."""
        entries = [
            (PILOTE, {CAR: 0.52}),
            (MACHINE, {TRUCK: 0.41}),
            ((600.0, 300.0, 80.0, 60.0), {MOTORCYCLE: 0.66}),
            ((900.0, 500.0, 200.0, 150.0), {BUS: 0.71}),
        ]
        classes = [CAR, MOTORCYCLE, BUS, TRUCK]

        merged = predictor(classes=classes).postprocess(raw_predictions(entries), None, [None])
        parent = detect_predict.DetectionPredictor.postprocess(
            predictor(classes=classes), raw_predictions(entries), None, [None]
        )

        assert torch.equal(merged[0], parent[0])


class TestFusion:
    def test_les_boites_sortent_triees_par_score_decroissant(self) -> None:
        """Concaténer trois familles rend un ordre par blocs ; le NMS rend un ordre
        décroissant. Le tracker n'a pas à connaître la différence."""
        entries = [
            ((100.0, 100.0, 60.0, 60.0), {PERSON: 0.30}),
            ((400.0, 100.0, 60.0, 60.0), {MOTORCYCLE: 0.90}),
            ((700.0, 100.0, 60.0, 60.0), {CAR: 0.60}),
        ]

        merged = predictor(classes=[PERSON, CAR, MOTORCYCLE]).postprocess(
            raw_predictions(entries), None, [None]
        )

        assert scores_of(merged[0]) == [0.9, 0.6, 0.3]
        assert labels_of(merged[0]) == [MOTORCYCLE, CAR, PERSON]

    def test_max_det_coupe_les_scores_les_plus_bas_et_non_la_derniere_famille(self) -> None:
        entries = [
            ((100.0, 100.0, 60.0, 60.0), {PERSON: 0.30}),
            ((400.0, 100.0, 60.0, 60.0), {MOTORCYCLE: 0.90}),
            ((700.0, 100.0, 60.0, 60.0), {CAR: 0.60}),
        ]

        merged = predictor(classes=[PERSON, CAR, MOTORCYCLE], max_det=2).postprocess(
            raw_predictions(entries), None, [None]
        )

        assert labels_of(merged[0]) == [MOTORCYCLE, CAR]

    def test_le_tenseur_brut_est_clone_a_chaque_famille(self) -> None:
        """**La panne la plus discrète du lot.**

        `non_max_suppression` fait `prediction.transpose(-1, -2)` — une vue — puis
        `prediction[..., :4] = xywh2xyxy(...)` : elle convertit les boîtes **en place**
        dans le tenseur de l'appelant. Sans `clone`, le deuxième appel reconvertirait
        des xyxy en xyxy et rendrait des boîtes plausibles et fausses.

        On le vérifie par l'invariance de l'entrée, la seule observation qui ne dépende
        pas de l'implémentation de la fusion.
        """
        preds = raw_predictions([(PILOTE, {PERSON: 0.55}), (MACHINE, {MOTORCYCLE: 0.48})])
        before = preds.clone()

        predictor(classes=[PERSON, MOTORCYCLE]).postprocess(preds, None, [None])

        assert torch.equal(preds, before)


class TestInstallation:
    """Le prédicteur est construit **une fois** par instance de modèle — ADR 0035.

    Le préchauffage appelle `model.predict()` au démarrage, donc le prédicteur par
    défaut est en place avant le premier `track()` et l'argument `predictor=` est
    ignoré pour toute la vie du processus. Sans l'échange de classe, le correctif
    serait entièrement inerte — et la première analyse après un démarrage n'obéirait
    pas non plus, contrairement au cas d'ADR 0035.
    """

    def test_un_predicteur_par_defaut_deja_construit_est_echange(self) -> None:
        model = SimpleNamespace(predictor=object.__new__(detect_predict.DetectionPredictor))

        ultralytics_engine.install_group_aware_nms(model)

        assert type(model.predictor) is ultralytics_engine._group_aware_predictor()

    def test_l_echange_est_idempotent(self) -> None:
        """Une analyse par job sur la même instance résidente : il passe ici à chaque fois."""
        model = SimpleNamespace(predictor=object.__new__(detect_predict.DetectionPredictor))

        ultralytics_engine.install_group_aware_nms(model)
        first = model.predictor
        ultralytics_engine.install_group_aware_nms(model)

        assert model.predictor is first
        assert type(model.predictor) is ultralytics_engine._group_aware_predictor()

    def test_un_modele_sans_predicteur_est_laisse_tel_quel(self) -> None:
        """`predictor=` de `track()` s'en chargera : ici il n'y a rien à échanger."""
        model = SimpleNamespace(predictor=None)

        ultralytics_engine.install_group_aware_nms(model)

        assert model.predictor is None

    def test_un_predicteur_d_une_autre_tache_n_est_pas_touche(self) -> None:
        """Le test de type est **exact** : un prédicteur de pose ou de segmentation
        n'a rien à faire ici, et l'échanger casserait son propre post-traitement."""

        class ForeignPredictor(detect_predict.DetectionPredictor):
            pass

        foreign = object.__new__(ForeignPredictor)
        model = SimpleNamespace(predictor=foreign)

        ultralytics_engine.install_group_aware_nms(model)

        assert type(model.predictor) is ForeignPredictor
