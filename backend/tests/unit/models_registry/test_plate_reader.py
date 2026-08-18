"""L'adaptateur de lecture — **sans poids et sans onnxruntime**.

C'est possible parce que le décodage, la mise en tenseur et la lecture du dictionnaire
sont des fonctions de module pures : `onnxruntime` n'est importé que dans
`_ensure_loaded`. Ce n'est pas un choix de style, c'est ce qui rend ce fichier
exécutable en CI.

Les trois tests les plus rentables, chacun sur un mode de panne qui ne lève rien :

- `test_la_confiance_ignore_la_traine_de_blancs` — moyenner les quarante pas de temps
  au lieu des seuls pas retenus tirerait toute confiance vers 0,95 et rendrait
  n'importe quel seuil inopérant ;
- `test_le_remplissage_vaut_zero_dans_l_espace_normalise` — étirer au lieu de remplir
  est la première cause de « le modèle tourne et rend du charabia » ;
- `test_l_indice_zero_est_le_blanc_du_ctc` — l'oublier décale tout l'alphabet d'un
  cran, ce qui produit des chaînes lisibles et **entièrement fausses**.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from traffic_analysis.features.counting.application.dto import BoundingBox
from traffic_analysis.features.models_registry.infrastructure.plate_reader import (
    MIN_VARIANT_WIDTH_PX,
    REC_HARD_MAX_WIDTH,
    REC_HEIGHT,
    REC_MAX_WIDTH,
    REC_MIN_WIDTH,
    REC_WIDTH_QUANTUM,
    OnnxPlateReader,
    Reading,
    as_probabilities,
    batch_width,
    charset_from_lines,
    charset_from_metadata,
    ctc_greedy_decode,
    deskew,
    estimate_skew,
    target_width,
    to_tensor,
)

if TYPE_CHECKING:
    from pathlib import Path

    import numpy.typing as npt

#: Alphabet minuscule : indice 0 = blanc, puis A, B, C, D.
CHARSET = ("", "A", "B", "C", "D")


def _probs(rows: list[list[float]]) -> np.ndarray:
    """Un lot d'un élément, de forme `(1, T, C)`."""
    return np.array([rows], dtype=np.float32)


class TestCharsetFromLines:
    def test_l_indice_zero_est_le_blanc_du_ctc(self) -> None:
        """Le dictionnaire de PaddleOCR ne le contient pas : il est implicite.

        L'oublier décale tout l'alphabet d'un cran. Aucune exception, aucun journal,
        et des chaînes parfaitement lisibles qui désignent d'autres caractères.
        """
        charset = charset_from_lines(["A", "B", "C"])
        assert charset[0] == ""
        assert charset == ("", "A", "B", "C")

    def test_une_ligne_qui_ne_contient_qu_un_espace_est_conservee(self) -> None:
        """**Le bug trouvé par les vrais poids**, et il ne levait rien.

        `en_dict.txt` contient une ligne dont le seul contenu est un espace — c'est un
        caractère de l'alphabet, pas un blanc de mise en forme. Un filtre `line.strip()`
        la supprimait, et l'alphabet tombait à 95 entrées là où le modèle en rend 97.

        Le garde de cohérence transformait cela en « OCR indisponible » plutôt qu'en
        plaques fausses — la bonne panne — mais l'OCR n'aurait jamais fonctionné.
        """
        charset = charset_from_lines(["A", " ", "B"])
        assert charset == ("", "A", " ", "B")

    def test_la_taille_vaut_toutes_les_lignes_plus_le_blanc(self) -> None:
        lines = ["A", "B", " ", "D", "E"]
        assert len(charset_from_lines(lines)) == len(lines) + 1

    def test_seule_la_fin_de_ligne_est_retiree(self) -> None:
        """`rstrip("\\r\\n")` et non `strip()` — comme `BaseRecLabelDecode`."""
        assert charset_from_lines(["A\r\n", " \n", "B"]) == ("", "A", " ", "B")


class _FakeOutput:
    """Sortie ONNX minimale : seule sa dernière dimension nous intéresse."""

    def __init__(self, classes: object) -> None:
        self.shape = [None, None, classes]


class _FakeMeta:
    def __init__(self, character: str | None) -> None:
        self.custom_metadata_map = {} if character is None else {"character": character}


class _FakeSession:
    """Session ONNX minimale.

    `character=None` imite un export **sans** métadonnées : `get_modelmeta` lève,
    exactement comme un runtime qui n'en expose pas. C'est le cas de repli qu'il faut
    couvrir, puisque c'est celui de tout export non PaddlePaddle.
    """

    def __init__(self, classes: object, character: str | None = None) -> None:
        self._classes = classes
        self._character = character

    def get_outputs(self) -> list[_FakeOutput]:
        return [_FakeOutput(self._classes)]

    def get_modelmeta(self) -> _FakeMeta:
        if self._character is None:
            msg = "cet export ne porte pas de métadonnées"
            raise RuntimeError(msg)
        return _FakeMeta(self._character)


class TestResolveCharset:
    """L'alignement de l'alphabet sur la sortie du modèle.

    Testable sans onnxruntime grâce à une session factice : la fonction ne lit que la
    dernière dimension de sortie. C'est ce qui permet de couvrir en CI le mode de panne
    le plus dangereux du lot.
    """

    def test_un_alphabet_de_la_bonne_taille_passe_tel_quel(self, tmp_path: Path) -> None:
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        # 3 lignes + blanc = 4
        assert reader._resolve_charset(_FakeSession(4), ["A", "B", "C"]) == ("", "A", "B", "C")

    def test_l_espace_est_ajoute_quand_il_manque_exactement_une_classe(
        self, tmp_path: Path
    ) -> None:
        """Le cas réel : `en_dict.txt` (95) + blanc = 96, le modèle en rend 97.

        PaddleOCR ajoute l'espace en **fin** d'alphabet quand le modèle a été entraîné
        avec `use_space_char`, et le fichier ne le contient pas. On ne peut donc pas le
        savoir d'avance — mais le déduire de l'écart est vérifiable, et l'espace en fin
        ne décale rien de ce qui précède.
        """
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        assert reader._resolve_charset(_FakeSession(5), ["A", "B", "C"]) == (
            "",
            "A",
            "B",
            "C",
            " ",
        )

    def test_un_ecart_de_deux_est_un_refus(self, tmp_path: Path) -> None:
        """On n'ajoute que ce qui fait correspondre **exactement**.

        Deux classes de trop, c'est un autre export — typiquement le modèle chinois à
        6625 classes lu avec un dictionnaire latin. Le refus est ce qui évite des
        plaques fausses et parfaitement plausibles.
        """
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        assert reader._resolve_charset(_FakeSession(6), ["A", "B", "C"]) is None

    def test_un_alphabet_trop_grand_est_un_refus(self, tmp_path: Path) -> None:
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        assert reader._resolve_charset(_FakeSession(2), ["A", "B", "C"]) is None

    def test_une_dimension_dynamique_laisse_passer(self, tmp_path: Path) -> None:
        """Refuser un modèle valide serait pire : le script a déjà fait le contrôle."""
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        assert reader._resolve_charset(_FakeSession("classes"), ["A", "B"]) == ("", "A", "B")


class TestAlphabetGraveDansLeModele:
    """L'alphabet des métadonnées fait foi, parce que lui ne peut pas se désynchroniser.

    PaddlePaddle grave la liste des caractères dans le `.onnx` sous la clé
    `character`. Le fichier de dictionnaire, lui, est un **second** artefact : on peut
    le remplacer, le tronquer, ou le confondre avec celui d'un autre export — et ADR
    0007 raconte ce que ça coûte, parce qu'un décalage d'alphabet ne lève rien. Il rend
    des plaques fausses et parfaitement plausibles.
    """

    def test_la_chaine_gravee_devient_un_alphabet_avec_son_blanc(self) -> None:
        assert charset_from_metadata("A\nB\nC") == ("", "A", "B", "C")

    def test_le_saut_de_ligne_final_ne_cree_pas_un_caractere_fantome(self) -> None:
        """Le vrai modèle termine sa chaîne par `\\n`.

        Un `split` naïf rend alors une dernière entrée vide, l'alphabet compte un
        caractère de trop, et le contrôle de cohérence **rejette un modèle
        parfaitement valide** — une panne d'autant plus déroutante qu'elle accuse les
        poids.
        """
        assert charset_from_metadata("A\nB\n") == ("", "A", "B")

    def test_l_espace_grave_est_un_caractere_comme_un_autre(self) -> None:
        """Même piège que la ligne d'espace de `en_dict.txt`, à la source cette fois."""
        assert charset_from_metadata("A\n \nB\n") == ("", "A", " ", "B")

    def test_le_modele_l_emporte_sur_un_fichier_qui_diverge(self, tmp_path: Path) -> None:
        """Le fichier reste exigé — un opérateur doit pouvoir *voir* l'alphabet — mais
        il devient une seconde opinion, pas l'autorité."""
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        resolved = reader._resolve_charset(_FakeSession(4, character="X\nY\nZ\n"), ["A", "B", "C"])
        assert resolved == ("", "X", "Y", "Z")

    def test_l_espace_de_use_space_char_s_applique_aussi_a_l_alphabet_grave(
        self, tmp_path: Path
    ) -> None:
        """C'est l'arithmétique du vrai modèle : 95 gravés + blanc + espace = 97."""
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        resolved = reader._resolve_charset(_FakeSession(5, character="X\nY\nZ\n"), ["A", "B", "C"])
        assert resolved == ("", "X", "Y", "Z", " ")

    def test_un_alphabet_grave_incoherent_retombe_sur_le_fichier(self, tmp_path: Path) -> None:
        """Assez anormal pour ne pas décider tout seul.

        Si les métadonnées ne collent pas non plus à la sortie, elles n'ont pas plus
        d'autorité que le fichier : on retombe sur le chemin d'origine, qui sait
        refuser.
        """
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        resolved = reader._resolve_charset(
            _FakeSession(4, character="V\nW\nX\nY\nZ\n"), ["A", "B", "C"]
        )
        assert resolved == ("", "A", "B", "C")

    def test_un_export_sans_metadonnees_utilise_le_fichier(self, tmp_path: Path) -> None:
        """Le cas de tout export non PaddlePaddle. Ne doit rien casser."""
        reader = OnnxPlateReader(tmp_path / "m.onnx", tmp_path / "c.txt")
        assert reader._resolve_charset(_FakeSession(4), ["A", "B", "C"]) == ("", "A", "B", "C")


class TestLargeurDeLot:
    """La largeur du tenseur est négociée, pas décrétée.

    Une plaque européenne fait 4,7:1, donc 226 px à 48 px de haut. Calculer les 320
    colonnes de PP-OCR revient à payer 40 % de convolutions pour du remplissage. Et
    dans l'autre sens, une plaque plus large que 6,7:1 était **comprimée** à 320, ce
    qui écrase les glyphes — le graphe accepte plus large, on le lui donne.
    """

    def test_la_largeur_suit_le_rapport_d_aspect(self) -> None:
        # 4,7:1 à 48 px de haut.
        assert target_width(470, 100, REC_HARD_MAX_WIDTH) == 226

    def test_une_vignette_minuscule_a_quand_meme_de_quoi_coder_sept_caracteres(self) -> None:
        """Sous ~13 pas de temps, le CTC ne *peut pas* écrire une plaque.

        Il lui faut un blanc entre deux caractères répétés, donc `2n - 1` pas au
        minimum. Un plancher sur la largeur est ce qui l'en empêche.
        """
        assert target_width(10, 100, REC_HARD_MAX_WIDTH) == REC_MIN_WIDTH

    def test_la_largeur_est_plafonnee(self) -> None:
        assert target_width(5000, 100, REC_MAX_WIDTH) == REC_MAX_WIDTH

    def test_le_lot_prend_le_maximum_arrondi_au_quantum(self) -> None:
        """Quelques formes distinctes plutôt qu'une par lot : onnxruntime réutilise
        alors ses plans d'exécution au lieu d'en recompiler un à chaque frame."""
        width = batch_width([100, 226, 180], REC_HARD_MAX_WIDTH)
        assert width == 256
        assert width % REC_WIDTH_QUANTUM == 0

    def test_un_lot_vide_rend_le_plancher(self) -> None:
        assert batch_width([], REC_HARD_MAX_WIDTH) == REC_MIN_WIDTH


class TestRedressement:
    """Le redressement corrige la rotation **dans le plan**, et seulement elle.

    Une plaque vue de trois quarts demanderait ses quatre coins ; le détecteur rend
    une boîte alignée sur les axes, donc ses bords ne portent **aucune** information
    d'angle. Seul le contenu en porte — d'où l'estimation par les caractères.
    """

    @staticmethod
    def _plate(angle: float = 0.0) -> np.ndarray:
        """Une bande claire portant quatre barres sombres, tournée d'`angle`."""
        import cv2

        image = np.full((60, 240), 230, dtype=np.uint8)
        for index in range(4):
            image[20:40, 30 + index * 45 : 50 + index * 45] = 20
        if angle == 0.0:
            return image
        matrix = cv2.getRotationMatrix2D((120.0, 30.0), angle, 1.0)
        return cv2.warpAffine(image, matrix, (240, 60), borderValue=230)

    def test_une_plaque_droite_ne_declenche_rien(self) -> None:
        """Redresser coûte une interpolation qui adoucit les traits.

        En dessous de l'angle plancher, on perdrait de la netteté pour rien.
        """
        assert estimate_skew(self._plate(0.0)) == 0.0

    def test_une_inclinaison_franche_est_mesuree_dans_le_bon_sens(self) -> None:
        measured = estimate_skew(self._plate(8.0))
        assert measured != 0.0
        assert abs(abs(measured) - 8.0) < 3.0

    def test_le_redressement_ramene_l_angle_vers_zero(self) -> None:
        """Le seul test qui prouve la **convention de signe**.

        Se tromper de signe redresse dans le mauvais sens : la plaque ressort deux
        fois plus penchée qu'elle n'est entrée, sans que rien ne le signale.
        """
        tilted = self._plate(8.0)
        angle = estimate_skew(tilted)
        straightened = deskew(tilted, angle)
        assert abs(estimate_skew(straightened)) < abs(angle)

    def test_un_angle_absurde_est_ignore(self) -> None:
        """Au-delà du plafond, l'estimation s'est accrochée à autre chose — une ombre,
        un bord de carrosserie — et redresser de 40° détruirait la vignette."""
        assert estimate_skew(self._plate(40.0)) == 0.0

    def test_une_vignette_trop_petite_ne_rend_aucun_angle(self) -> None:
        assert estimate_skew(np.zeros((4, 10), dtype=np.uint8)) == 0.0

    def test_le_redressement_agrandit_le_cadre_plutot_que_de_couper(self) -> None:
        """Couper les coins amputerait le premier et le dernier caractère."""
        straightened = deskew(self._plate(0.0), 10.0)
        assert straightened.shape[0] > 60
        assert straightened.shape[1] > 240


class TestChoixDeVariante:
    """Entre deux prétraitements, c'est la confiance **cumulée** qui départage."""

    def test_la_confiance_cumulee_prefere_la_lecture_la_plus_complete(self) -> None:
        """Trois caractères à 0,99 contre sept à 0,85.

        La moyenne préfère la première — alors qu'elle a manqué quatre glyphes. La
        somme (2,97 contre 5,95) préfère celle qui a lu le plus, aussi sûrement, et
        sans qu'on ait à inventer un facteur de longueur.
        """
        court = Reading(text="ABC", score=0.99, char_scores=(0.99, 0.99, 0.99))
        complet = Reading(text="AB123CD", score=0.85, char_scores=(0.85,) * 7)
        assert complet.total > court.total
        assert complet.score < court.score


class TestRognageDeGauche:
    """Les variantes rognées à gauche, et le fait qu'elles ne retirent jamais rien.

    Elles existent pour un caractère de tête absent de l'alphabet du modèle — un
    idéogramme de province chinois : le CTC doit émettre quelque chose pour ces pas
    de temps, et ce quelque chose **mange la lettre voisine**. Mesuré sur 40
    vignettes de vraie circulation, la chaîne rendait `96886` pour `苏A·96886`, à
    0,90 de confiance ; le même recadrage privé de son bord gauche rend `A96886` à
    0,97.

    Ces tests portent sur `_prepare`, qui n'a besoin ni de poids ni d'onnxruntime :
    `_clahe` reste `None` tant que le modèle n'est pas chargé, et la chaîne de
    prétraitement le supporte exprès.
    """

    @staticmethod
    def _reader(tmp_path: Path, **kwargs: object) -> OnnxPlateReader:
        return OnnxPlateReader(tmp_path / "absent.onnx", tmp_path / "absent.txt", **kwargs)  # type: ignore[arg-type]

    @staticmethod
    def _image() -> npt.NDArray[np.uint8]:
        """Une plaque de synthèse dont le bord gauche est **noir** et le reste clair.

        C'est ce contraste qui rend le rognage vérifiable sans lire de texte : une
        variante qui a réellement coupé son bord gauche ne contient plus de colonne
        sombre.
        """
        image = np.full((60, 200, 3), 200, dtype=np.uint8)
        image[10:50, 10:28] = 0
        return image

    BOX = BoundingBox(x=10.0, y=10.0, width=180.0, height=40.0)

    def test_une_variante_de_plus_par_fraction(self, tmp_path: Path) -> None:
        sans = self._reader(tmp_path, left_insets=())
        avec = self._reader(tmp_path, left_insets=(0.14, 0.22))

        base = sans._prepare(self._image(), self.BOX)
        etendu = avec._prepare(self._image(), self.BOX)

        assert len(etendu) == len(base) + 2

    def test_la_variante_a_bien_perdu_son_bord_gauche(self, tmp_path: Path) -> None:
        """Le contrôle qui vaut la mesure : la colonne sombre a disparu."""
        reader = self._reader(tmp_path, left_insets=(0.30,))
        variants = reader._prepare(self._image(), self.BOX)

        # La dernière variante est celle du rognage : 30 % de 180 px = 54 px, donc
        # au-delà des 18 px de bande sombre.
        assert variants[0].min() == 0
        assert variants[-1].min() > 0

    def test_sans_fraction_le_comportement_est_celui_d_avant(self, tmp_path: Path) -> None:
        """L'ajout doit pouvoir être annulé exactement, pour comparer au banc."""
        reader = self._reader(tmp_path, left_insets=())
        variants = reader._prepare(self._image(), self.BOX)

        assert len(variants) == 2  # base + encart, pas d'angle sur une image droite

    def test_le_commutateur_maitre_des_variantes_les_coupe_aussi(self, tmp_path: Path) -> None:
        """`variants=False` doit tout couper, sinon « désactivé » ne compare rien."""
        reader = self._reader(tmp_path, variants=False, left_insets=(0.14, 0.22))
        assert len(reader._prepare(self._image(), self.BOX)) == 1

    def test_les_fractions_absurdes_sont_ecartees_a_la_construction(self, tmp_path: Path) -> None:
        """Une fraction nulle donnerait une copie de la base : une inférence pour rien."""
        reader = self._reader(tmp_path, left_insets=(0.0, -0.2, 0.95, 1.5, 0.14, 0.14))
        assert reader._left_insets == (0.14,)

    def test_une_vignette_trop_etroite_ne_donne_pas_de_variante_degeneree(
        self, tmp_path: Path
    ) -> None:
        """Rogner 60 % d'une vignette de 70 px laisserait 28 colonnes : inexploitable."""
        image = np.full((30, 80, 3), 180, dtype=np.uint8)
        reader = self._reader(tmp_path, left_insets=(0.60,))
        box = BoundingBox(x=0.0, y=0.0, width=70.0, height=24.0)

        variants = reader._prepare(image, box)
        assert all(variant.shape[1] >= MIN_VARIANT_WIDTH_PX for variant in variants)

    def test_toutes_les_variantes_sortent_en_trois_canaux(self, tmp_path: Path) -> None:
        """La tête de reconnaissance attend `(3, 48, W)` : un gris planterait le lot."""
        reader = self._reader(tmp_path, left_insets=(0.14, 0.22))
        for variant in reader._prepare(self._image(), self.BOX):
            assert variant.ndim == 3
            assert variant.shape[2] == 3
            assert variant.dtype == np.uint8


class TestAsProbabilities:
    def test_des_probabilites_traversent_inchangees(self) -> None:
        already = _probs([[0.1, 0.7, 0.1, 0.05, 0.05]])
        assert np.allclose(as_probabilities(already), already)

    def test_des_logits_bruts_sont_normalises(self) -> None:
        logits = _probs([[1.0, 8.0, 2.0, 0.5, 0.5]])
        result = as_probabilities(logits)
        assert result.sum(axis=-1) == pytest.approx(1.0)
        assert result.max() < 1.0
        assert int(result.argmax()) == 1

    def test_des_logits_extremes_ne_produisent_aucun_avertissement(self) -> None:
        """La forme stable, vérifiée gratuitement par `filterwarnings = ["error"]`.

        Un `exp` sur des logits bruts émettrait un `RuntimeWarning: overflow`, qui fait
        échouer toute la suite. Ce test n'a donc pas besoin d'assertion sur
        l'avertissement : sa simple exécution en est une.
        """
        result = as_probabilities(_probs([[900.0, -900.0, 0.0, 1e5, -1e5]]))
        assert result.sum(axis=-1) == pytest.approx(1.0)
        assert np.isfinite(result).all()


class TestCtcGreedyDecode:
    def test_les_repetitions_consecutives_sont_effondrees(self) -> None:
        decoded = ctc_greedy_decode(
            _probs(
                [
                    [0.0, 0.9, 0.0, 0.0, 0.1],  # A
                    [0.0, 0.9, 0.0, 0.0, 0.1],  # A répété → un seul A
                    [0.0, 0.0, 0.9, 0.0, 0.1],  # B
                ]
            ),
            CHARSET,
        )
        assert decoded[0].text == "AB"

    def test_les_blancs_sont_supprimes(self) -> None:
        decoded = ctc_greedy_decode(
            _probs(
                [
                    [0.9, 0.05, 0.0, 0.0, 0.05],  # blanc
                    [0.0, 0.9, 0.0, 0.0, 0.1],  # A
                    [0.9, 0.05, 0.0, 0.0, 0.05],  # blanc
                ]
            ),
            CHARSET,
        )
        assert decoded[0].text == "A"

    def test_un_blanc_separateur_preserve_un_double_caractere(self) -> None:
        """C'est ce qui impose l'ordre des deux effondrements.

        Effondrer les blancs d'abord collerait les deux A et rendrait `AB` au lieu de
        `AAB` : le blanc intercalaire est précisément ce qui les distingue.
        """
        decoded = ctc_greedy_decode(
            _probs(
                [
                    [0.0, 0.9, 0.0, 0.0, 0.1],  # A
                    [0.9, 0.05, 0.0, 0.0, 0.05],  # blanc séparateur
                    [0.0, 0.9, 0.0, 0.0, 0.1],  # A de nouveau
                    [0.0, 0.0, 0.9, 0.0, 0.1],  # B
                ]
            ),
            CHARSET,
        )
        assert decoded[0].text == "AAB"

    def test_la_confiance_ignore_la_traine_de_blancs(self) -> None:
        """Le test le plus rentable de tout l'adaptateur.

        Deux caractères à 0,60 suivis de six blancs à 0,99. La confiance attendue est
        **0,60** — celle des pas retenus. Moyenner les huit pas donnerait ~0,89, et
        n'importe quel seuil de publication cesserait de vouloir dire quoi que ce soit.
        """
        rows = [
            [0.0, 0.60, 0.20, 0.10, 0.10],  # A à 0,60
            [0.0, 0.20, 0.60, 0.10, 0.10],  # B à 0,60
        ]
        rows += [[0.99, 0.0025, 0.0025, 0.0025, 0.0025]] * 6

        decoded = ctc_greedy_decode(_probs(rows), CHARSET)

        assert decoded[0].text == "AB"
        assert decoded[0].score == pytest.approx(0.60)

    def test_une_sortie_entierement_blanche_rend_une_chaine_vide(self) -> None:
        decoded = ctc_greedy_decode(_probs([[1.0, 0.0, 0.0, 0.0, 0.0]] * 4), CHARSET)
        assert (decoded[0].text, decoded[0].score) == ("", 0.0)

    def test_un_indice_hors_dictionnaire_est_ignore_plutot_que_de_lever(self) -> None:
        """Le contrôle de cohérence est en amont ; ici on ne casse pas un comptage."""
        wide = np.zeros((1, 2, 8), dtype=np.float32)
        wide[0, 0, 7] = 1.0  # indice 7, hors d'un dictionnaire de 5 entrées
        wide[0, 1, 1] = 1.0  # A
        assert ctc_greedy_decode(wide, CHARSET)[0].text == "A"

    def test_le_lot_rend_un_element_par_ligne(self) -> None:
        batch = np.zeros((3, 2, 5), dtype=np.float32)
        batch[:, :, 0] = 1.0
        assert len(ctc_greedy_decode(batch, CHARSET)) == 3


class TestToTensor:
    def test_la_forme_et_le_type_attendus_par_la_tete(self) -> None:
        crop = np.full((20, 60, 3), 128, dtype=np.uint8)
        tensor = to_tensor(crop)
        assert tensor.shape == (3, REC_HEIGHT, REC_MAX_WIDTH)
        assert tensor.dtype == np.float32

    def test_les_valeurs_restent_dans_la_plage_normalisee(self) -> None:
        crop = np.zeros((20, 60, 3), dtype=np.uint8)
        crop[:, :30] = 255
        tensor = to_tensor(crop)
        assert tensor.min() >= -1.0
        assert tensor.max() <= 1.0

    def test_le_remplissage_vaut_zero_dans_l_espace_normalise(self) -> None:
        """Zéro **normalisé**, pas du noir normalisé — qui vaudrait −1,0.

        Du noir rempli avant normalisation ferait porter un signal fort à la dizaine de
        pas de temps de la zone vide, au lieu de rien.
        """
        crop = np.zeros((48, 48, 3), dtype=np.uint8)  # noir : normalisé à −1,0
        tensor = to_tensor(crop)

        # 48×48 → 48 px de large sur les 320 : tout ce qui suit est du remplissage.
        assert tensor[:, :, :48].min() == pytest.approx(-1.0)
        assert np.count_nonzero(tensor[:, :, 48:]) == 0

    def test_le_rapport_d_aspect_est_conserve_et_non_etire(self) -> None:
        """Étirer à 320 déforme les glyphes au-delà de ce que le modèle a vu.

        Une vignette de 96×48 doit occuper 96 colonnes, pas 320. La preuve est que la
        colonne 200 reste du remplissage exact.
        """
        crop = np.full((48, 96, 3), 200, dtype=np.uint8)
        tensor = to_tensor(crop)

        assert np.count_nonzero(tensor[:, :, :96])
        assert np.count_nonzero(tensor[:, :, 200]) == 0

    def test_une_vignette_plus_large_que_la_cible_est_bornee(self) -> None:
        """Pas de débordement : `320` est un plafond, pas une cible."""
        crop = np.full((48, 2000, 3), 200, dtype=np.uint8)
        assert to_tensor(crop).shape == (3, REC_HEIGHT, REC_MAX_WIDTH)


class TestDisponibilite:
    def test_les_deux_fichiers_absents_rendent_indisponible(self, tmp_path: Path) -> None:
        reader = OnnxPlateReader(tmp_path / "absent.onnx", tmp_path / "absent.txt")
        assert reader.available is False

    def test_le_modele_seul_ne_suffit_pas(self, tmp_path: Path) -> None:
        """Le test qui protège du décodage à dictionnaire manquant.

        Répondre « disponible » avec le seul modèle produirait des chaînes construites
        sur un alphabet vide, ou pire, sur celui d'un autre export.
        """
        model = tmp_path / "ocr.onnx"
        model.write_bytes(b"pas un vrai modele")
        reader = OnnxPlateReader(model, tmp_path / "absent.txt")
        assert reader.available is False

    def test_le_dictionnaire_seul_ne_suffit_pas(self, tmp_path: Path) -> None:
        charset = tmp_path / "ocr.charset.txt"
        charset.write_text("A\nB\n", encoding="utf-8")
        reader = OnnxPlateReader(tmp_path / "absent.onnx", charset)
        assert reader.available is False

    def test_les_deux_presents_rendent_disponible(self, tmp_path: Path) -> None:
        model = tmp_path / "ocr.onnx"
        model.write_bytes(b"pas un vrai modele")
        charset = tmp_path / "ocr.charset.txt"
        charset.write_text("A\nB\n", encoding="utf-8")
        assert OnnxPlateReader(model, charset).available is True


class TestReadNeLevePas:
    def test_un_lot_vide_rend_un_tuple_vide(self, tmp_path: Path) -> None:
        """`np.stack([])` lève : le cas vide se traite avant tout le reste."""
        reader = OnnxPlateReader(tmp_path / "absent.onnx", tmp_path / "absent.txt")
        assert reader.read(np.zeros((10, 10, 3), dtype=np.uint8), []) == ()

    def test_un_modele_absent_rend_un_none_par_boite(self, tmp_path: Path) -> None:
        """Le contrat d'alignement positionnel tient même en échec total."""
        reader = OnnxPlateReader(tmp_path / "absent.onnx", tmp_path / "absent.txt")
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        boxes = [BoundingBox(0.0, 0.0, 60.0, 20.0), BoundingBox(60.0, 0.0, 60.0, 20.0)]

        assert reader.read(image, boxes) == (None, None)

    def test_deux_appels_de_suite_se_comportent_pareil(self, tmp_path: Path) -> None:
        """Le drapeau `_checked` évite la tempête de réessais, pas le résultat."""
        reader = OnnxPlateReader(tmp_path / "absent.onnx", tmp_path / "absent.txt")
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        boxes = [BoundingBox(0.0, 0.0, 60.0, 20.0)]

        assert reader.read(image, boxes) == (None,)
        assert reader.read(image, boxes) == (None,)

    def test_un_fichier_illisible_ne_leve_pas(self, tmp_path: Path) -> None:
        """Un ONNX invalide fait lever onnxruntime : `read` doit l'absorber."""
        model = tmp_path / "ocr.onnx"
        model.write_bytes(b"pas un vrai modele")
        charset = tmp_path / "ocr.charset.txt"
        charset.write_text("A\nB\n", encoding="utf-8")
        reader = OnnxPlateReader(model, charset)

        image = np.zeros((200, 200, 3), dtype=np.uint8)
        assert reader.read(image, [BoundingBox(0.0, 0.0, 60.0, 20.0)]) == (None,)
