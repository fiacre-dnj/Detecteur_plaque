"""Le cœur métier : comptage de véhicules.

Détection et suivi viennent d'ailleurs (feature `models_registry`, derrière un
port). Cette feature ne fait que **compter** : franchissements de lignes,
présence en zone, identités, vitesses.
"""

from __future__ import annotations
