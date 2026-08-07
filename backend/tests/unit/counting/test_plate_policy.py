"""L'étranglement de l'OCR.

Ce que ces tests protègent : deux dépenses inutiles et une économie.

`test_une_boite_immobile_n_est_pas_relue` couvre le cas qui coûte le plus cher **en
justesse** : un véhicule arrêté au feu produit cent recadrages identiques, et les
relire ne fait que gonfler la confiance d'un texte peut-être faux.

`test_un_vote_etabli_arrete_tout` couvre l'économie principale — un véhicule passe
de quarante inférences à trois sur sa vie. Il est paramétré sur les autres cas pour
prouver que ce garde a bien la **priorité** sur eux.

`test_une_inference_infructueuse_est_quand_meme_notee` couvre la dépense qu'on
oublie : sans elle, une plaque durablement illisible serait relue à chaque frame.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.domain.models import BoundingBox
from traffic_analysis.features.counting.domain.plate_policy import (
    PlateOcrOptions,
    PlateOcrPolicy,
)

PLATE = BoundingBox(x=100.0, y=200.0, width=60.0, height=18.0)


def _policy(**overrides: object) -> PlateOcrPolicy:
    return PlateOcrPolicy(PlateOcrOptions(**overrides))  # type: ignore[arg-type]


class TestShouldRead:
    def test_la_premiere_occasion_est_toujours_saisie(self) -> None:
        policy = _policy()
        assert policy.should_read(7, 0, PLATE, vote_is_confident=False) is True

    def test_une_piste_sans_identite_ne_vaut_pas_une_inference(self) -> None:
        """La lecture n'aurait aucun agrégat où voter : elle serait jetée."""
        policy = _policy()
        assert policy.should_read(0, 0, PLATE, vote_is_confident=False) is False

    def test_une_plaque_trop_petite_n_est_jamais_lue(self) -> None:
        """~4 px par caractère : l'inférence coûterait sans jamais rien lire."""
        policy = _policy()
        tiny = BoundingBox(x=100.0, y=200.0, width=20.0, height=8.0)
        assert policy.should_read(7, 0, tiny, vote_is_confident=False) is False

    def test_la_cadence_bloque_l_image_suivante(self) -> None:
        policy = _policy()
        policy.record(7, 0, PLATE)
        moved = BoundingBox(x=400.0, y=600.0, width=60.0, height=18.0)
        assert policy.should_read(7, 1, moved, vote_is_confident=False) is False

    def test_la_cadence_se_rouvre_apres_n_images(self) -> None:
        policy = _policy(every_n_frames=3)
        policy.record(7, 0, PLATE)
        moved = BoundingBox(x=400.0, y=600.0, width=60.0, height=18.0)
        assert policy.should_read(7, 3, moved, vote_is_confident=False) is True

    def test_une_boite_immobile_n_est_pas_relue(self) -> None:
        """IoU de 1,0 : même cadence écoulée, il n'y a rien de neuf à lire."""
        policy = _policy()
        policy.record(7, 0, PLATE)
        assert policy.should_read(7, 10, PLATE, vote_is_confident=False) is False

    def test_une_plaque_qui_a_grandi_vaut_une_relecture(self) -> None:
        """Un véhicule qui s'approche est un point de vue plus net.

        C'est ce qu'un garde de distance de centroïde ne verrait pas : le centre
        bouge à peine, l'échelle change beaucoup. L'IoU capte les deux.
        """
        policy = _policy()
        policy.record(7, 0, PLATE)
        closer = BoundingBox(x=90.0, y=195.0, width=95.0, height=28.0)
        assert policy.should_read(7, 10, closer, vote_is_confident=False) is True

    @pytest.mark.parametrize("ordinal", [0, 1, 10])
    def test_un_vote_etabli_arrete_tout(self, ordinal: int) -> None:
        """La priorité de ce garde est ce qui fait l'économie du dispositif."""
        policy = _policy()
        assert policy.should_read(7, ordinal, PLATE, vote_is_confident=True) is False

    def test_l_arret_sur_confiance_est_desactivable(self) -> None:
        policy = _policy(stop_when_confident=False)
        assert policy.should_read(7, 0, PLATE, vote_is_confident=True) is True

    def test_deux_identites_ne_partagent_pas_d_etat(self) -> None:
        """Sinon un véhicule bloquerait la lecture de celui d'à côté."""
        policy = _policy()
        policy.record(7, 0, PLATE)
        assert policy.should_read(8, 1, PLATE, vote_is_confident=False) is True

    def test_une_inference_infructueuse_est_quand_meme_notee(self) -> None:
        """`record` est appelé même quand la lecture n'a rien rendu.

        Sans cela, une plaque sale serait relue à chaque frame — exactement le coût
        que cette politique existe pour éviter.
        """
        policy = _policy()
        policy.record(7, 5, PLATE)
        assert policy.should_read(7, 6, PLATE, vote_is_confident=False) is False


class TestRecord:
    def test_record_remplace_la_boite_memorisee(self) -> None:
        """La comparaison porte sur la **dernière** boîte lue, pas la première."""
        policy = _policy(every_n_frames=1)
        policy.record(7, 0, PLATE)
        closer = BoundingBox(x=90.0, y=195.0, width=95.0, height=28.0)
        policy.record(7, 1, closer)

        assert policy.last_box[7] == closer
        assert policy.should_read(7, 2, closer, vote_is_confident=False) is False
