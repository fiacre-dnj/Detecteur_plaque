"""Le tracker que le moteur charge réellement, et pas celui que le dépôt versionne.

Ultralytics ne prend sa configuration de suivi **que** par chemin de fichier :
rendre `gmc_method` réglable oblige donc à écrire un fichier dérivé. Ce module
vérifie les deux issues de cette dérivation, parce que l'une des deux est
silencieuse.

**La panne évitée est un réglage sans effet.** Un `TRAFFIC_TRACKER_GMC` qui ne
serait pas répercuté dans le fichier chargé laisserait tourner la compensation de
mouvement — 20,2 ms par image, 39 % du budget (ADR 0013) — pendant que
`/health`, les journaux et le rapport de banc annonceraient l'inverse. Rien
n'échouerait : l'analyse serait simplement deux fois plus lente que ce que tout le
monde croit.

Ces tests n'importent pas ultralytics : ils lisent un YAML et comparent des
chemins. Même discipline que `test_tracker_config.py`, pour la même raison — la CI
tourne sans GPU, sans poids et sans ultralytics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from traffic_analysis.core.settings import Settings
from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    TRACKER_CONFIG,
    detector_floor,
    resolved_tracker_config,
)

if TYPE_CHECKING:
    from pathlib import Path


def _gmc_of(path: Path) -> str:
    return str(yaml.safe_load(path.read_text(encoding="utf-8"))["gmc_method"])


def _load(path: Path) -> dict[str, object]:
    loaded: dict[str, object] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


#: Le seuil que le fichier versionné porte déjà — celui qui ne dérive rien.
BASE_HIGH = float(_load(TRACKER_CONFIG)["track_high_thresh"])  # type: ignore[arg-type]


def test_la_valeur_du_fichier_de_base_rend_le_fichier_de_base() -> None:
    """Cas courant : rien à dériver, donc aucun fichier temporaire.

    C'est ce qui garantit qu'en configuration par défaut le service charge le
    fichier **versionné** — celui qu'on peut lire dans le dépôt pour savoir ce qui
    tourne, sans aller fouiller un dossier temporaire.
    """
    assert resolved_tracker_config(_gmc_of(TRACKER_CONFIG), BASE_HIGH) == TRACKER_CONFIG


def test_une_autre_valeur_produit_un_fichier_derive_qui_la_porte() -> None:
    """Le réglage doit **arriver** jusqu'au fichier, pas seulement être accepté."""
    derived = resolved_tracker_config("sparseOptFlow", BASE_HIGH)

    assert derived != TRACKER_CONFIG
    assert _gmc_of(derived) == "sparseOptFlow"


def test_le_fichier_derive_conserve_tout_le_reste() -> None:
    """Seule la compensation change ; les seuils d'association ne bougent pas.

    `track_buffer` en particulier est le **miroir exact** de `max_lost_ms = 2500`
    du domaine. Une dérivation qui le perdrait désaccorderait le moteur et le
    domaine sur ce qu'est « une piste perdue », et la ré-identification
    travaillerait sur des identités que le tracker a déjà recyclées.
    """
    base = _load(TRACKER_CONFIG)
    derived = _load(resolved_tracker_config("orb", BASE_HIGH))

    assert derived == {**base, "gmc_method": "orb"}


def test_le_seuil_de_la_requete_arrive_sur_les_deux_cles() -> None:
    """Le seuil de l'utilisateur gouverne la bande **et** la création de pistes.

    `track_high_thresh` sépare les deux bandes d'association ; `new_track_thresh`
    décide ce qui peut ouvrir une piste. Les deux doivent porter le seuil de la
    requête, et pour deux raisons distinctes :

    - sans `track_high_thresh`, toutes les détections seraient « hautes » et la
      bande basse resterait vide — c'est la panne que `detector_floor` corrige ;
    - sans `new_track_thresh`, une détection faible pourrait **ouvrir** une piste,
      et le changement cesserait d'être strictement additif.
    """
    derived = _load(resolved_tracker_config(_gmc_of(TRACKER_CONFIG), 0.5))

    assert derived["track_high_thresh"] == 0.5
    assert derived["new_track_thresh"] == 0.5


def test_le_plancher_du_detecteur_alimente_bien_la_bande_basse() -> None:
    """**Le test qui tient tout le mécanisme BYTE.**

    La bande basse de ByteTrack va de `track_low_thresh` (exclu) à
    `track_high_thresh` (exclu). Elle n'existe que si le détecteur rend des boîtes
    en dessous du seuil de l'utilisateur : c'est tout l'objet de `detector_floor`.

    Si ce plancher remontait au niveau du seuil de piste, la bande serait vide, la
    seconde association redeviendrait du code mort, et une confiance qui plonge
    couperait de nouveau la piste — donc perdrait des franchissements.
    """
    floor = detector_floor()

    assert floor == _load(TRACKER_CONFIG)["track_low_thresh"]
    assert floor < BASE_HIGH, "sans écart, la bande basse est vide"


def test_le_defaut_des_reglages_est_bien_celui_du_fichier_versionne() -> None:
    """Les deux sources doivent dire la même chose, sinon l'une des deux ment.

    Le fichier porte la valeur de base et le réglage la surcharge : tant qu'ils
    s'accordent, lire l'un ou l'autre donne la vérité. Les laisser diverger
    rendrait le fichier versionné trompeur pour quiconque le lit sans savoir qu'un
    réglage existe — et c'est le premier endroit où on regarde.
    """
    assert Settings(_env_file=None).tracker_gmc == _gmc_of(TRACKER_CONFIG)  # type: ignore[call-arg]
