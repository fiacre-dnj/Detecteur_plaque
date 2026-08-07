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
