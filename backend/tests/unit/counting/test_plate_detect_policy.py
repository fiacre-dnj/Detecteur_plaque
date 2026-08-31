"""L'étranglement du **détecteur** — le vrai goulot de l'ANPR.

Avec le défaut d'avant ce lot, le détecteur tournait une fois par piste et par
image analysée : une inférence 640×640 chacune. Sur une vidéo de 30 s à 25 fps,
soit 750 images, cela faisait plusieurs minutes de détection de plaques seule —
très probablement l'expérience décrite comme « ça ne marche pas ».

Ce que ces tests verrouillent est l'ordre et la raison de chaque garde. Les
comptes portent sur des **appels**, jamais sur des durées : un verdict qui dépend
de la vitesse de la machine ne prouve rien.
"""

from __future__ import annotations

from traffic_analysis.features.counting.domain.inference_budget import (
    InferenceCandidate,
    select_within_budget,
)
from traffic_analysis.features.counting.domain.models import BoundingBox
from traffic_analysis.features.counting.domain.plate_policy import (
    PlateDetectOptions,
    PlateDetectPolicy,
)

#: Un véhicule largement au-dessus de `min_vehicle_width_px`.
VEHICLE = BoundingBox(x=100.0, y=200.0, width=200.0, height=150.0)


def _policy(**overrides: object) -> PlateDetectPolicy:
    return PlateDetectPolicy(PlateDetectOptions(**overrides))  # type: ignore[arg-type]


class TestPremiereDetection:
    def test_une_piste_jamais_detectee_part_immediatement(self) -> None:
        """Sans cette garde, une piste apparue juste après son tour de rôle
        attendrait `every_n_frames` images avant d'exister à l'écran."""
        policy = _policy()

        assert policy.should_detect(
            7, ordinal=0, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_une_piste_sans_ancre_est_toujours_detectee(self) -> None:
        """**La garde qui empêche le clignotement.**

        Sauter une image sans ancre à reprojeter ne produirait rien du tout —
        c'est-à-dire précisément le rectangle manquant que l'ancre existe pour
        supprimer. On préfère payer l'inférence.
        """
        policy = _policy(every_n_frames=3)
        policy.record(7, ordinal=0)

        assert policy.should_detect(
            7, ordinal=1, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )


class TestCadence:
    def test_une_identite_est_detectee_une_image_sur_n(self) -> None:
        policy = _policy(every_n_frames=3)
        policy.record(3, ordinal=0)

        fired = [
            ordinal
            for ordinal in range(12)
            if policy.should_detect(
                3, ordinal=ordinal, vehicle=VEHICLE, vote_is_confident=False, has_anchor=True
            )
        ]

        assert fired == [0, 3, 6, 9]

    def test_le_decalage_aplatit_la_charge_au_lieu_de_la_faire_osciller(self) -> None:
        """**La raison d'être de `stagger`.**

        Sans décalage, les six pistes d'une image partiraient toutes ensemble une
        image sur trois : 6 inférences, puis 0, puis 0. Le débit moyen serait le
        même et l'expérience bien pire — une image sur trois prendrait trois fois
        plus longtemps, ce qui se voit dans la cadence affichée.
        """
        policy = _policy(every_n_frames=3, stagger=True)
        for global_id in range(1, 7):
            policy.record(global_id, ordinal=0)

        charge = [
            sum(
                1
                for global_id in range(1, 7)
                if policy.should_detect(
                    global_id,
                    ordinal=ordinal,
                    vehicle=VEHICLE,
                    vote_is_confident=False,
                    has_anchor=True,
                )
            )
            for ordinal in range(6)
        ]

        assert charge == [2, 2, 2, 2, 2, 2]

    def test_sans_decalage_la_charge_oscille(self) -> None:
        """Le témoin : il donne son sens au test précédent."""
        policy = _policy(every_n_frames=3, stagger=False)
        for global_id in range(1, 7):
            policy.record(global_id, ordinal=0)

        charge = [
            sum(
                1
                for global_id in range(1, 7)
                if policy.should_detect(
                    global_id,
                    ordinal=ordinal,
                    vehicle=VEHICLE,
                    vote_is_confident=False,
                    has_anchor=True,
                )
            )
            for ordinal in range(5)
        ]

        # Toutes ensemble ou aucune : c'est exactement l'oscillation que le
        # décalage supprime. (Les six ont été enregistrées à l'ordinal 0, donc la
        # cadence les relâche à partir de l'ordinal 3.)
        assert charge == [0, 0, 0, 6, 6]


class TestGardesDEconomie:
    def test_un_vote_acquis_arrete_la_detection(self) -> None:
        """On payait le goulot pour alimenter un consommateur qui n'écoute plus.

        Sur les vidéos dont les plaques sont sous le plancher de lecture, aucun vote
        ne s'établit jamais et cette garde n'apporte rien — c'est attendu, et c'est
        pourquoi le gain retombe vers le seul facteur de cadence sur ces scènes.
        """
        policy = _policy(stop_when_confident=True)

        assert not policy.should_detect(
            3, ordinal=5, vehicle=VEHICLE, vote_is_confident=True, has_anchor=True
        )

    def test_le_vote_acquis_peut_etre_ignore(self) -> None:
        policy = _policy(stop_when_confident=False, every_n_frames=1, stagger=False)
        policy.record(3, ordinal=0)

        assert policy.should_detect(
            3, ordinal=5, vehicle=VEHICLE, vote_is_confident=True, has_anchor=True
        )

    def test_une_piste_trop_etroite_n_est_jamais_detectee(self) -> None:
        """Sur un véhicule de 80 px, la plaque ferait une douzaine de pixels :
        l'inférence coûterait sans rien pouvoir trouver."""
        policy = _policy(min_vehicle_width_px=96.0)
        etroit = BoundingBox(x=0.0, y=0.0, width=80.0, height=60.0)

        assert not policy.should_detect(
            3, ordinal=0, vehicle=etroit, vote_is_confident=False, has_anchor=False
        )

    def test_la_garde_de_taille_precede_toutes_les_autres(self) -> None:
        """Gratuite à évaluer, garantie sans résultat : elle passe en premier."""
        policy = _policy(min_vehicle_width_px=96.0)
        etroit = BoundingBox(x=0.0, y=0.0, width=80.0, height=60.0)

        # Ni la première détection, ni l'absence d'ancre ne la contournent.
        assert not policy.should_detect(
            99, ordinal=0, vehicle=etroit, vote_is_confident=False, has_anchor=False
        )


class TestEchecsConsecutifs:
    """Le trou que l'ancre ne bouche pas.

    Une piste dont la plaque n'est structurellement jamais visible n'a jamais
    d'ancre : sans cette garde, elle serait retentée à chaque image analysée
    pendant toute sa vie, payant le goulot sans jamais rien obtenir de nouveau.
    """

    def test_une_piste_sans_plaque_finit_par_retomber_sur_la_cadence(self) -> None:
        """Rejoue la vraie boucle : décider, puis enregistrer, image après image."""
        policy = _policy(every_n_frames=3, stagger=False, max_consecutive_misses=3)

        # Les trois premiers échecs sont payés — comportement inchangé.
        for ordinal in range(3):
            assert policy.should_detect(
                7, ordinal=ordinal, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
            )
            policy.record(7, ordinal=ordinal, found=False)

        # Le quatrième échec consécutif atteint le plafond : la piste retombe sur
        # la cadence, comme si elle avait une ancre.
        assert not policy.should_detect(
            7, ordinal=3, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_un_succes_reinitialise_le_compte_d_echecs(self) -> None:
        """Une piste qui retrouve sa plaque une fois n'est pas punie pour ses
        échecs passés : elle doit pouvoir en enchaîner `max_consecutive_misses`
        nouveaux avant de retomber sur la cadence."""
        policy = _policy(every_n_frames=3, stagger=False, max_consecutive_misses=1)
        policy.record(7, ordinal=0, found=False)
        policy.record(7, ordinal=1, found=True)

        assert policy.should_detect(
            7, ordinal=2, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_le_plafond_par_defaut_est_trois(self) -> None:
        options = PlateDetectOptions()

        assert options.max_consecutive_misses == 3

    def test_record_par_defaut_compte_un_succes(self) -> None:
        """Les appelants historiques de `record(global_id, ordinal)`, sans le
        paramètre `found`, ne doivent pas se retrouver traités comme des échecs."""
        policy = _policy(every_n_frames=3, stagger=False, max_consecutive_misses=1)
        policy.record(7, ordinal=0)

        assert policy.misses.get(7, 0) == 0


class TestPlafondParImage:
    """Le seul plafond qui rende le coût de l'ANPR indépendant de la scène.

    Mesuré sur une scène dense réelle (1920×1080, 6 à 14 véhicules par image) :
    l'étage de plaques coûte 76 ms par image analysée, soit **73 %** du budget, contre
    0,4 ms pour l'OCR — et ce coût est **linéaire en nombre de recadrages** (21,5 ms
    pour un, 139,7 pour huit), chaque véhicule payant une inférence entière. Sans
    plafond, la cadence suit donc la circulation.

    Ce que ces tests verrouillent est le **classement**, parce que c'est lui qui décide
    de la justesse : plafonner en gardant les mauvaises pistes échangerait de la
    cadence contre des plaques.
    """

    @staticmethod
    def _candidate(global_id: int, width: float, *, never: bool = False) -> InferenceCandidate:
        return InferenceCandidate(global_id=global_id, width=width, never_served=never)

    def test_sans_plafond_rien_n_est_ecarte(self) -> None:
        """`0` = illimité, le comportement historique. Le plafond doit rester
        strictement additif tant que personne ne le pose."""
        candidates = [self._candidate(index, 100.0) for index in range(6)]

        assert select_within_budget(candidates, 0) == frozenset(range(6))

    def test_un_plafond_plus_large_que_la_scene_n_ecarte_rien(self) -> None:
        candidates = [self._candidate(index, 100.0) for index in range(3)]

        assert select_within_budget(candidates, 8) == frozenset({0, 1, 2})

    def test_les_plus_larges_passent_d_abord(self) -> None:
        """La largeur du véhicule est le meilleur prédicteur disponible de la
        lisibilité de sa plaque : le plancher de lecture est mesuré à 64 px, et
        dépenser sur une piste dont la plaque fera 20 px achète une boîte que l'OCR
        refusera de lire."""
        candidates = [
            self._candidate(1, 120.0),
            self._candidate(2, 400.0),
            self._candidate(3, 250.0),
        ]

        assert select_within_budget(candidates, 2) == frozenset({2, 3})

    def test_une_piste_jamais_mesuree_passe_avant_une_piste_plus_large(self) -> None:
        """**Sans cette priorité, un véhicule peut traverser tout le champ sans
        recevoir une seule mesure**, donc sans jamais afficher de rectangle — un
        silence qui se lit comme une panne de détection, pas comme une économie.

        C'est la même raison qui fait que `should_detect` ne diffère jamais la
        première mesure d'une piste.
        """
        candidates = [
            self._candidate(1, 500.0),
            self._candidate(2, 80.0, never=True),
        ]

        assert select_within_budget(candidates, 1) == frozenset({2})

    def test_a_egalite_stricte_le_choix_est_deterministe(self) -> None:
        """Deux courses du même clip doivent dépenser au même endroit.

        Un `set` d'itération non déterministe rendrait deux analyses du même fichier
        légèrement différentes — exactement le genre d'écart qu'on passe des jours à
        ne pas comprendre.
        """
        candidates = [self._candidate(index, 200.0) for index in (9, 4, 7)]

        assert select_within_budget(candidates, 2) == select_within_budget(candidates, 2)
        assert select_within_budget(candidates, 2) == frozenset({4, 7})

    def test_le_defaut_est_illimite(self) -> None:
        """Plafonner écarte des mesures, donc des plaques possibles : l'arbitrage ne
        se prend pas à la place de l'exploitant."""
        assert PlateDetectOptions().max_per_frame == 0


class TestLisibiliteProjetee:
    """La porte qui refuse de payer pour une plaque prouvée illisible — ADR 0039.

    Sur une vue de circulation réelle, la détection de plaques pèse 73 % du budget
    et **aucune plaque n'y est publiable** : elles font moins de 48 px pour un
    plancher de lecture à 64 (invariant 12). Cette porte rend ce temps-là, et
    seulement celui-là.

    Le plancher utilisé est **exactement** celui dont l'OCR se sert pour refuser de
    lire, donc aucun texte publiable ne peut être perdu — par construction, pas en
    moyenne. Ce qui est payé est le rectangle.
    """

    #: Un véhicule de 200 px dont la plaque mesure 20 px : rapport 0,1, et il
    #: faudrait 640 px de véhicule pour atteindre un plancher de 64.
    PLATE_WIDTH = 20.0
    FLOOR = 64.0

    def _suspended(self, **overrides: object) -> PlateDetectPolicy:
        """Une politique dont la piste 7 vient d'être suspendue pour illisibilité."""
        policy = _policy(readable_min_plate_width_px=self.FLOOR, **overrides)
        for ordinal in range(2):
            policy.record(7, ordinal=ordinal)
            policy.observe_plate(7, VEHICLE.width, self.PLATE_WIDTH)
        return policy

    def test_une_piste_dont_la_plaque_reste_trop_petite_est_suspendue(self) -> None:
        policy = self._suspended()

        assert not policy.should_detect(
            7, ordinal=9, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_la_porte_se_rouvre_seule_quand_le_vehicule_s_approche(self) -> None:
        """**Le test qui distingue une suspension d'un abandon.**

        Sans lui, la porte perdrait la plaque qu'une piste publiera dans trois
        secondes, à dix mètres d'ici — l'objection décisive contre un simple
        compteur d'abandon. Le réarmement ne demande aucun réglage : c'est une
        mesure, `largeur_véhicule × rapport ≥ plancher`.
        """
        policy = self._suspended()
        # Rapport mesuré 0,1 : il faut 640 px de véhicule pour une plaque de 64.
        approaching = BoundingBox(x=0.0, y=0.0, width=700.0, height=520.0)

        assert policy.should_detect(
            7, ordinal=9, vehicle=approaching, vote_is_confident=False, has_anchor=False
        )

    def test_une_seule_mesure_basse_ne_suspend_pas(self) -> None:
        """Deux mesures décrivent une situation, une seule décrit un instant.

        Une plaque à moitié occultée ou vue de biais rend une largeur courte qui ne
        décrit pas la piste.
        """
        policy = _policy(readable_min_plate_width_px=self.FLOOR)
        policy.record(7, ordinal=0)
        policy.observe_plate(7, VEHICLE.width, self.PLATE_WIDTH)

        assert policy.should_detect(
            7, ordinal=1, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_une_mesure_lisible_reouvre_la_porte(self) -> None:
        """Les échecs comptés sont **consécutifs**, comme `misses`."""
        policy = self._suspended()
        policy.observe_plate(7, VEHICLE.width, self.FLOOR + 10.0)

        assert policy.should_detect(
            7, ordinal=9, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_la_porte_passe_avant_la_garde_sans_ancre(self) -> None:
        """**Le détail qui peut faire échouer tout le mécanisme en silence.**

        Une piste suspendue ne mesure plus, donc son ancre vieillit et disparaît à
        `max_anchor_age`. La garde « pas d'ancre » rend `True` sans condition : si
        la porte était placée après elle, la piste serait relancée à *chaque* image
        et la porte n'économiserait rien du tout — sans que rien ne le signale.
        """
        policy = self._suspended()

        assert not policy.should_detect(
            7, ordinal=9, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_un_plancher_nul_ne_change_rien(self) -> None:
        """**Le témoin d'additivité** : porte désarmée, comportement d'avant.

        C'est aussi le cas de production sans OCR — le service ne pose jamais le
        plancher quand aucun lecteur ne tourne.
        """
        policy = _policy()
        for ordinal in range(4):
            policy.record(7, ordinal=ordinal)
            policy.observe_plate(7, VEHICLE.width, self.PLATE_WIDTH)

        assert policy.should_detect(
            7, ordinal=4, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_le_rapport_retenu_est_le_meilleur_jamais_vu(self) -> None:
        """Un maximum, jamais la dernière valeur : il rouvre la porte plus qu'il ne la ferme.

        Une piste dont la plaque a été vue large une fois *peut* l'être ; laisser
        une vue de biais écraser ce rapport fermerait la porte pour de bon sur un
        véhicule pourtant lisible.
        """
        policy = _policy(readable_min_plate_width_px=self.FLOOR)
        policy.observe_plate(7, VEHICLE.width, 80.0)  # rapport 0,4
        for ordinal in range(2):
            policy.record(7, ordinal=ordinal)
            policy.observe_plate(7, VEHICLE.width, self.PLATE_WIDTH)  # rapport 0,1

        # Avec le meilleur rapport (0,4), 200 px de véhicule donnent 80 px de plaque.
        assert policy.should_detect(
            7, ordinal=9, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )

    def test_le_quota_d_exploration_rouvre_la_porte_une_image(self) -> None:
        """Désactivé par défaut, et il ne rouvre que le temps d'une image."""
        policy = self._suspended(readable_retry_every=5)

        # Premier refus : il pose la date de suspension.
        assert not policy.should_detect(
            7, ordinal=10, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )
        # Avant l'échéance, toujours refusé.
        assert not policy.should_detect(
            7, ordinal=13, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )
        # À l'échéance, une tentative est accordée.
        assert policy.should_detect(
            7, ordinal=15, vehicle=VEHICLE, vote_is_confident=False, has_anchor=False
        )
