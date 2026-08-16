"""La numérotation des véhicules et le vote de leur type.

Remplace `test_reid.py`, supprimé avec la galerie d'apparence (ADR 0016). Le
contraste entre les deux fichiers est l'essentiel de ce que l'ADR a changé :
l'ancien testait des descripteurs, des similarités et des budgets de déplacement ;
celui-ci teste qu'un entier monte et qu'un vote majoritaire tranche.

Deux propriétés sont vérifiées ici et **nulle part ailleurs** :

- un numéro n'est jamais réattribué, y compris quand le tracker réémet un
  identifiant de piste. C'est ce qui protège de la panne silencieuse du compteur
  process-global d'Ultralytics ;
- `count_by_class()` somme toujours à `size`, même quand un vote bascule. Sans le
  transfert de voix de `_retally`, la répartition par type afficherait plus de
  véhicules que le total — ce que l'utilisateur voit immédiatement.
"""

from __future__ import annotations

from traffic_analysis.features.counting.domain.track_numbering import TrackNumbering

CAR = 2
TRUCK = 7
BUS = 5


class TestEmissionDesNumeros:
    def test_le_premier_numero_est_un(self) -> None:
        """Pas zéro : `0` signifie « pas encore numéroté » sur `SessionTrack`.

        Les confondre ferait passer une piste numérotée pour une piste en attente,
        et le compteur de lignes attribuerait ses franchissements au numéro 0.
        """
        numbering = TrackNumbering()

        assert numbering.assign(track_id=1, class_id=CAR, label="car") == 1

    def test_la_suite_monte_et_ne_redescend_jamais(self) -> None:
        numbering = TrackNumbering()

        numbers = [numbering.assign(track_id, CAR, "car") for track_id in (1, 2, 3, 4)]

        assert numbers == [1, 2, 3, 4]
        assert numbering.issued == 4

    def test_reappeler_pour_la_meme_piste_rend_le_meme_numero(self) -> None:
        """Idempotence : la session appelle à chaque image sans se souvenir.

        Sans elle, un véhicule changerait de badge à chaque frame et le registre
        compterait une entrée par image.
        """
        numbering = TrackNumbering()

        first = numbering.assign(9, CAR, "car")
        again = numbering.assign(9, CAR, "car")

        assert first == again == 1
        assert numbering.issued == 1

    def test_toutes_les_classes_puisent_dans_la_meme_suite(self) -> None:
        """**La cohérence inter-types.**

        Un compteur par classe donnerait un `car#1` et un `truck#1` simultanés :
        deux véhicules avec le même badge à l'écran, et un registre sans clé.
        """
        numbering = TrackNumbering()

        assert numbering.assign(1, CAR, "car") == 1
        assert numbering.assign(2, TRUCK, "truck") == 2
        assert numbering.assign(3, 0, "person") == 3
        assert numbering.assign(4, CAR, "car") == 4

    def test_un_numero_oublie_n_est_jamais_reattribue(self) -> None:
        """**Le garde contre la panne silencieuse d'Ultralytics.**

        `BaseTrack._count` est un attribut de classe : une session temps réel qui
        démarre pendant une analyse le remet à zéro, et l'analyse se remet à voir
        des identifiants 1, 2, 3. Si `forget` libérait aussi le *numéro*, l'ancien
        véhicule 1 et le nouveau fusionneraient — un total qui baisse sans que rien
        à l'écran ne l'explique.

        `forget` ne libère donc que l'identifiant de **piste**.
        """
        numbering = TrackNumbering()
        first = numbering.assign(1, CAR, "car")

        numbering.forget(1)
        reused = numbering.assign(1, CAR, "car")

        assert first == 1
        assert reused == 2, "l'identifiant de piste réémis a reçu un numéro neuf"
        assert numbering.number_of(1) == 2

    def test_une_piste_inconnue_ne_porte_aucun_numero(self) -> None:
        numbering = TrackNumbering()

        assert numbering.number_of(404) == 0
        assert numbering.label_of(0) == ""


class TestConfirmation:
    """Émettre un numéro et compter un véhicule sont deux gestes distincts."""

    def test_un_numero_emis_n_est_pas_encore_compte(self) -> None:
        numbering = TrackNumbering()
        numbering.assign(1, CAR, "car")

        assert numbering.issued == 1
        assert numbering.size == 0
        assert numbering.count_by_class() == {}
        assert numbering.is_confirmed(1) is False

    def test_la_confirmation_fait_entrer_le_vehicule_dans_le_total(self) -> None:
        numbering = TrackNumbering()
        vehicle = numbering.assign(1, CAR, "car")

        numbering.confirm(vehicle)

        assert numbering.size == 1
        assert numbering.count_by_class() == {"car": 1}
        assert numbering.is_confirmed(vehicle) is True

    def test_confirmer_deux_fois_ne_compte_qu_une_fois(self) -> None:
        """Idempotence, pour la même raison qu'`assign` : la session appelle à
        chaque image d'une piste confirmée."""
        numbering = TrackNumbering()
        vehicle = numbering.assign(1, CAR, "car")

        numbering.confirm(vehicle)
        numbering.confirm(vehicle)
        numbering.confirm(vehicle)

        assert numbering.size == 1
        assert numbering.count_by_class() == {"car": 1}

    def test_confirmer_un_numero_inconnu_ne_leve_pas(self) -> None:
        """`0` est un numéro inconnu, et la session le rencontre."""
        numbering = TrackNumbering()

        numbering.confirm(0)
        numbering.confirm(999)

        assert numbering.size == 0

    def test_un_scintillement_creuse_un_trou_dans_la_suite(self) -> None:
        """La contrepartie assumée : `size` est inférieur au dernier numéro émis.

        Le véhicule 2 n'a jamais été confirmé — une seule image, un scintillement du
        détecteur. Son numéro reste consommé, et c'est le prix d'un badge qui ne
        change jamais en cours de route.
        """
        numbering = TrackNumbering()
        for track_id in (1, 2, 3):
            numbering.assign(track_id, CAR, "car")
        numbering.confirm(numbering.number_of(1))
        numbering.confirm(numbering.number_of(3))

        assert numbering.issued == 3
        assert numbering.size == 2
        assert numbering.is_confirmed(2) is False

    def test_un_vehicule_confirme_reste_compte_apres_l_oubli_de_sa_piste(self) -> None:
        """Le total ne redescend jamais en cours d'analyse.

        Un compteur qui baisse quand un véhicule sort du champ se lit comme une
        panne, et rendrait toute lecture intermédiaire inutilisable.
        """
        numbering = TrackNumbering()
        vehicle = numbering.assign(1, CAR, "car")
        numbering.confirm(vehicle)

        numbering.forget(1)

        assert numbering.size == 1
        assert numbering.is_confirmed(vehicle) is True
        assert numbering.label_of(vehicle) == "car"


class TestVoteDeClasse:
    def test_le_type_majoritaire_gagne(self) -> None:
        numbering = TrackNumbering()
        vehicle = numbering.assign(1, CAR, "car")

        for label, class_id in (("car", CAR), ("truck", TRUCK), ("truck", TRUCK)):
            numbering.vote(vehicle, class_id, label)

        assert numbering.label_of(vehicle) == "truck"

    def test_a_egalite_le_tenant_garde_la_place(self) -> None:
        """Une lecture qui alterne bus/camion ne doit pas faire osciller le compteur.

        C'est le `>` strict de `vote`. Avec un `>=`, un véhicule à égalité changerait
        de type à chaque image et sa ligne du registre clignoterait.
        """
        numbering = TrackNumbering()
        vehicle = numbering.assign(1, BUS, "bus")

        numbering.vote(vehicle, BUS, "bus")
        numbering.vote(vehicle, TRUCK, "truck")

        assert numbering.label_of(vehicle) == "bus"

    def test_un_basculement_deplace_la_voix_et_ne_l_ajoute_pas(self) -> None:
        """`count_by_class()` somme toujours à `size`. **L'invariant 3 en petit.**

        Sans le transfert de `_retally`, la répartition par type afficherait deux
        véhicules pour un seul suivi.
        """
        numbering = TrackNumbering()
        vehicle = numbering.assign(1, CAR, "car")
        numbering.confirm(vehicle)
        assert numbering.count_by_class() == {"car": 1}

        for _ in range(3):
            numbering.vote(vehicle, TRUCK, "truck")

        assert numbering.label_of(vehicle) == "truck"
        assert numbering.count_by_class() == {"truck": 1}
        assert sum(numbering.count_by_class().values()) == numbering.size

    def test_un_basculement_avant_confirmation_ne_touche_aucun_total(self) -> None:
        """Un véhicule pas encore compté n'a aucune voix à déplacer.

        Retirer une voix qu'il n'a pas ferait descendre un total de classe sous zéro,
        et `count_by_class()` cesserait de sommer à `size`.
        """
        numbering = TrackNumbering()
        vehicle = numbering.assign(1, CAR, "car")

        for _ in range(3):
            numbering.vote(vehicle, TRUCK, "truck")
        assert numbering.count_by_class() == {}

        numbering.confirm(vehicle)

        # Le type retenu est celui du vote au moment de la confirmation, pas celui
        # de la première image.
        assert numbering.count_by_class() == {"truck": 1}
        assert sum(numbering.count_by_class().values()) == numbering.size

    def test_voter_pour_un_numero_inconnu_ne_leve_pas(self) -> None:
        numbering = TrackNumbering()

        numbering.vote(0, CAR, "car")
        numbering.vote(999, CAR, "car")

        assert numbering.count_by_class() == {}

    def test_la_repartition_somme_au_total_sur_plusieurs_vehicules(self) -> None:
        numbering = TrackNumbering()

        for track_id, class_id, label in ((1, CAR, "car"), (2, CAR, "car"), (3, TRUCK, "truck")):
            vehicle = numbering.assign(track_id, class_id, label)
            numbering.vote(vehicle, class_id, label)
            numbering.confirm(vehicle)

        assert numbering.size == 3
        assert numbering.count_by_class() == {"car": 2, "truck": 1}
        assert sum(numbering.count_by_class().values()) == numbering.size
