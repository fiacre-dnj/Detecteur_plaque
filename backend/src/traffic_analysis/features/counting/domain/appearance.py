"""Comparaison de deux apparences — la seule définition de « se ressembler ».

Dans le domaine et non dans l'adaptateur, pour la raison que
`counting/domain/__init__.py` énonce depuis ADR 0016 : « un descripteur de
ré-identification est du calcul, pas de l'infrastructure ». C'est ce qui autorise
`numpy` ici.

Et surtout : **trois lecteurs, un seul juge**. L'adaptateur produit les vecteurs, le
service les compare, le banc mesure la séparation. Trois produits scalaires écrits
séparément finiraient par différer sur la normalisation ou sur les bornes, et l'écart
serait invisible — deux scores plausibles qui ne veulent pas dire la même chose. Même
raison qui a fait naître `shared/lib/directions.ts` côté client.

**Aucun compteur ne lit ce module.** Il ne sert qu'à la recherche par image de
requête : ni `crossings`, ni `tracked_vehicles`, ni aucun `by_line` n'en dépendent, et
une analyse sans encodeur rend exactement les mêmes chiffres. C'est ce qui met cette
fonctionnalité hors du champ de l'abrogation d'ADR 0016, qui a supprimé la galerie
d'identités précisément parce qu'elle était branchée sur le comptage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt


def cosine_similarity(left: npt.NDArray[np.float32], right: npt.NDArray[np.float32]) -> float:
    """Ressemblance de deux vecteurs **déjà normalisés L2**, bornée à [-1, 1].

    Un simple produit scalaire, parce que la normalisation a lieu à la production —
    dans l'adaptateur, une fois — et non ici. Normaliser à la comparaison laisserait
    deux consommateurs le faire différemment, ou un seul l'oublier, auquel cas les
    scores sortiraient de [-1, 1] sans que rien ne le signale.

    Le bornage explicite n'est pas de la coquetterie : l'arithmétique flottante rend
    régulièrement 1,0000001 pour un vecteur comparé à lui-même, et un score au-dessus
    de 1 affiché en pourcentage donnerait « 100,00001 % de ressemblance ».

    **Ce que ce nombre ne vaut pas.** Mesuré (ADR 0048), les distributions se
    recouvrent : deux vues du même véhicule descendent à 0,387, deux véhicules
    différents montent à 0,891. Aucun seuil global n'est donc à la fois sûr et utile,
    et c'est pourquoi ce score est publié **brut** et classé, jamais transformé en
    verdict côté serveur.
    """
    return float(np.clip(np.dot(left, right), -1.0, 1.0))


def best_similarity(vector: npt.NDArray[np.float32], views: npt.NDArray[np.float32]) -> float:
    """La **meilleure** ressemblance entre un vecteur et un jeu de vues empilées.

    `views` est une matrice `(k, d)` de vecteurs eux aussi normalisés L2 : le produit
    matrice-vecteur rend les `k` similarités d'un coup, et on garde la plus haute.

    **Pourquoi comparer plusieurs vues plutôt qu'une.** Deux vues d'un même véhicule
    prises à des instants différents ne se ressemblent pas autant qu'on croit —
    mesuré, elles descendent à 0,387 (ADR 0048), parce que le prétraitement étire la
    vignette au carré et que la déformation suit le rapport d'aspect de la boîte, qui
    change avec la distance et l'angle. Comparer une vue à **une seule** vue de
    référence, c'est donc jouer sur la chance que les deux se correspondent. Comparer
    à toutes celles qu'on a retenues, c'est laisser la bonne paire se déclarer.

    Ici et non dans la galerie, pour la raison qui a mis `cosine_similarity` dans ce
    module : **un seul juge**. Un `views @ vector` écrit ailleurs finirait par
    différer sur la normalisation ou sur les bornes, et l'écart serait invisible.

    Rend `-1.0` sur un jeu vide — la borne basse de l'échelle, jamais `0.0`, qui se
    lirait comme « mesuré, et sans ressemblance ». L'appelant, lui, distingue déjà le
    cas « aucun déposant » en amont.
    """
    if views.size == 0:
        return -1.0
    return float(np.clip(np.max(views @ vector), -1.0, 1.0))
