"""Le découpage du NMS par groupe de classes — ADR 0057.

`nms_class_groups` est le juge unique de ce que le moteur compare à quoi. Trois
propriétés portent tout le reste :

1. **une seule partie pour le jeu de classes par défaut**, donc un seul appel au NMS,
   donc le comportement d'avant au bit près. C'est cette propriété qui rend le
   changement livrable sans réanalyser quoi que ce soit ;
2. **`person` sort des véhicules** — sans quoi le correctif ne corrige rien ;
3. **le groupe n'est PAS `class_group`**, et l'écart est verrouillé plus bas. Les deux
   tables se ressemblent, et les confondre est le piège de ce module.
"""

from __future__ import annotations

import pytest

from traffic_analysis.features.counting.application.ports import nms_class_groups
from traffic_analysis.features.counting.domain.models import (
    CATEGORY_OF_CLASS,
    CATEGORY_OF_ID,
    DETECTABLE_CLASSES,
    VEHICLE_CLASS_IDS,
    class_group,
)

PERSON = 0
BICYCLE = 1
CAR = 2
MOTORCYCLE = 3
BUS = 5
TRAIN = 6
TRUCK = 7


class TestLeDefautNeChangePas:
    def test_les_quatre_vehicules_par_defaut_font_une_seule_partie(self) -> None:
        """**La propriété qui rend ADR 0057 livrable.**

        Une seule partie veut dire un seul appel à `non_max_suppression`, donc
        exactement le chemin d'avant. Si ce test tombait, toutes les analyses du
        défaut changeraient de chiffres sans que personne l'ait demandé.
        """
        assert nms_class_groups(VEHICLE_CLASS_IDS) == (tuple(sorted(VEHICLE_CLASS_IDS)),)

    def test_tous_les_vehicules_du_catalogue_font_une_seule_partie(self) -> None:
        """Y compris les deux-roues : deux boîtes de véhicules qui **coïncident** sont
        un objet scoré deux fois, jamais deux objets. C'est le piège 5, préservé."""
        assert nms_class_groups([BICYCLE, CAR, MOTORCYCLE, BUS, TRAIN, TRUCK]) == (
            (BICYCLE, CAR, MOTORCYCLE, BUS, TRAIN, TRUCK),
        )

    def test_une_seule_classe_fait_une_seule_partie(self) -> None:
        assert nms_class_groups([MOTORCYCLE]) == ((MOTORCYCLE,),)


class TestLaSeparationQuiCorrige:
    def test_personne_sort_des_vehicules(self) -> None:
        """Le cas du motard : sans cette séparation, le pilote et sa moto concourent."""
        assert nms_class_groups([PERSON, MOTORCYCLE]) == ((PERSON,), (MOTORCYCLE,))

    def test_le_cycliste_aussi(self) -> None:
        assert nms_class_groups([PERSON, BICYCLE]) == ((PERSON,), (BICYCLE,))

    def test_la_selection_complete_fait_deux_parties(self) -> None:
        groups = nms_class_groups([PERSON, BICYCLE, CAR, MOTORCYCLE, BUS, TRAIN, TRUCK])
        assert groups == ((PERSON,), (BICYCLE, CAR, MOTORCYCLE, BUS, TRAIN, TRUCK))

    def test_c_est_une_partition_et_non_un_recouvrement(self) -> None:
        """Une classe présente dans deux parties serait rendue **deux fois** par deux
        appels différents, donc compterait double — l'inverse exact du but."""
        wanted = [PERSON, BICYCLE, CAR, MOTORCYCLE, BUS, TRAIN, TRUCK]
        flat = [class_id for group in nms_class_groups(wanted) for class_id in group]
        assert sorted(flat) == sorted(wanted)
        assert len(flat) == len(set(flat))


class TestDeuxTablesQuiNeSeConfondentPas:
    """L'écart entre `nms_class_groups` et `class_group`, verrouillé.

    Les deux répondent à deux questions distinctes, et les fondre casserait l'une des
    deux : la containment doit séparer la moto du camion (elle est **devant**, donc
    contenue à 1,0 mais à IoU basse), le NMS doit les garder ensemble (deux boîtes qui
    **coïncident** sont un objet scoré deux fois, piège 5).
    """

    def test_la_moto_et_le_camion_partagent_leur_partie_de_nms(self) -> None:
        assert nms_class_groups([MOTORCYCLE, TRUCK]) == ((MOTORCYCLE, TRUCK),)

    def test_mais_pas_leur_famille_de_containment(self) -> None:
        assert class_group("motorcycle") != class_group("truck")

    def test_le_pilote_est_separe_des_deux_cotes(self) -> None:
        """La seule classe pour laquelle les deux tables sont d'accord."""
        assert nms_class_groups([PERSON, MOTORCYCLE]) == ((PERSON,), (MOTORCYCLE,))
        assert class_group("person") != class_group("motorcycle")


class TestDeterminisme:
    def test_l_ordre_ne_depend_pas_de_l_ordre_d_entree(self) -> None:
        assert nms_class_groups([TRUCK, PERSON, CAR]) == nms_class_groups([PERSON, CAR, TRUCK])

    def test_les_doublons_sont_absorbes(self) -> None:
        assert nms_class_groups([CAR, CAR, CAR]) == ((CAR,),)

    def test_une_selection_vide_ne_rend_aucune_partie(self) -> None:
        """Le moteur délègue alors au parent : `classes=None` veut dire « toutes »."""
        assert nms_class_groups([]) == ()


class TestRepli:
    def test_une_classe_hors_catalogue_est_un_vehicule(self) -> None:
        """Le même repli que `category_of`, donc elle reste dédupliquée avec eux."""
        assert nms_class_groups([CAR, 42]) == ((CAR, 42),)


class TestTableComplete:
    @pytest.mark.parametrize("entry", DETECTABLE_CLASSES, ids=lambda e: e.coco_name)
    def test_chaque_classe_cochable_est_indexee_par_identifiant(self, entry: object) -> None:
        """`CATEGORY_OF_ID` et `CATEGORY_OF_CLASS` sont deux vues d'une même table ;
        elles doivent le rester, sinon le moteur et le comptage rangeraient une même
        classe dans deux catégories."""
        class_id = entry.id  # type: ignore[attr-defined]
        coco_name = entry.coco_name  # type: ignore[attr-defined]
        assert CATEGORY_OF_ID[class_id] == CATEGORY_OF_CLASS[coco_name]
