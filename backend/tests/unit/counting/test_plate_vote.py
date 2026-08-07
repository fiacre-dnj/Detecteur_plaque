"""Le vote du texte de plaque.

Ce que ces tests protègent : **l'invariant 4 appliqué au texte**.
`test_une_lecture_unique_ne_publie_rien` est le test le plus important du fichier —
une lecture unique *est* la lecture de la frame courante, exactement ce que
l'invariant interdit de publier. Sans lui, deux relectures du même clip donneraient
deux plaques différentes pour le même véhicule.

L'autre moitié est le quasi-ex æquo — `AB123CD` contre `AB123CO` à confiance voisine.
Le vote **par chaîne** refuse de trancher, et il a raison : entre deux chaînes de
confiance voisine il n'y a pas de gagnant, il y a un tirage au sort. Le consensus
**par caractère** tranche pourtant, et ce n'est pas une contradiction : les six
premiers caractères sont unanimes, seul le septième est disputé, et il se départage
sur la confiance que le modèle lui a donnée. La garde qui rend cela sûr est que le
consensus ne publie **que du déjà-lu** — sans elle il fabriquerait des chimères, et
publier une plaque que personne n'a lue est le pire résultat possible.
"""

from __future__ import annotations

from traffic_analysis.features.counting.domain.plate_vote import PlateTextVote


class TestPublication:
    def test_un_vote_neuf_ne_publie_rien(self) -> None:
        vote = PlateTextVote()
        assert vote.text is None
        assert vote.score == 0.0

    def test_une_lecture_unique_ne_publie_rien(self) -> None:
        """L'invariant 4 : une lecture unique est la lecture de la frame courante."""
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.99)
        assert vote.text is None

    def test_deux_lectures_concordantes_nettes_publient(self) -> None:
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.70)
        vote.observe("AB123CD", 0.70)
        assert vote.text == "AB123CD"

    def test_deux_lectures_concordantes_hesitantes_ne_publient_pas(self) -> None:
        """Deux hésitations qui se ressemblent ne font pas une certitude.

        2 × 0,45 = 0,90, sous le plancher cumulé de 1,2 : l'accord est là, la
        conviction non.
        """
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.45)
        vote.observe("AB123CD", 0.45)
        assert vote.text is None

    def test_une_chaine_vide_ne_vote_pas(self) -> None:
        """`""` est le refus de `normalise_plate_text`, pas un candidat.

        Le compter ferait voter « rien », et « rien » finirait par gagner sur les
        clips où la plupart des recadrages sont illisibles.
        """
        vote = PlateTextVote()
        vote.observe("", 0.99)
        vote.observe("", 0.99)
        assert vote.text is None
        assert vote.accumulated == {}

    def test_le_gagnant_domine_un_concurrent_minoritaire(self) -> None:
        vote = PlateTextVote()
        for _ in range(3):
            vote.observe("AB123CD", 0.90)
        vote.observe("AB123CO", 0.80)
        assert vote.text == "AB123CD"

    def test_une_quasi_egalite_est_tranchee_caractere_par_caractere(self) -> None:
        """1,7 contre 1,6 sur la chaîne entière : la domination refuse, et elle a raison.

        Mais six des sept caractères sont **unanimes** : seul le dernier est disputé.
        Jeter cette unanimité pour cause de désaccord sur un caractère, c'est jeter la
        quasi-totalité de ce qu'on a mesuré. Le consensus par position tranche la case
        litigieuse avec la seule chose qui la départage — la confiance accordée à
        chacun — et publie `AB123CD`, qui a bien été lu.
        """
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.85)
        vote.observe("AB123CD", 0.85)
        vote.observe("AB123CO", 0.80)
        vote.observe("AB123CO", 0.80)
        assert vote.text == "AB123CD"

    def test_le_consensus_ne_publie_jamais_une_chaine_que_personne_n_a_lue(self) -> None:
        """La garde qui empêche le consensus de fabriquer une chimère.

        Deux lectures franchement différentes de même longueur : position par
        position, le gagnant est tantôt de l'une tantôt de l'autre, et la chaîne
        reconstruite n'a jamais été vue par personne. Publier une plaque que le modèle
        n'a jamais lue est le pire résultat possible du dispositif — pire que se
        taire, parce qu'une chaîne affichée est crue.
        """
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.90)
        vote.observe("XY789ZW", 0.85)
        vote.observe("XY789ZW", 0.84)
        assert vote.text != "XB183CW"
        # Le vote par chaîne, lui, tranche normalement : `XY789ZW` domine largement.
        assert vote.text == "XY789ZW"

    def test_deux_longueurs_rivales_ne_se_melangent_pas(self) -> None:
        """Comparer la position 4 de `AB123CD` à celle de `AB1234CD` n'a aucun sens.

        Sans le groupement par longueur, le consensus superposerait deux textes
        décalés d'un cran et rendrait une bouillie — que la garde du « déjà-lu »
        rattraperait, mais en refusant de publier au lieu de trancher.
        """
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.80)
        vote.observe("AB1234CD", 0.75)
        assert vote.text is None

    def test_a_egalite_le_tenant_garde_la_place(self) -> None:
        """Miroir de `IdentityGallery.vote` : `>` strict, pas `>=`.

        Une lecture qui alterne entre deux graphies proches ne doit pas faire
        osciller la plaque affichée d'une frame à l'autre.
        """
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.80)
        vote.observe("AB123CO", 0.80)
        assert vote.leader == "AB123CD"


class TestScore:
    def test_le_score_est_la_moyenne_jamais_la_somme(self) -> None:
        """Un score de confiance supérieur à 1 sur le fil est un bug visible."""
        vote = PlateTextVote()
        for _ in range(5):
            vote.observe("AB123CD", 0.90)
        assert vote.score <= 1.0
        assert vote.score == 0.90

    def test_le_score_moyenne_des_lectures_inegales(self) -> None:
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.60)
        vote.observe("AB123CD", 0.90)
        assert vote.score == 0.75


class TestIsConfident:
    def test_deux_lectures_ne_suffisent_pas_a_arreter_l_ocr(self) -> None:
        """Publier et cesser de vérifier sont deux décisions différentes.

        À deux lectures nettes, le texte est publiable ; l'OCR continue quand même,
        parce qu'une troisième lecture peut encore changer quelque chose.
        """
        vote = PlateTextVote()
        vote.observe("AB123CD", 0.95)
        vote.observe("AB123CD", 0.95)
        assert vote.text == "AB123CD"
        assert vote.is_confident is False

    def test_trois_lectures_nettes_concordantes_arretent_l_ocr(self) -> None:
        """C'est la plus grosse économie du dispositif : 40 inférences → 3."""
        vote = PlateTextVote()
        for _ in range(3):
            vote.observe("AB123CD", 0.95)
        assert vote.is_confident is True

    def test_trois_lectures_concordantes_mais_floues_n_arretent_pas_l_ocr(self) -> None:
        vote = PlateTextVote()
        for _ in range(3):
            vote.observe("AB123CD", 0.70)
        assert vote.is_confident is False

    def test_un_concurrent_credible_empeche_l_arret(self) -> None:
        """Tant qu'une autre graphie tient, une lecture de plus peut trancher."""
        vote = PlateTextVote()
        for _ in range(3):
            vote.observe("AB123CD", 0.95)
        vote.observe("AB123CO", 0.95)
        vote.observe("AB123CO", 0.95)
        assert vote.is_confident is False
