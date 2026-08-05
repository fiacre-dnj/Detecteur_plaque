"""Décodage JPEG — **de l'infrastructure, pas de l'application**.

Le test d'architecture l'a montré, et il avait raison : `cv2` est une bibliothèque
concrète, et la couche `application` parle à des ports. Le décodage vivait d'abord
dans `session_service.py`, ce qui mettait OpenCV au milieu de l'orchestration et
rendait le service intestable sans OpenCV installé — exactement la propriété que
l'architecture du projet existe pour préserver.

Ici, l'import est légitime et le module est trivial : une fonction, un adaptateur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt


def decode_jpeg(payload: bytes) -> npt.NDArray[np.uint8] | None:
    """Décode un JPEG en tableau BGR, ou `None` s'il est illisible.

    `None` plutôt qu'une exception : une frame tronquée par un réseau capricieux est
    un incident **normal** en temps réel, pas une erreur de programmation. Le client
    en enverra une autre dans 30 millisecondes ; fermer la session serait une
    réaction disproportionnée qui obligerait à tout reconstruire.

    BGR et non RGB : c'est ce qu'attend Ultralytics, et convertir ici décalerait les
    scores par rapport à une analyse différée sur la même image.
    """
    import cv2
    import numpy as np

    if len(payload) == 0:
        return None
    buffer = np.frombuffer(payload, dtype=np.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if decoded is None:
        return None
    return np.asarray(decoded, dtype=np.uint8)
