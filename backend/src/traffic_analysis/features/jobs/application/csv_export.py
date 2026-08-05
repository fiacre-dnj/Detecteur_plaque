"""Export CSV du registre et des franchissements.

Trois détails rendent un CSV réellement ouvrable par la personne qui le demande,
et les trois sont français :

1. **BOM UTF-8 en tête.** Sans lui, Excel lit le fichier en ANSI et massacre tous
   les accents — « véhicule » devient « vÃ©hicule ».
2. **Séparateur `;`.** Excel en configuration française attend le point-virgule ;
   avec une virgule, tout le fichier atterrit dans une seule colonne.
3. **Virgule décimale.** `12,5` et non `12.5`, sinon Excel lit un texte et refuse
   de faire la moindre somme.

Aucune bibliothèque : le module `csv` de la bibliothèque standard suffit, et ces
trois règles ne sont supportées par aucune option toute faite.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# Excel attend l'octet-marqueur pour reconnaître l'UTF-8.
BOM = "﻿"
DELIMITER = ";"

VEHICLE_HEADERS = (
    "Identifiant",
    "Type",
    "Vu de (s)",
    "Vu jusqu'à (s)",
    "Lignes franchies",
    "Zones visitées",
    "Ré-identifications",
    "Vitesse moyenne (px/s)",
    "Vitesse moyenne (km/h)",
    "Score de plaque",
)

CROSSING_HEADERS = (
    "Ligne",
    "Identifiant",
    "Type",
    "Sens",
    "Instant (s)",
    "Image",
)

# Libellés français des classes comptées. Un CSV destiné à un humain
# francophone ne doit pas contenir « truck ».
CLASS_LABELS = {
    "car": "Voiture",
    "motorcycle": "Moto",
    "bus": "Bus",
    "truck": "Camion",
}


def _decimal(value: float | None, *, digits: int = 1) -> str:
    """Nombre à la française, ou case vide si l'information n'existe pas.

    Une case vide et non `0` : sans échelle px/m, une vitesse en km/h est
    **inconnue**, pas nulle. Écrire zéro ferait croire à un véhicule à l'arrêt.
    """
    if value is None:
        return ""
    return f"{value:.{digits}f}".replace(".", ",")


def _seconds(milliseconds: float | None) -> str:
    """Millisecondes de scène → secondes lisibles.

    Les millisecondes servent au calcul ; personne ne lit « 143 720 » dans un
    tableau.
    """
    if milliseconds is None:
        return ""
    return _decimal(milliseconds / 1000.0, digits=2)


def _label(raw: str) -> str:
    return CLASS_LABELS.get(raw, raw)


def _direction(value: int) -> str:
    """`+1`/`-1` → le libellé que l'interface affiche.

    Le signe est le contrat machine ; « A→B » est ce que lit un humain, et les
    deux doivent dire la même chose que les flèches du registre.
    """
    return "A→B" if value > 0 else "B→A"


def _render(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    buffer = io.StringIO()
    # `lineterminator` explicite : le défaut de `csv` est `\r\n`, mais le rendre
    # explicite évite qu'un changement de plateforme produise un fichier
    # qu'Excel affiche sur une seule ligne.
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return BOM + buffer.getvalue()


def vehicles_csv(vehicles: Sequence[dict[str, Any]]) -> str:
    """Le registre des véhicules — ce qui rend un total vérifiable."""
    rows = [
        (
            str(vehicle["globalId"]),
            _label(vehicle["label"]),
            _seconds(vehicle["firstSeenMs"]),
            _seconds(vehicle["lastSeenMs"]),
            " | ".join(
                f"{crossing['lineId']} {_direction(crossing['direction'])}"
                f" à {_seconds(crossing['timestampMs'])} s"
                for crossing in vehicle.get("crossedLines", ())
            ),
            " | ".join(vehicle.get("zonesVisited", ())),
            str(vehicle["reidCount"]),
            _decimal(vehicle.get("avgSpeedPxS")),
            _decimal(vehicle.get("avgSpeedKmh")),
            _decimal(vehicle.get("bestPlateScore"), digits=2),
        )
        for vehicle in vehicles
    ]
    return _render(VEHICLE_HEADERS, rows)


def crossings_csv(crossings: Sequence[dict[str, Any]]) -> str:
    """Les franchissements, dans l'ordre chronologique."""
    rows = [
        (
            crossing["lineId"],
            str(crossing["globalId"]),
            _label(crossing["label"]),
            _direction(crossing["direction"]),
            _seconds(crossing["timestampMs"]),
            str(crossing["frameIndex"]),
        )
        for crossing in crossings
    ]
    return _render(CROSSING_HEADERS, rows)
