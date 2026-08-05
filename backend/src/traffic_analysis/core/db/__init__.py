"""Socle de persistance : moteur, session, base déclarative.

`core` ne connaît aucun modèle de feature — ce sont les features qui déclarent
leurs tables sur la `Base` d'ici. La flèche de dépendance ne va que dans un sens.
"""

from __future__ import annotations
