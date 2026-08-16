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
    resolved_tracker_config,
)

if TYPE_CHECKING:
    from pathlib import Path


def _gmc_of(path: Path) -> str:
    return str(yaml.safe_load(path.read_text(encoding="utf-8"))["gmc_method"])


def test_la_valeur_du_fichier_de_base_rend_le_fichier_de_base() -> None:
    """Cas courant : rien à dériver, donc aucun fichier temporaire.

    C'est ce qui garantit qu'en configuration par défaut le service charge le
    fichier **versionné** — celui qu'on peut lire dans le dépôt pour savoir ce qui
    tourne, sans aller fouiller un dossier temporaire.
    """
    assert resolved_tracker_config(_gmc_of(TRACKER_CONFIG)) == TRACKER_CONFIG


def test_une_autre_valeur_produit_un_fichier_derive_qui_la_porte() -> None:
    """Le réglage doit **arriver** jusqu'au fichier, pas seulement être accepté."""
    derived = resolved_tracker_config("sparseOptFlow")

    assert derived != TRACKER_CONFIG
    assert _gmc_of(derived) == "sparseOptFlow"


def test_le_fichier_derive_conserve_tout_le_reste() -> None:
    """Seule la compensation change ; les seuils d'association ne bougent pas.

    `track_buffer` en particulier est le **miroir exact** de `max_lost_ms = 2500`
    du domaine. Une dérivation qui le perdrait désaccorderait le moteur et le
    domaine sur ce qu'est « une piste perdue », et la ré-identification
    travaillerait sur des identités que le tracker a déjà recyclées.
    """
    base = yaml.safe_load(TRACKER_CONFIG.read_text(encoding="utf-8"))
    derived = yaml.safe_load(resolved_tracker_config("orb").read_text(encoding="utf-8"))

    assert derived == {**base, "gmc_method": "orb"}


def test_le_defaut_des_reglages_est_bien_celui_du_fichier_versionne() -> None:
    """Les deux sources doivent dire la même chose, sinon l'une des deux ment.

    Le fichier porte la valeur de base et le réglage la surcharge : tant qu'ils
    s'accordent, lire l'un ou l'autre donne la vérité. Les laisser diverger
    rendrait le fichier versionné trompeur pour quiconque le lit sans savoir qu'un
    réglage existe — et c'est le premier endroit où on regarde.
    """
    assert Settings(_env_file=None).tracker_gmc == _gmc_of(TRACKER_CONFIG)  # type: ignore[call-arg]
