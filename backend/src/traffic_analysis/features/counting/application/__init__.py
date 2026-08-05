"""Orchestration du comptage : ports, DTO, service d'analyse, sérialiseurs.

Cette couche connaît l'**ordre** du pipeline et rien d'autre. Elle ne sait ni
d'où viennent les images, ni où va le résultat.
"""

from __future__ import annotations
