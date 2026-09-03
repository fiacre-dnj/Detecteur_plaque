"""Les arguments passés à `model.track()` — vérifiés sur la **source**.

Ces deux arguments décident du nombre de véhicules comptés, et aucun test ne
pouvait les voir : les 500 tests du comptage injectent un `FakeEngine` et
n'atteignent jamais `UltralyticsEngine`. C'est le but de l'architecture — la CI
tourne sans GPU, sans poids et sans ultralytics — et son prix : un chemin utilisé
uniquement en production n'est couvert par personne.

Le test lit donc le **texte du module** plutôt que d'exécuter l'appel. C'est
inhabituel et volontairement modeste : construire un faux modèle, un faux registre
et une fausse vidéo pour observer un appel coûterait bien plus qu'il ne prouve, et
il n'existe pas d'autre façon d'atteindre ce code sans ultralytics. Ce que ce test
garantit est étroit mais réel : personne ne retirera silencieusement l'un des deux
arguments.

Un `agnostic_nms` retiré ne casserait rien de visible — il ferait simplement
compter une camionnette deux fois, de temps en temps.
"""

from __future__ import annotations

import re
from pathlib import Path

import traffic_analysis.features.models_registry.infrastructure.ultralytics_engine as engine_module

SOURCE = Path(engine_module.__file__).read_text(encoding="utf-8")


def _track_calls(source: str) -> list[str]:
    """Extrait le texte des arguments de chaque `.track(...)`.

    Par équilibrage de parenthèses et non par expression régulière : les appels
    n'ont pas la même indentation — certains sont dans un `with`, d'autres non —
    et une expression paresseuse sur une parenthèse fermante indentée les fusionnait
    en un seul bloc. Le test de garde ci-dessous l'a attrapé immédiatement, ce qui
    est exactement pourquoi il existe.
    """
    calls: list[str] = []
    for match in re.finditer(r"\.track\(", source):
        start = match.end()
        depth = 1
        index = start
        while index < len(source) and depth:
            if source[index] == "(":
                depth += 1
            elif source[index] == ")":
                depth -= 1
            index += 1
        calls.append(source[start : index - 1])
    return calls


#: Les **deux** appels au moteur :
#:
#: 1. `model.track(source=[image for _, image in chunk], …)` — le différé, qui décode
#:    lui-même dans un fil séparé et confie les images par lots ;
#: 2. `self._model.track(source=image, …)` — le direct.
#:
#: Il y en a eu trois, et ce garde-fou a signalé les deux changements en échouant :
#: l'apparition du direct, puis la disparition du chemin « avec borne de début ».
#: Ce dernier existait parce que le chargeur d'Ultralytics ne sait pas se déplacer ;
#: depuis que le différé décode lui-même, le déplacement n'est plus un cas
#: particulier et les deux chemins n'en font qu'un — celui qui reste porte donc les
#: garanties des deux.
TRACK_CALLS = _track_calls(SOURCE)

#: Nombre d'appels attendus. **À changer en connaissance de cause** : chaque nouvel
#: appel doit d'abord satisfaire les trois vérifications ci-dessous.
EXPECTED_TRACK_CALLS = 2


def test_tous_les_chemins_appellent_bien_le_tracker() -> None:
    """Garde-fou du garde-fou : si l'expression ne trouve plus rien, les tests
    suivants passeraient à vide et ne prouveraient plus rien."""
    assert len(TRACK_CALLS) == EXPECTED_TRACK_CALLS, (
        f"{len(TRACK_CALLS)} appel(s) à `.track(` trouvé(s) au lieu de "
        f"{EXPECTED_TRACK_CALLS} — mettre à jour ce test en vérifiant que le "
        "nouvel appel satisfait bien les trois garanties ci-dessous, sinon elles "
        "ne portent plus sur tout le code."
    )


def test_le_nms_ignore_la_classe_dans_les_deux_modes() -> None:
    """Piège 5 de prompt/13, et le réglage qui manquait réellement.

    Le NMS par défaut d'Ultralytics est *class-aware* : il ne compare que des
    boîtes de même classe. Une camionnette scorée `car 0.52` **et** `truck 0.41`
    survit donc en double, devient deux pistes, deux identités, et compte deux
    fois. `classes=[2,3,5,7]` ne suffit pas — il restreint les classes, il ne
    déduplique pas entre elles.

    Le commentaire du code affirmait pendant tout le projet que « `classes=` plus
    le NMS d'Ultralytics traitent le cas ». C'était faux.
    """
    for index, call in enumerate(TRACK_CALLS):
        assert "agnostic_nms=True" in call, (
            f"L'appel n°{index + 1} à `.track()` n'active pas `agnostic_nms`. "
            "Une camionnette y sera comptée deux fois, sans aucune erreur."
        )


def test_le_nms_par_groupe_est_installe_dans_les_deux_modes() -> None:
    """**Les deux mécanismes sont nécessaires, et aucun ne suffit** — ADR 0057.

    `agnostic_nms=True` seul supprime la moto sous son pilote. Le découpage par
    groupe corrige cela, et il tient à deux fils que rien d'autre ne surveille :

    - `predictor=` couvre le cas « aucun prédicteur encore construit », c'est-à-dire
      un déploiement où le préchauffage est désactivé ;
    - `install_group_aware_nms` couvre le cas inverse, qui est le **cas normal** : le
      préchauffage appelle `model.predict()` au démarrage, `predict()` ne construit
      son prédicteur qu'une fois par instance, et `ModelRegistry` garde ses instances
      d'un job à l'autre. Sans l'échange de classe, `predictor=` serait ignoré pour
      toute la vie du processus et le correctif serait entièrement inerte.

    En perdre un rendrait le NMS par groupe silencieusement inopérant dans une
    configuration sur deux, sans qu'aucun chiffre ne paraisse faux.
    """
    for index, call in enumerate(TRACK_CALLS):
        assert "predictor=_group_aware_predictor()" in call, (
            f"L'appel n°{index + 1} à `.track()` ne passe pas le prédicteur par groupe. "
            "Sans préchauffage, un pilote y effacera sa moto."
        )
    assert SOURCE.count("install_group_aware_nms(") == 3, (
        "Il doit y avoir la définition et **deux** appels — différé et direct. "
        "Le direct partage l'instance résidente avec le différé : l'oublier ferait "
        "compter un motard pour un seul objet en caméra."
    )


def test_les_classes_de_vehicules_sont_restreintes_dans_les_deux_modes() -> None:
    """Sans `classes=`, le modèle rend les 80 classes de COCO.

    Les piétons, les feux et les panneaux deviendraient des pistes, seraient
    comptés au franchissement, et le post-traitement paierait un travail entier
    pour des objets qu'on jette ensuite.
    """
    for index, call in enumerate(TRACK_CALLS):
        assert "classes=" in call, f"L'appel n°{index + 1} ne restreint pas les classes."


def test_le_suivi_persiste_entre_les_appels() -> None:
    """`persist=True` est ce qui fait d'une suite d'images un flux.

    Sans lui, chaque frame repartirait avec des identifiants neufs : rien ne
    serait jamais suivi, et le comptage rendrait autant de véhicules uniques que
    de détections.
    """
    for index, call in enumerate(TRACK_CALLS):
        assert "persist=True" in call, f"L'appel n°{index + 1} ne persiste pas le suivi."


def test_le_plafond_de_detections_est_explicite_dans_les_deux_modes() -> None:
    """`max_det` était subi, alors que le détecteur de plaques nomme les siens.

    300 est le défaut d'Ultralytics : le nommer ne change aucun chiffre. Mais la
    troncature s'applique **par score décroissant** (`nms.py`, `i = i[:max_det]`), donc
    elle jette les boîtes les plus faibles — c'est-à-dire les petits objets qu'on
    cherche justement à récupérer. Un plafond qu'on subit sans le voir est exactement le
    genre de réglage qui fait chercher la panne ailleurs.
    """
    for index, call in enumerate(TRACK_CALLS):
        assert "max_det=self._max_det" in call, (
            f"L'appel n°{index + 1} à `.track()` laisse le plafond de détections "
            "implicite : une scène chargée y perdra ses petits objets en silence."
        )
