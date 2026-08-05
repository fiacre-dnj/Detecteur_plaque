"""Estimation de vitesse par identité, en pixels par seconde de **temps de scène**.

Deux principes gouvernent ce module :

1. **Le lissage est nécessaire.** Une boîte de détection tremble d'un pixel entre
   deux frames ; à 40 ms d'intervalle, cela vaut 25 px/s de pointe sur un véhicule
   parfaitement immobile. Sans amortissement, le chiffre affiché danse.
2. **Ne rien inventer.** Une seule observation ne donne pas de vitesse (`None`, pas
   `0.0` — un véhicule à l'arrêt et un véhicule qu'on vient de voir ne sont pas la
   même chose). Une conversion en km/h sans échelle fournie par l'utilisateur
   n'existe pas.
"""

from __future__ import annotations

from dataclasses import dataclass

from traffic_analysis.features.counting.domain.geometry import Point, distance

# Poids de la nouvelle mesure dans le lissage exponentiel. 0.3 amortit le
# tremblement de détection tout en suivant une accélération réelle en ~5 frames.
EMA_ALPHA = 0.3

# Au-delà de ce trou de scène, deux positions ne décrivent plus un déplacement
# continu : le véhicule a pu tourner, ralentir ou être confondu avec un autre.
# Intégrer la distance inventerait une trajectoire rectiligne non observée.
MAX_GAP_MS = 1000.0

_MS_PER_SECOND = 1000.0
_SECONDS_PER_HOUR = 3600.0


@dataclass(slots=True)
class _IdentitySpeed:
    """État vivant de l'estimation pour une identité."""

    last_centroid: Point
    last_timestamp_ms: float
    smoothed_px_s: float | None = None
    total_distance_px: float = 0.0
    total_duration_ms: float = 0.0


class SpeedEstimator:
    """Vitesse instantanée lissée et vitesse moyenne, par identité globale.

    Par identité et non par piste : c'est ce qui permet à la vitesse moyenne du
    registre de survivre à une occlusion, comme le reste des agrégats.
    """

    __slots__ = ("_states",)

    def __init__(self) -> None:
        self._states: dict[int, _IdentitySpeed] = {}

    def observe(self, global_id: int, centroid: Point, timestamp_ms: float) -> float | None:
        """Enregistre une position et rend la vitesse lissée, ou `None`.

        `None` est rendu dans deux cas, tous les deux honnêtes : première
        observation de cette identité, et reprise après un trou trop long.
        """
        state = self._states.get(global_id)
        if state is None:
            self._states[global_id] = _IdentitySpeed(centroid, timestamp_ms)
            return None

        elapsed_ms = timestamp_ms - state.last_timestamp_ms

        # Un trou trop long, ou un temps qui n'avance pas (deux observations sur
        # la même frame), ne permettent aucun calcul : on ré-amorce.
        if elapsed_ms <= 0 or elapsed_ms > MAX_GAP_MS:
            state.last_centroid = centroid
            state.last_timestamp_ms = timestamp_ms
            state.smoothed_px_s = None
            return None

        travelled = distance(state.last_centroid, centroid)
        instant_px_s = travelled / (elapsed_ms / _MS_PER_SECOND)

        state.smoothed_px_s = (
            instant_px_s
            if state.smoothed_px_s is None
            else state.smoothed_px_s + EMA_ALPHA * (instant_px_s - state.smoothed_px_s)
        )
        # Les cumuls servent la moyenne du registre. Ils n'intègrent que les
        # intervalles réellement observés, donc jamais le saut d'une occlusion.
        state.total_distance_px += travelled
        state.total_duration_ms += elapsed_ms
        state.last_centroid = centroid
        state.last_timestamp_ms = timestamp_ms

        return state.smoothed_px_s

    def average_px_s(self, global_id: int) -> float | None:
        """Vitesse moyenne sur les intervalles observés, ou `None`.

        Moyenne sur la distance et la durée cumulées, et non moyenne des vitesses
        instantanées : la seconde donnerait un poids égal à une frame de 40 ms et
        à un intervalle de 900 ms.
        """
        state = self._states.get(global_id)
        if state is None or state.total_duration_ms <= 0:
            return None
        return state.total_distance_px / (state.total_duration_ms / _MS_PER_SECOND)


def to_kmh(px_s: float | None, pixels_per_meter: float | None) -> float | None:
    """Convertit des pixels par seconde en km/h, **seulement si c'est possible**.

    Rend `None` sans échelle, avec une échelle nulle ou négative (un curseur
    laissé à zéro signifie « non définie », pas « zéro pixel par mètre »), ou sans
    vitesse.

    C'est le point d'honnêteté du module : sans échelle fournie par
    l'utilisateur, la vitesse reste en px/s. La convertir serait inventer une
    distance réelle, et un chiffre inventé dans un rapport de comptage est pire
    qu'une case vide.
    """
    if px_s is None or pixels_per_meter is None or pixels_per_meter <= 0:
        return None
    metres_per_second = px_s / pixels_per_meter
    return metres_per_second * _SECONDS_PER_HOUR / 1000.0
