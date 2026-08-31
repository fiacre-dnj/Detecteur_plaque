"""Quelles pistes méritent une inférence **coûteuse** sur cette image.

Deux étages posent exactement la même question et n'ont aucun rapport l'un avec
l'autre : la détection de plaques (une inférence 640×640 par recadrage de véhicule,
ADR 0030 et 0032) et l'encodage d'apparence de la recherche par image (21,8 ms de CPU
par vignette, ADR 0050). Tant que la règle vivait dans `plate_policy`, le second
l'aurait importée depuis un module dont la docstring parle de lisibilité de plaque —
et deux copies d'une règle de dépense finissent par diverger sur la piste qu'elles
servent en premier.

**Ce module ne connaît ni plaque ni apparence.** Il classe des candidates sur deux
faits — jamais servie, et large — qui se trouvent être les bons prédicteurs dans les
deux cas, pour des raisons différentes : la largeur du véhicule prédit celle de sa
plaque, et elle prédit aussi la séparation de son embedding (ADR 0048 : +0,462 à
208 px, +0,310 à 48 px).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["InferenceCandidate", "select_within_budget"]


@dataclass(frozen=True, slots=True)
class InferenceCandidate:
    """Une piste qui a passé les gardes de son étage, prête à être classée.

    Trois champs et pas la piste entière : le classement est une règle de dépense, il
    n'a aucune raison de connaître une `SessionTrack` — et cette séparation est ce qui
    le rend testable sur des tuples.
    """

    global_id: int
    width: float
    #: Cette piste n'a **jamais** été servie par cet étage.
    never_served: bool


def select_within_budget(candidates: Sequence[InferenceCandidate], budget: int) -> frozenset[int]:
    """Les `budget` pistes qui méritent l'inférence de cette image.

    Rend un ensemble d'identités et non une liste : l'appelant garde **son** ordre,
    qui est celui du suivi. Un budget nul ou supérieur au nombre de candidates ne
    retire rien — c'est le comportement historique, et le plafond reste donc
    strictement additif tant que personne ne le pose.

    **Ce qui n'est pas servi n'est pas perdu.** Rien n'étant enregistré pour une piste
    écartée, elle repasse candidate à l'image suivante : c'est un report, pas un
    abandon. La propriété tient parce que les deux étages posent leur question sur un
    état que l'inférence est seule à faire avancer.

    Le classement, dans cet ordre :

    1. **jamais servie d'abord.** Sans cette priorité, un véhicule qui apparaît au
       milieu d'un embouteillage pourrait traverser tout le champ sans jamais recevoir
       une seule mesure — un silence qui se lit comme une panne, pas comme une
       économie. Côté plaques c'est un rectangle qui ne s'affiche jamais ; côté
       recherche par image, un véhicule qui reste sans score de ressemblance ;
    2. **la plus large ensuite.** La largeur du véhicule est le meilleur prédicteur
       disponible de ce que l'inférence rendra. Pour une plaque, elle prédit sa
       largeur donc sa lisibilité — le plancher de lecture est mesuré à 64 px
       (invariant 12), et dépenser sur une piste dont la plaque fera 20 px achète une
       boîte que l'OCR refusera de lire. Pour une apparence, elle prédit la
       séparation de l'embedding (ADR 0048) ;
    3. **l'identité, à égalité stricte**, pour que deux courses du même clip
       dépensent au même endroit. Un `set` d'itération non déterministe rendrait deux
       analyses du même fichier légèrement différentes, ce qui est exactement le
       genre d'écart qu'on passe des jours à ne pas comprendre.
    """
    if budget <= 0 or len(candidates) <= budget:
        return frozenset(candidate.global_id for candidate in candidates)
    ranked = sorted(
        candidates,
        key=lambda candidate: (not candidate.never_served, -candidate.width, candidate.global_id),
    )
    return frozenset(candidate.global_id for candidate in ranked[:budget])
