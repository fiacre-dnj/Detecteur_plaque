"""Découpage vertical par feature.

Une feature est un dossier autonome qui porte son domaine, son application, son
infrastructure, son transport et ses tests. Elle se lit — et se supprime — d'un
bloc.

Une feature n'importe **jamais** une autre feature autrement que par un port
explicite. `tests/test_architecture.py` échoue si c'est le cas.
"""

from __future__ import annotations
