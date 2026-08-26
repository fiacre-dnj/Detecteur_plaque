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
    LIVE_TRACKER_KEYS,
    REQUEST_HIGH_KEYS,
    REQUEST_TRACKER_KEYS,
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

#: Le plancher que le fichier versionné porte — celui qui valait pour tout le monde
#: quand il était figé.
BASE_LOW = float(_load(TRACKER_CONFIG)["track_low_thresh"])  # type: ignore[arg-type]


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
    floor = detector_floor(BASE_HIGH)

    assert floor == _load(TRACKER_CONFIG)["track_low_thresh"]
    assert floor < BASE_HIGH, "sans écart, la bande basse est vide"


def test_le_plancher_ne_bouge_pas_au_dessus_du_seuil_du_fichier() -> None:
    """**La preuve de migration** : l'usage courant ne change pas d'un chiffre.

    Le plancher ne descend que sous le seuil de piste du fichier versionné. Au
    défaut du contrat (0,35) comme partout au-dessus de 0,25, il vaut exactement ce
    qu'il valait quand il était figé — donc aucune analyse existante ne bouge.
    """
    for confidence in (BASE_HIGH, 0.35, 0.5, 0.99):
        assert detector_floor(confidence) == BASE_LOW


def test_le_plancher_suit_le_curseur_quand_il_descend() -> None:
    """Sous le seuil du fichier, le curseur doit redevenir opérant.

    C'est le geste de l'utilisateur qui ne voit pas ses motos : il descend
    « Confiance véhicules ». Tant que le plancher restait figé à 0,10, le détecteur
    ne rendait **aucune** boîte en dessous, donc descendre sous 0,10 ne changeait
    rien — le curseur était mort sur tout le bas de sa plage.
    """
    assert detector_floor(0.20) < detector_floor(BASE_HIGH)
    assert detector_floor(0.05) < detector_floor(0.20)


def test_la_bande_basse_n_est_jamais_vide_sur_toute_la_plage() -> None:
    """**Le test qui empêche ADR 0024 de se défaire par l'autre bout.**

    La bande basse de ByteTrack est `track_low_thresh < s < track_high_thresh`.
    Avec un plancher figé à 0,10 et un seuil de requête à 0,05, cet ensemble est
    **vide** : la seconde association redevient du code mort sans qu'aucun message
    ne le dise, et une confiance qui plonge coupe de nouveau la piste.

    Vérifié valeur par valeur sur toute la plage du contrat
    (`AnalysisRequestSchema.confidence_threshold`, `ge=0.01, le=0.99`), y compris
    aux deux bornes — c'est précisément là que la panne vivait.

    La plage entière est passée sur la **fonction pure** : chaque appel à
    `resolved_tracker_config` écrit un fichier, et cent fichiers temporaires pour
    vérifier une inégalité arithmétique seraient un test lent qui ne prouve rien de
    plus. Le fichier lui-même est vérifié juste après, sur les valeurs basses qui
    sont les seules où le plancher bouge.
    """
    for step in range(1, 100):
        confidence = step / 100.0
        assert detector_floor(confidence) < confidence, f"bande vide à {confidence}"

    for confidence in (0.01, 0.05, 0.20):
        derived = _load(resolved_tracker_config("orb", confidence))
        low = float(derived["track_low_thresh"])  # type: ignore[arg-type]
        high = float(derived["track_high_thresh"])  # type: ignore[arg-type]

        assert low < high, f"bande basse vide à confiance {confidence}"
        assert low == detector_floor(confidence)


def test_le_defaut_des_reglages_est_bien_celui_du_fichier_versionne() -> None:
    """Les deux sources doivent dire la même chose, sinon l'une des deux ment.

    Le fichier porte la valeur de base et le réglage la surcharge : tant qu'ils
    s'accordent, lire l'un ou l'autre donne la vérité. Les laisser diverger
    rendrait le fichier versionné trompeur pour quiconque le lit sans savoir qu'un
    réglage existe — et c'est le premier endroit où on regarde.
    """
    assert Settings(_env_file=None).tracker_gmc == _gmc_of(TRACKER_CONFIG)  # type: ignore[call-arg]


def test_le_fichier_derive_ne_change_que_les_cles_annoncees() -> None:
    """`resolved_tracker_config` écrit exactement le mouvement et les clés de requête.

    Ce test tient l'autre bout de `reset_trackers` : celle-ci ne repose que
    `REQUEST_TRACKER_KEYS` sur un tracker déjà construit. Une clé de plus dans le
    fichier dérivé et non dans cet ensemble serait un réglage qui n'arriverait au
    tracker qu'à la **première** analyse du processus — la panne exacte qu'on vient
    de corriger, revenue par l'autre porte.

    **Inclusion et non égalité**, depuis que le plancher suit le curseur : à seuil
    haut il garde la valeur du fichier de base, donc il ne figure pas parmi les
    clés *modifiées* alors qu'il est bien une clé de requête. Ce qui compte est
    qu'aucune clé ne change **hors** de l'ensemble reposé — le second cas, à seuil
    bas, vérifie que le plancher y entre bien quand il bouge.
    """
    base = _load(TRACKER_CONFIG)

    derived = _load(resolved_tracker_config("orb", 0.5))
    changed = {key for key, value in derived.items() if base.get(key) != value}
    assert changed <= {"gmc_method", *REQUEST_TRACKER_KEYS}
    assert changed >= {"gmc_method", *REQUEST_HIGH_KEYS}

    low = _load(resolved_tracker_config("orb", 0.05))
    changed_low = {key for key, value in low.items() if base.get(key) != value}
    assert changed_low == {"gmc_method", *REQUEST_TRACKER_KEYS}


def test_les_cles_de_requete_sont_relues_a_chaque_image() -> None:
    """**La condition qui rend `reset_trackers` suffisante.**

    Les clés de requête doivent être lues par le tracker sur `self.args` à chaque
    image, et non consommées dans son `__init__`. Sinon les reposer ne changerait
    rien et il faudrait reconstruire le tracker — ce qui obligerait à désinscrire
    les rappels d'Ultralytics, dont un doublon appellerait `tracker.update()` deux
    fois par image.

    Vérifié dans la roue installée : `byte_tracker.py` lit `track_high_thresh` et
    `new_track_thresh` dans `update()` / `init_track()`.
    """
    assert REQUEST_TRACKER_KEYS <= LIVE_TRACKER_KEYS
