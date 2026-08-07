"""La forme canonique d'un texte de plaque.

Ce que ces tests protègent : **l'invention**. Une chaîne affichée est crue, donc une
OCR juste à 40 % est pire que pas d'OCR. `test_aucune_substitution_de_glyphes` est le
test le plus important du fichier : il empêchera quelqu'un d'« améliorer » la
reconnaissance en décidant que le troisième caractère « doit » être un chiffre.

`test_la_normalisation_est_idempotente` compte vraiment : la fonction est appliquée
deux fois dans le pipeline — une fois quand le service pose le texte brut du lecteur,
une fois quand `record_plates` canonicalise.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.domain.plate_text import (
    normalise_plate_reading,
    normalise_plate_text,
)

#: Cas de bout en bout, réutilisés pour l'idempotence.
CASES: tuple[tuple[str, str], ...] = (
    ("ab-123-cd", "AB-123-CD"),
    ("AB-123-CD", "AB-123-CD"),
    ("  ab 123 cd  ", "AB123CD"),
    ("2418 TBE", "2418TBE"),
    ("AB--123", "AB-123"),
    ("-AB123-", "AB123"),
    ("AB.123·CD", "AB123CD"),
    ("ÀB-123-CD", "B-123-CD"),
    ("A1", ""),
    ("ABC1234567890", ""),
    ("", ""),
    ("---", ""),
)


class TestNormalisePlateText:
    @pytest.mark.parametrize(("raw", "expected"), CASES)
    def test_les_cas_de_reference(self, raw: str, expected: str) -> None:
        assert normalise_plate_text(raw) == expected


class TestNormalisePlateReading:
    """La normalisation emmène les confiances avec elle.

    Le consensus par caractère compare des **positions** : il lui faut la confiance du
    caractère retenu, alignée sur le texte *canonique*. Refaire cet alignement en aval
    serait impossible — la normalisation supprime des caractères, et rien dans la
    chaîne de sortie ne dit lesquels. Un décalage ici ne lève rien : il attribue la
    confiance du voisin, et le consensus tranche les mauvaises cases.
    """

    @pytest.mark.parametrize(("raw", "expected"), CASES)
    def test_elle_rend_le_meme_texte_que_sa_facade(self, raw: str, expected: str) -> None:
        """`normalise_plate_text` n'est qu'une vue sur elle : les deux ne peuvent pas
        diverger sans que ce test le dise."""
        assert normalise_plate_reading(raw)[0] == expected

    def test_les_confiances_suivent_les_caracteres_supprimes(self) -> None:
        """Le point sauté doit emporter **sa** confiance, pas celle du `1`."""
        text, scores = normalise_plate_reading("AB.123", (0.9, 0.8, 0.1, 0.7, 0.6, 0.5))
        assert text == "AB123"
        assert scores == (0.9, 0.8, 0.7, 0.6, 0.5)

    def test_les_confiances_survivent_a_la_mise_en_majuscules(self) -> None:
        text, scores = normalise_plate_reading("ab123cd", (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3))
        assert text == "AB123CD"
        assert scores == (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)

    def test_les_separateurs_effondres_emportent_leurs_confiances(self) -> None:
        text, scores = normalise_plate_reading("AB--123", (0.9, 0.8, 0.5, 0.4, 0.7, 0.6, 0.5))
        assert text == "AB-123"
        # Le second tiret disparaît : c'est sa confiance (0,4) qui part, pas celle du
        # tiret conservé.
        assert scores == (0.9, 0.8, 0.5, 0.7, 0.6, 0.5)

    def test_un_texte_refuse_ne_rend_aucune_confiance(self) -> None:
        assert normalise_plate_reading("A1", (0.9, 0.8)) == ("", ())

    def test_sans_confiances_fournies_le_texte_sort_quand_meme(self) -> None:
        """La canonicalisation de `record_plates` et les doublures de test n'ont rien
        à fournir : elles ne mesurent pas de confiance par caractère."""
        assert normalise_plate_reading("ab-123-cd") == ("AB-123-CD", ())

    def test_des_confiances_mal_dimensionnees_sont_ignorees_sans_lever(self) -> None:
        """Un lecteur d'une autre implémentation peut mal tenir le contrat.

        Le vote retombe alors sur la confiance de la lecture entière — moins fin,
        jamais faux — et surtout : un comptage ne doit pas échouer pour ça.
        """
        assert normalise_plate_reading("ab123cd", (0.9, 0.8)) == ("AB123CD", ())

    def test_les_minuscules_deviennent_des_majuscules(self) -> None:
        assert normalise_plate_text("ab123cd") == "AB123CD"

    def test_la_ponctuation_et_les_accents_sont_retires(self) -> None:
        """Une plaque ne porte ni point, ni astérisque, ni lettre accentuée.

        Le modèle en produit pourtant : un rivet lu comme un point, un reflet lu
        comme une apostrophe. Les garder créerait autant de candidats distincts au
        vote qu'il y a de variantes de bruit, et diviserait les voix du bon.
        """
        assert normalise_plate_text("A*B.1'2/3?C") == "AB123C"

    def test_les_separateurs_consecutifs_sont_reduits(self) -> None:
        assert normalise_plate_text("AB---123---CD") == "AB-123-CD"

    def test_les_separateurs_des_extremites_disparaissent(self) -> None:
        assert normalise_plate_text("--AB-123--") == "AB-123"

    def test_une_lecture_trop_courte_est_refusee(self) -> None:
        """Trois caractères, c'est un autocollant ou du bruit, pas une plaque."""
        assert normalise_plate_text("A-1-B") == ""

    def test_une_lecture_trop_longue_est_refusee(self) -> None:
        """Au-delà de dix, le modèle a lu la plaque ET le nom du concessionnaire."""
        assert normalise_plate_text("AB123CD-GARAGE") == ""

    def test_les_separateurs_ne_comptent_pas_dans_la_longueur(self) -> None:
        """`AB-12` fait quatre caractères utiles : c'est le minimum, il passe."""
        assert normalise_plate_text("AB-12") == "AB-12"

    @pytest.mark.parametrize("raw", [raw for raw, _ in CASES])
    def test_la_normalisation_est_idempotente(self, raw: str) -> None:
        once = normalise_plate_text(raw)
        assert normalise_plate_text(once) == once

    def test_aucune_substitution_de_glyphes(self) -> None:
        """`0AB123` et `OAB123` restent deux chaînes **distinctes**.

        Le modèle ne connaît pas le format des plaques du pays. Corriger O en 0
        parce qu'« un chiffre est attendu là » inventerait une information qu'on ne
        possède pas, et produirait une plaque fausse et plausible — le pire résultat
        possible, puisqu'une chaîne affichée est crue.
        """
        assert normalise_plate_text("0AB123") == "0AB123"
        assert normalise_plate_text("OAB123") == "OAB123"
        assert normalise_plate_text("0AB123") != normalise_plate_text("OAB123")

        # Idem pour I/1 et S/5, les deux autres confusions classiques.
        assert normalise_plate_text("I234BC") != normalise_plate_text("1234BC")
        assert normalise_plate_text("S678BC") != normalise_plate_text("5678BC")
