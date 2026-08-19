"""L'adaptateur de détection de plaques, **sans poids et sans ultralytics**.

Deux choses valent d'être démontrées ici, et elles ne se ressemblent pas.

La première est l'**aller-retour de coordonnées** de la mosaïque. Plusieurs
recadrages de véhicules entrent dans une seule image de 640×640, et une boîte
trouvée en ressort après trois changements de repère : cellule → recadrage →
image complète. Une erreur dans cette chaîne ne lève rien. Elle décale tous les
rectangles, et un rectangle décalé se lit comme un défaut de détection — jamais
comme un défaut de repère (invariant 14 : le serveur ne peut pas détecter ce que
le client voit). Les tests reconstruisent donc la boîte attendue à la main et
exigent l'égalité au pixel près.

La seconde est le **filtre de plausibilité**. Il ne peut que retirer des
détections, donc il ne peut pas améliorer le rappel ; tout son intérêt est de ne
pas retirer les bonnes. Chaque test nomme la boîte absurde qu'il écarte.

Le modèle n'est jamais chargé : `_pack`, `_locate`, `_to_crop` et `_is_plausible`
sont des fonctions de géométrie pure, et c'est délibérément là qu'est la logique
risquée.
"""

from __future__ import annotations

import numpy as np
import pytest

from traffic_analysis.features.counting.application.dto import BoundingBox
from traffic_analysis.features.models_registry.infrastructure.plate_detector import (
    DEFAULT_MOSAIC_SIDE,
    MAX_BATCH,
    MOSAIC_GUTTER_PX,
    NET_SIZE,
    PAD_VALUE,
    PlateGeometry,
    UltralyticsPlateDetector,
)

_MISSING = "modele-absent.onnx"


def _detector(**kwargs: object) -> UltralyticsPlateDetector:
    from pathlib import Path

    return UltralyticsPlateDetector(Path(_MISSING), 0.25, **kwargs)  # type: ignore[arg-type]


def _crop(width: int, height: int, fill: int = 200) -> np.ndarray:
    """Un recadrage texturé : une image unie ne prouverait pas l'orientation."""
    crop = np.full((height, width, 3), fill, dtype=np.uint8)
    crop[:, : max(1, width // 4)] = 40
    return crop


class TestEmpaquetage:
    def test_la_mosaique_est_desactivee_par_defaut(self) -> None:
        """**Le rappel ne se troque pas contre du débit sans qu'on le demande.**

        L'empaquetage n'est pas gratuit, contrairement à ce que suggère l'intuition
        « sur-échantillonner n'apporte pas d'information ». Ce qui décide qu'une
        plaque est trouvée est sa taille dans l'entrée du réseau, et elle ne dépend
        que de la cellule : `plaque ≈ 0,15 × côté_de_cellule`. Mesuré sur 657
        véhicules de vraie circulation — côté 1 : 100 % de rappel ; côté 2 : 84 %
        pour 3,4× ; côté 3 : 56 % pour 6,6×.

        Ce test existe pour qu'un futur réglage de performance ne fasse pas glisser
        ce défaut sans que la mesure soit refaite.
        """
        assert DEFAULT_MOSAIC_SIDE == 1
        assert _detector()._mosaic_side == 1

    def test_une_seule_piste_occupe_une_grille_1x1(self) -> None:
        """Pas de mosaïque quand il n'y a rien à empaqueter."""
        detector = _detector()
        tile, placements = detector._pack([(0, _crop(200, 150), 10, 20)])

        assert tile.shape == (NET_SIZE, NET_SIZE, 3)
        assert len(placements) == 1
        cell = NET_SIZE - 2 * MOSAIC_GUTTER_PX
        # Le recadrage est 4:3, donc c'est la largeur qui bute sur la cellule.
        assert placements[0].scale == pytest.approx(cell / 200)

    def test_quatre_pistes_tiennent_dans_une_grille_2x2(self) -> None:
        """La grille est la plus petite qui contienne le paquet, jamais la plus grande.

        Une grille 3×3 pour quatre recadrages rétrécirait les cellules de 308 à
        202 px sans rien empaqueter de plus.
        """
        detector = _detector()
        _, placements = detector._pack([(i, _crop(200, 150), 0, 0) for i in range(4)])

        cell = (NET_SIZE - 3 * MOSAIC_GUTTER_PX) // 2
        offsets = {(p.offset_x, p.offset_y) for p in placements}
        assert offsets == {
            (MOSAIC_GUTTER_PX, MOSAIC_GUTTER_PX),
            (2 * MOSAIC_GUTTER_PX + cell, MOSAIC_GUTTER_PX),
            (MOSAIC_GUTTER_PX, 2 * MOSAIC_GUTTER_PX + cell),
            (2 * MOSAIC_GUTTER_PX + cell, 2 * MOSAIC_GUTTER_PX + cell),
        }

    def test_les_cellules_ne_se_touchent_jamais(self) -> None:
        """La gouttière n'est pas cosmétique.

        Sans elle, le champ récepteur du réseau déborde d'une cellule sur l'autre et
        fabrique des détections à cheval sur deux véhicules — une plaque attribuée au
        voisin, ce qu'aucune couche en aval ne peut rattraper.
        """
        detector = _detector()
        _, placements = detector._pack([(i, _crop(180, 180), 0, 0) for i in range(9)])

        for first in placements:
            for second in placements:
                if first is second:
                    continue
                separated_x = (
                    first.offset_x + first.placed_width <= second.offset_x
                    or second.offset_x + second.placed_width <= first.offset_x
                )
                separated_y = (
                    first.offset_y + first.placed_height <= second.offset_y
                    or second.offset_y + second.placed_height <= first.offset_y
                )
                assert separated_x or separated_y

    def test_le_fond_est_le_gris_neutre_du_letterbox(self) -> None:
        """114 et non 0 : le réseau a vu ce gris à chaque image de son entraînement.

        Du noir serait un signal fort sur une bande entière de l'image.
        """
        detector = _detector()
        tile, _ = detector._pack([(0, _crop(100, 100), 0, 0)])
        assert tile[0, 0].tolist() == [PAD_VALUE] * 3

    def test_le_rapport_d_aspect_est_conserve(self) -> None:
        """Étirer un véhicule déformerait la plaque au-delà de ce que le modèle connaît."""
        detector = _detector()
        _, placements = detector._pack([(0, _crop(300, 100), 0, 0)])
        placement = placements[0]
        assert placement.placed_width / placement.placed_height == pytest.approx(3.0, abs=0.02)


class TestAllerRetourDeCoordonnees:
    def test_une_boite_revient_exactement_a_sa_place(self) -> None:
        """Le test central de tout ce fichier.

        On part d'une boîte *connue* dans le recadrage, on la projette dans la
        mosaïque comme le ferait le réseau, et on exige que le chemin retour rende
        l'originale. C'est l'aller-retour complet : cellule, échelle, origine.
        """
        detector = _detector()
        crop_origin_x, crop_origin_y = 640, 360
        _, placements = detector._pack([(0, _crop(240, 180), crop_origin_x, crop_origin_y)])
        placement = placements[0]

        # Une plaque plausible dans le repère du recadrage.
        expected = BoundingBox(x=60.0, y=120.0, width=100.0, height=25.0)
        # Projetée dans la mosaïque, exactement comme le réseau la verrait.
        scale = placement.scale
        projected = (
            expected.x * scale + placement.offset_x,
            expected.y * scale + placement.offset_y,
            (expected.x + expected.width) * scale + placement.offset_x,
            (expected.y + expected.height) * scale + placement.offset_y,
        )

        recovered = detector._to_crop(placement, *projected)

        assert recovered is not None
        assert recovered.x == pytest.approx(expected.x, abs=0.01)
        assert recovered.y == pytest.approx(expected.y, abs=0.01)
        assert recovered.width == pytest.approx(expected.width, abs=0.01)
        assert recovered.height == pytest.approx(expected.height, abs=0.01)

    def test_la_cellule_est_designee_par_le_centre_de_la_boite(self) -> None:
        """Par le centre et non par un chevauchement.

        Un critère de chevauchement attribuerait une boîte débordant légèrement de sa
        cellule à **deux** véhicules à la fois.
        """
        detector = _detector()
        _, placements = detector._pack([(i, _crop(200, 200), 0, 0) for i in range(4)])

        for placement in placements:
            centre_x = placement.offset_x + placement.placed_width / 2
            centre_y = placement.offset_y + placement.placed_height / 2
            assert detector._locate(placements, centre_x, centre_y) is placement

    def test_une_boite_tombee_dans_la_gouttiere_n_appartient_a_personne(self) -> None:
        """Mieux vaut perdre une détection que l'attribuer au mauvais véhicule."""
        detector = _detector()
        _, placements = detector._pack([(i, _crop(200, 200), 0, 0) for i in range(4)])
        assert detector._locate(placements, 1.0, 1.0) is None

    def test_une_boite_debordant_de_sa_cellule_est_decoupee_aux_bornes(self) -> None:
        """Sans découpage, elle rendrait des coordonnées hors du véhicule.

        Le sérialiseur les publierait telles quelles et le canvas dessinerait un
        rectangle à côté de la voiture.
        """
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 150), 0, 0)])
        placement = placements[0]

        recovered = detector._to_crop(
            placement,
            placement.offset_x - 50.0,
            placement.offset_y - 50.0,
            placement.offset_x + placement.placed_width + 50.0,
            placement.offset_y + placement.placed_height + 50.0,
        )

        assert recovered is not None
        assert recovered.x == 0.0
        assert recovered.y == 0.0
        assert recovered.width == pytest.approx(200.0, abs=1.0)
        assert recovered.height == pytest.approx(150.0, abs=1.0)

    def test_une_boite_entierement_hors_cellule_est_ecartee(self) -> None:
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 150), 0, 0)])
        placement = placements[0]
        assert (
            detector._to_crop(
                placement,
                placement.offset_x - 80.0,
                placement.offset_y - 80.0,
                placement.offset_x - 40.0,
                placement.offset_y - 40.0,
            )
            is None
        )

    def test_l_origine_du_recadrage_est_bien_rajoutee(self) -> None:
        """Le contrat du port : des coordonnées de l'image **complète**.

        Un adaptateur qui oublie de réexprimer rendrait des coordonnées relatives au
        recadrage, plausibles et fausses de plusieurs centaines de pixels.
        """
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 150), 800, 400)])
        placement = placements[0]

        selected = detector._select(
            [(placement, BoundingBox(x=10.0, y=100.0, width=80.0, height=20.0), 0.9)],
            _crop(1920, 1080),
        )

        assert selected[0].box.x == pytest.approx(810.0)
        assert selected[0].box.y == pytest.approx(500.0)


class TestPlausibilite:
    @staticmethod
    def _placement(detector: UltralyticsPlateDetector, width: int = 200, height: int = 160):  # noqa: ANN205
        _, placements = detector._pack([(0, _crop(width, height), 0, 0)])
        return placements[0]

    def test_une_plaque_ordinaire_passe(self) -> None:
        detector = _detector()
        placement = self._placement(detector)
        plate = BoundingBox(x=60.0, y=110.0, width=80.0, height=20.0)
        assert detector._is_plausible(plate, placement)

    def test_une_boite_plus_haute_que_large_est_ecartee(self) -> None:
        """Une plaque est plus large que haute. Verticale, c'est un montant de portière."""
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=60.0, y=110.0, width=20.0, height=40.0), placement
        )

    def test_une_boite_aussi_large_que_le_vehicule_est_ecartee(self) -> None:
        """C'est le véhicule lui-même, pas sa plaque."""
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=0.0, y=110.0, width=198.0, height=30.0), placement
        )

    def test_un_ecusson_est_ecarte(self) -> None:
        """Trop petit par rapport au véhicule pour être sa plaque."""
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=90.0, y=110.0, width=4.0, height=2.0), placement
        )

    def test_un_reflet_de_pare_brise_est_ecarte(self) -> None:
        """Le haut du véhicule ne porte pas de plaque.

        Le garde est très permissif — 12 % de la hauteur — parce qu'un plan plongeant
        sur un camion place la plaque plus haut qu'on ne le croit.
        """
        detector = _detector()
        placement = self._placement(detector)
        assert not detector._is_plausible(
            BoundingBox(x=60.0, y=2.0, width=80.0, height=18.0), placement
        )

    def test_une_plaque_de_moto_passe(self) -> None:
        """~1,4:1 : presque carrée, et parfaitement légitime."""
        detector = _detector()
        placement = self._placement(detector)
        assert detector._is_plausible(
            BoundingBox(x=80.0, y=120.0, width=28.0, height=20.0), placement
        )


class TestSelection:
    def test_seule_la_meilleure_est_gardee_par_defaut(self) -> None:
        """Un véhicule a **une** plaque visible.

        En garder plusieurs multiplie les rectangles à l'écran et le coût d'OCR sans
        rien apprendre — et laisse le vote arbitrer entre deux lectures d'objets
        différents.
        """
        detector = _detector()
        _, placements = detector._pack([(0, _crop(200, 160), 0, 0)])
        placement = placements[0]

        selected = detector._select(
            [
                (placement, BoundingBox(x=10.0, y=110.0, width=80.0, height=20.0), 0.42),
                (placement, BoundingBox(x=60.0, y=112.0, width=82.0, height=21.0), 0.91),
                (placement, BoundingBox(x=20.0, y=118.0, width=70.0, height=18.0), 0.55),
            ],
            _crop(1920, 1080),
        )

        assert len(selected) == 1
        assert selected[0].score == pytest.approx(0.91)

    def test_le_plafond_par_vehicule_est_reglable(self) -> None:
        detector = _detector(geometry=PlateGeometry(max_per_vehicle=2))
        _, placements = detector._pack([(0, _crop(200, 160), 0, 0)])
        placement = placements[0]

        selected = detector._select(
            [
                (placement, BoundingBox(x=10.0, y=110.0, width=80.0, height=20.0), 0.42),
                (placement, BoundingBox(x=60.0, y=112.0, width=82.0, height=21.0), 0.91),
                (placement, BoundingBox(x=20.0, y=118.0, width=70.0, height=18.0), 0.55),
            ],
            _crop(1920, 1080),
        )

        assert [round(detection.score, 2) for detection in selected] == [0.91, 0.55]


class _FakeBoxes:
    """Le strict nécessaire de `Results.boxes` : `xyxy`, `conf`, et une longueur."""

    def __init__(self, rows: list[tuple[float, float, float, float, float]]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def xyxy(self) -> _FakeTensor:
        return _FakeTensor(np.array([row[:4] for row in self._rows], dtype=np.float32))

    @property
    def conf(self) -> _FakeTensor:
        return _FakeTensor(np.array([row[4] for row in self._rows], dtype=np.float32))


class _FakeTensor:
    """Imite juste assez de torch pour que `.cpu().numpy()` traverse."""

    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def cpu(self) -> _FakeTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self._array


class _FakeResult:
    def __init__(self, rows: list[tuple[float, float, float, float, float]]) -> None:
        self.boxes = _FakeBoxes(rows)


class _RecordingYolo:
    """Un modèle qui note **comment** on l'appelle, pas ce qu'on lui demande de voir.

    C'est le seul moyen de tester un coût : le résultat d'une passe étranglée et
    celui d'une passe séquentielle sont identiques, donc aucune assertion sur les
    boîtes ne pourrait distinguer une inférence par véhicule d'une seule pour tous.
    """

    def __init__(self, rows: list[tuple[float, float, float, float, float]] | None = None) -> None:
        self.calls: list[int] = []
        #: Côté d'entrée demandé à chaque appel. C'est le premier poste du budget
        #: quand l'ANPR tourne (73 % sur une scène dense) : un réglage qui
        #: n'atteindrait pas `predict` se lirait comme un levier sans effet.
        self.sizes: list[object] = []
        #: Forme de la source de chaque appel, mosaïque comprise : c'est elle qui dit
        #: qu'une tuile a bien été construite au côté demandé.
        self.shapes: list[tuple[int, ...]] = []
        self._rows = rows if rows is not None else [(10.0, 30.0, 70.0, 50.0, 0.9)]

    def predict(self, source: object, **kwargs: object) -> list[_FakeResult]:
        self.sizes.append(kwargs.get("imgsz"))
        if isinstance(source, list):
            self.calls.append(len(source))
            return [_FakeResult(list(self._rows)) for _ in source]
        # Chemin mosaïque : une seule image, un seul résultat.
        self.calls.append(1)
        self.shapes.append(getattr(source, "shape", ()))
        return [_FakeResult(list(self._rows))]


class TestUnSeulLotPourToutesLesPistes:
    """Le chemin par défaut paie **un** `predict`, pas un par véhicule.

    Ce n'était pas le cas jusqu'ici : `detect_many` découpait en paquets de `side²`
    recadrages, et le défaut `side = 1` faisait donc un paquet — donc un appel — par
    piste. Mesuré sur vidéo réelle à 3,7 véhicules par image, corriger cela vaut
    **217 ms → 107 ms par image**, à détections rigoureusement équivalentes (240
    véhicules, aucune plaque gagnée ni perdue, IoU minimale de 0,943 sur les boîtes
    appariées — l'écart sub-pixel vient du redimensionnement de mosaïque que le lot
    n'a plus à faire).

    Une régression ici ne changerait **aucun chiffre affiché** : elle diviserait
    seulement la cadence par deux, ce que personne ne relie spontanément à ce
    fichier. D'où un test qui compte les appels.
    """

    @staticmethod
    def _prepared(model: _RecordingYolo, **kwargs: object) -> UltralyticsPlateDetector:
        detector = _detector(**kwargs)
        detector._model = model
        return detector

    def test_cinq_vehicules_ne_coutent_qu_une_inference(self) -> None:
        model = _RecordingYolo()
        detector = self._prepared(model)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        boxes = [
            BoundingBox(x=float(index * 200), y=0.0, width=180.0, height=120.0)
            for index in range(5)
        ]

        detector.detect_many(image, boxes)

        assert model.calls == [5]

    def test_le_cote_d_entree_configure_atteint_l_inference(self) -> None:
        """**Le premier poste du budget dès que l'ANPR tourne.**

        Mesuré sur une scène dense réelle : 73 % du temps par image, et un coût
        linéaire en nombre de recadrages — chaque véhicule paie une inférence
        complète. Le côté de l'entrée est donc le seul levier qui n'exige pas d'en
        détecter moins : 141 ms par appel à 640, 56,8 à 320 sur les mêmes huit
        recadrages.

        Un réglage qui n'atteindrait pas `predict` serait le pire des deux mondes :
        l'opérateur croirait avoir changé de régime et mesurerait l'ancien.
        """
        model = _RecordingYolo()
        detector = self._prepared(model, net_size=320)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        detector.detect_many(image, [BoundingBox(x=0.0, y=0.0, width=180.0, height=120.0)])

        assert model.sizes == [320]

    def test_la_mosaique_est_construite_au_cote_demande(self) -> None:
        """Les deux chemins doivent lire le **même** côté.

        La tuile est une image réelle : la bâtir à 640 pour l'inférer à 320
        rétrécirait chaque cellule d'un facteur deux sans que rien ne le dise, et
        détruirait le rappel que la mosaïque essaie déjà de préserver (ADR 0008).
        """
        model = _RecordingYolo()
        detector = self._prepared(model, mosaic_side=2, net_size=320)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        detector.detect_many(image, [BoundingBox(x=0.0, y=0.0, width=180.0, height=120.0)])

        assert model.sizes == [320]
        assert model.shapes == [(320, 320, 3)]

    def test_le_defaut_reste_la_resolution_d_entrainement(self) -> None:
        """640 tant que personne ne demande autre chose : on ne troque pas du rappel
        contre du débit en silence."""
        model = _RecordingYolo()
        detector = self._prepared(model)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        detector.detect_many(image, [BoundingBox(x=0.0, y=0.0, width=180.0, height=120.0)])

        assert model.sizes == [NET_SIZE]

    def test_le_lot_est_borne_pour_ne_pas_saturer_la_carte(self) -> None:
        """Une intersection chargée ne doit pas faire déborder une petite carte.

        Une erreur de mémoire GPU ferait échouer **toute** la passe ANPR de l'image,
        pas seulement le véhicule de trop.
        """
        model = _RecordingYolo()
        detector = self._prepared(model)
        image = np.zeros((2000, 4000, 3), dtype=np.uint8)
        boxes = [
            BoundingBox(
                x=float(index % 20 * 190), y=float(index // 20 * 190), width=180.0, height=180.0
            )
            for index in range(MAX_BATCH + 4)
        ]

        detector.detect_many(image, boxes)

        assert model.calls == [MAX_BATCH, 4]

    def test_la_boite_revient_dans_le_repere_de_l_image_complete(self) -> None:
        """Le lot supprime la mosaïque : il ne doit pas supprimer le retour au repère.

        Le modèle rend `(10, 30, 70, 50)` dans le repère du **recadrage** ; le
        véhicule commence à `x=200`, donc la plaque est à `x=210` dans l'image.
        """
        model = _RecordingYolo()
        detector = self._prepared(model)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        found = detector.detect_many(
            image, [BoundingBox(x=200.0, y=100.0, width=180.0, height=120.0)]
        )

        assert len(found[0]) == 1
        assert found[0][0].box.x == pytest.approx(210.0)
        assert found[0][0].box.y == pytest.approx(130.0)
        assert found[0][0].box.width == pytest.approx(60.0)

    def test_une_boite_invraisemblable_est_ecartee_sur_ce_chemin_aussi(self) -> None:
        """Le filtre du domaine ne doit pas être perdu en route.

        Sans lui, la boîte du véhicule entier repartirait en OCR — les 112 fausses
        détections sur 538 d'ADR 0008.
        """
        model = _RecordingYolo(rows=[(0.0, 0.0, 180.0, 120.0, 0.87)])
        detector = self._prepared(model)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        found = detector.detect_many(image, [BoundingBox(x=0.0, y=0.0, width=180.0, height=120.0)])

        assert found == ((),)

    def test_la_mosaique_garde_son_propre_chemin(self) -> None:
        """`mosaic_side > 1` reste l'empaquetage d'ADR 0008, intact.

        Elle échange du rappel contre de la vitesse sans GPU, et ce n'est pas le même
        arbitrage : le lot, lui, ne troque rien.
        """
        model = _RecordingYolo()
        detector = self._prepared(model, mosaic_side=2)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        boxes = [
            BoundingBox(x=float(index * 200), y=0.0, width=180.0, height=120.0)
            for index in range(4)
        ]

        detector.detect_many(image, boxes)

        # Quatre recadrages dans une grille 2×2 : une image empaquetée, un appel.
        assert model.calls == [1]


class TestDegradationGracieuse:
    def test_un_modele_absent_rend_un_tuple_par_boite(self) -> None:
        """Le contrat d'alignement positionnel tient même quand rien ne fonctionne.

        Rendre une liste plus courte obligerait l'appelant à deviner à quelle piste
        appartient quel résultat.
        """
        detector = _detector()
        boxes = [BoundingBox(x=0.0, y=0.0, width=100.0, height=100.0)] * 3
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        assert detector.detect_many(image, boxes) == ((), (), ())

    def test_un_lot_vide_rend_un_lot_vide(self) -> None:
        """`np.stack([])` lève : le cas vide se traite avant tout le reste."""
        detector = _detector()
        assert detector.detect_many(np.zeros((10, 10, 3), dtype=np.uint8), []) == ()

    def test_deux_appels_ne_journalisent_pas_deux_fois(self) -> None:
        """Le latch `_checked` : sinon des milliers de lignes identiques par vidéo."""
        detector = _detector()
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        box = BoundingBox(x=0.0, y=0.0, width=100.0, height=100.0)
        assert detector.detect(image, box) == ()
        assert detector.detect(image, box) == ()
        assert detector._checked is True

    def test_un_recadrage_minuscule_ne_coute_aucune_inference(self) -> None:
        """Sous 32 px, l'inférence coûterait sans jamais rien trouver."""
        detector = _detector()
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        assert detector.detect(image, BoundingBox(x=0.0, y=0.0, width=8.0, height=8.0)) == ()
