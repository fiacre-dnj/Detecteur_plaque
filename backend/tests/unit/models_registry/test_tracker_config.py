"""Le fichier de configuration du tracker doit **exister**.

Ce test vient d'un bug réel, et il mérite d'être expliqué parce que sa cause est
structurelle plutôt qu'accidentelle.

`CONFIG_DIR` est calculé en remontant les dossiers parents du fichier source
(`Path(__file__).parents[n]`). Ce compteur était faux d'un cran, donc le chemin
pointait vers `backend/src/config/` au lieu de `backend/config/`. Conséquence :
**toute analyse réelle échouait** sur un `FileNotFoundError` levé par Ultralytics,
avec un message parlant d'un fichier YAML — très loin de la cause.

Et rien ne l'attrapait. Les 500 tests du comptage injectent un `FakeEngine` : ils
ne passent jamais par `UltralyticsEngine`, et c'est **exactement le but** de cette
architecture (la CI tourne sans GPU, sans poids et sans ultralytics). Le prix de
cette isolation est qu'un chemin utilisé uniquement en production n'est couvert par
personne. Ce test paie ce prix, sans importer ultralytics : il vérifie une
constante et un fichier sur disque, rien de plus.
"""

from __future__ import annotations

from traffic_analysis.features.models_registry.infrastructure.ultralytics_engine import (
    CONFIG_DIR,
    TRACKER_CONFIG,
)


def test_le_fichier_de_configuration_du_tracker_existe() -> None:
    """Sans lui, `model.track()` lève et **toute** analyse réelle échoue.

    Le message d'échec cite le chemin calculé : c'est ce qui rend le diagnostic
    immédiat si le compteur de dossiers parents redevient faux.
    """
    assert TRACKER_CONFIG.is_file(), (
        f"Configuration du tracker introuvable à « {TRACKER_CONFIG} ». "
        f"Vérifier le nombre de dossiers parents dans `CONFIG_DIR` — il a déjà "
        f"été faux d'un cran, et aucune analyse ne fonctionnait."
    )


def test_le_dossier_de_configuration_est_a_la_racine_du_backend() -> None:
    """`backend/config/`, et non `backend/src/config/`.

    L'erreur historique exactement : `parents[4]` au lieu de `parents[5]`.
    """
    assert CONFIG_DIR.name == "config"
    assert CONFIG_DIR.parent.name == "backend"


def test_la_configuration_declare_bien_botsort_avec_reid() -> None:
    """Le pipeline attendu est BoT-SORT **avec** ré-identification.

    C'est ce que `prompt/04` exige, et c'est la raison pour laquelle les poids
    doivent être des `.pt` natifs : un export ONNX ne porte pas ce pipeline
    (ADR 0002). Un fichier présent mais déclarant `bytetrack` ferait tourner
    l'analyse sans ré-identification, et les identités changeraient à chaque
    occlusion **sans qu'aucune erreur ne le signale**.
    """
    content = TRACKER_CONFIG.read_text(encoding="utf-8")

    assert "botsort" in content.lower()
    assert "with_reid" in content.lower() or "reid" in content.lower()
