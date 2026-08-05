"""Domaine pur du comptage.

Aucun import de `fastapi`, `sqlalchemy`, `ultralytics` ni `cv2` n'est autorisé
ici — `tests/test_architecture.py` échoue si l'un apparaît. `numpy` est permis :
un descripteur de ré-identification est du calcul, pas de l'infrastructure.

C'est cette pureté qui permet à la CI de tourner sans GPU, sans poids et sans
ultralytics.
"""

from __future__ import annotations
