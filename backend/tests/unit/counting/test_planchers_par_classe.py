"""Le plancher de confiance par classe — ADR 0062.

**Le curseur unique force un choix qui n'a pas lieu d'être.** Mesuré sur une vraie
vidéo, descendre la confiance de 0,35 à 0,20 fait passer le rappel des voitures de
0,484 à 0,790 — et **inventer dix-sept observations de `bus`** sur un clip qui n'en
contient aucun. Les deux effets ne portent pas sur les mêmes classes : baisser pour les
petits objets ne demande pas de baisser pour les gros.

Trois propriétés, et la première est celle qui rend le changement livrable :

1. **`None` est un no-op strict** — tout le monde garde le seuil unique, au chiffre
   près. C'est le défaut, donc aucune analyse existante ne change ;
2. **le minimum des planchers part au tracker**, jamais le seuil nominal : il devient
   `new_track_thresh` (ADR 0024), et s'il restait à 0,35 une moto à 0,25 n'ouvrirait
   aucune piste — le plancher par classe n'aurait alors strictement aucun effet ;
3. **la table des petits objets est le miroir exact du client**, qui nomme les mêmes
   classes pour l'avertissement d'avant-analyse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from traffic_analysis.features.counting.application.ports import (
    EngineSpec,
    class_confidence_floors,
    minimum_floor,
)
from traffic_analysis.features.counting.domain.models import SMALL_CLASS_IDS

PERSON = 0
BICYCLE = 1
CAR = 2
MOTORCYCLE = 3
BUS = 5
TRUCK = 7

DEFAULT_SELECTION = (CAR, MOTORCYCLE, BUS, TRUCK)


class TestLeNoOpStrict:
    def test_sans_second_plancher_tout_le_monde_garde_le_seuil_unique(self) -> None:
        """**La propriété qui rend ADR 0062 livrable.** C'est le défaut."""
        floors = class_confidence_floors(DEFAULT_SELECTION, 0.35, None)
        assert floors == ((CAR, 0.35), (MOTORCYCLE, 0.35), (BUS, 0.35), (TRUCK, 0.35))

    def test_le_minimum_vaut_alors_exactement_le_seuil(self) -> None:
        """Donc `new_track_thresh` et `detector_floor` ne bougent pas d'un chiffre."""
        floors = class_confidence_floors(DEFAULT_SELECTION, 0.35, None)
        assert minimum_floor(floors, 0.35) == 0.35

    def test_le_spec_ne_porte_rien_par_defaut(self) -> None:
        spec = EngineSpec(model_id="yolov8n", confidence=0.35, iou=0.45, class_ids=(2,))
        assert spec.small_confidence is None


class TestLaSeparation:
    def test_seuls_les_petits_objets_descendent(self) -> None:
        floors = class_confidence_floors((PERSON, CAR, MOTORCYCLE, BUS), 0.35, 0.20)
        assert dict(floors) == {PERSON: 0.20, CAR: 0.35, MOTORCYCLE: 0.20, BUS: 0.35}

    def test_le_velo_en_fait_partie(self) -> None:
        """Rappel `bicycle` le plus bas du catalogue sur COCO : 0,392 en yolov8n."""
        assert dict(class_confidence_floors((BICYCLE, TRUCK), 0.35, 0.20)) == {
            BICYCLE: 0.20,
            TRUCK: 0.35,
        }

    def test_le_minimum_descend_avec_eux(self) -> None:
        """**Sans cela le plancher par classe serait inerte.**

        Le minimum part sur `track_high_thresh` / `new_track_thresh` : à 0,35, une moto
        à 0,25 ne pourrait jamais ouvrir de piste, donc la baisser pour elle seule ne
        changerait rien. C'est exactement la panne d'ADR 0037, à un autre étage.
        """
        floors = class_confidence_floors((CAR, MOTORCYCLE), 0.35, 0.20)
        assert minimum_floor(floors, 0.35) == 0.20

    def test_un_plancher_plus_HAUT_est_accepte(self) -> None:
        """Rien n'impose que le second plancher soit plus bas : une scène où les motos
        sont hallucinées appelle l'inverse, et le port n'a pas à en juger."""
        floors = class_confidence_floors((CAR, MOTORCYCLE), 0.20, 0.50)
        assert dict(floors) == {CAR: 0.20, MOTORCYCLE: 0.50}
        assert minimum_floor(floors, 0.20) == 0.20


class TestDeterminisme:
    def test_l_ordre_ne_depend_pas_de_l_entree(self) -> None:
        assert class_confidence_floors((TRUCK, CAR), 0.35, None) == class_confidence_floors(
            (CAR, TRUCK), 0.35, None
        )

    def test_les_doublons_sont_absorbes(self) -> None:
        assert class_confidence_floors((CAR, CAR), 0.35, None) == ((CAR, 0.35),)

    def test_une_selection_vide_rend_le_repli(self) -> None:
        """Le schéma de requête refuse ce cas, mais le port ne peut pas le supposer."""
        assert class_confidence_floors((), 0.35, 0.20) == ()
        assert minimum_floor((), 0.35) == 0.35


class TestLaTableEstLeMiroirDuClient:
    def test_les_trois_petites_classes_sont_celles_du_catalogue(self) -> None:
        assert frozenset({PERSON, BICYCLE, MOTORCYCLE}) == SMALL_CLASS_IDS

    def test_le_client_nomme_exactement_les_memes(self) -> None:
        """**Doublon assumé de part et d'autre de la frontière de langage**, verrouillé
        comme `MIN_PLATE_CROP_SIDE_PX` et `QUERY_MARGIN` avant lui.

        Le client range par nom COCO, le serveur par identifiant : deux vues de la même
        table, et rien d'autre ne les relierait si elles divergeaient.
        """
        classes_ts = (
            Path(__file__).resolve().parents[4]
            / "frontend"
            / "src"
            / "shared"
            / "lib"
            / "classes.ts"
        )
        if not classes_ts.is_file():  # pragma: no cover — dépôt backend seul
            pytest.skip("frontend absent")

        source = classes_ts.read_text(encoding="utf-8")
        declared = source.split("SMALL_CLASSES")[1].split("]")[0]
        for name in ("motorcycle", "bicycle", "person"):
            assert f'"{name}"' in declared, (
                f"« {name} » a quitté SMALL_CLASSES côté client : les deux tables ont "
                "divergé, et l'avertissement d'avant-analyse ne parlera plus de la "
                "classe dont le plancher descend."
            )
