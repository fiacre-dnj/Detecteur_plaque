"""Forme canonique d'un texte de plaque.

Pur : ni OpenCV, ni onnxruntime, ni numpy. Trois raisons de placer cette règle
**ici** et pas dans l'adaptateur, la troisième étant décisive :

1. c'est une **règle métier** — quels caractères une plaque peut porter, quelle
   longueur est plausible — pas une adaptation de bibliothèque ;
2. le vote de `plate_vote.py` **compare des chaînes** : la clé de comparaison doit
   être décidée par le domaine qui l'utilise, pas ailleurs ;
3. le `FakePlateReader` des tests doit pouvoir être **sale**. Si l'adaptateur
   normalisait, la doublure devrait normaliser aussi pour ressembler à la
   production — et une doublure qui fait le travail de la production est exactement
   le mécanisme par lequel deux vrais bugs ont traversé 500 tests verts. En plaçant
   la normalisation ici, la doublure rend `"ab-123-cd "` et le test affirme
   `"AB-123-CD"` : l'assertion **prouve** que la normalisation a tourné.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Caractères qu'une plaque peut réellement porter.
ALPHANUMERIC = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

#: Le tiret est conservé comme séparateur — `AB-123-CD` est la forme française — et
#: n'est jamais significatif au-delà de sa position.
SEPARATOR = "-"

#: Sous 4 caractères alphanumériques, ce n'est pas une plaque : c'est un fragment
#: de pare-chocs, un autocollant, ou trois pas de temps de bruit.
MIN_ALPHANUMERIC = 4

#: Au-delà de 10, ce n'est pas une plaque non plus : le modèle a lu la plaque ET le
#: nom du concessionnaire collé en dessous.
MAX_ALPHANUMERIC = 10


def normalise_plate_text(raw: str) -> str:
    """Forme canonique d'une lecture, ou `""` si elle n'est pas exploitable.

    `""` n'est pas une erreur : c'est un refus honnête, du même statut que le `None`
    de `build_signature`. Une lecture refusée ne vote pas, et le véhicule reste sans
    plaque plutôt que d'en porter une inventée.

    **Aucune substitution de glyphes ambigus** (O↔0, I↔1, S↔5), et c'est délibéré.
    Le modèle ne connaît pas le format des plaques du pays : décider que le
    troisième caractère « doit » être un chiffre, c'est inventer une information
    qu'on ne possède pas. Afficher une plaque fausse est bien pire que n'en afficher
    aucune — une chaîne à l'écran est crue. Une correction tenant compte du format
    national est un point d'extension, pas un détail d'implémentation.

    **Idempotente** : elle est appliquée deux fois dans le pipeline — une fois quand
    le service pose le texte brut du lecteur, une fois quand `record_plates`
    canonicalise — et un test le vérifie.
    """
    return normalise_plate_reading(raw)[0]


def normalise_plate_reading(
    raw: str, char_scores: Sequence[float] = ()
) -> tuple[str, tuple[float, ...]]:
    """Comme `normalise_plate_text`, mais **en emmenant les confiances avec elle**.

    Le vote par caractère de `plate_vote.py` compare des positions ; il lui faut donc
    la confiance du caractère *retenu*, alignée sur le texte *canonique*. Refaire cet
    alignement en aval serait impossible : la normalisation supprime des caractères,
    et rien dans la chaîne de sortie ne dit lesquels.

    C'est faisable parce que chaque étape de la normalisation ne fait que deux choses,
    jamais une troisième : convertir un caractère en un autre (`upper`), ou en
    supprimer un. Aucune n'en insère ni n'en réordonne — les confiances suivent donc
    exactement le même chemin que les caractères.

    `char_scores` peut être vide : un appelant qui n'a que du texte — la
    canonicalisation de `record_plates`, la doublure de test — n'a rien à fournir, et
    obtient un tuple vide en retour.
    """
    scored = len(char_scores) == len(raw)
    kept: list[tuple[str, float]] = [
        (character, float(char_scores[position]) if scored else 0.0)
        for position, character in enumerate(raw.upper())
        if character in ALPHANUMERIC or character == SEPARATOR
    ]

    # Réduction des séparateurs consécutifs puis retrait de ceux des extrémités :
    # `--AB--123-` et `AB-123` désignent la même plaque, et le vote doit les voir
    # comme une seule chaîne — sinon un tiret parasite crée un second candidat qui
    # divise les voix du bon.
    collapsed: list[tuple[str, float]] = []
    for character, score in kept:
        if character == SEPARATOR and (not collapsed or collapsed[-1][0] == SEPARATOR):
            continue
        collapsed.append((character, score))
    while collapsed and collapsed[-1][0] == SEPARATOR:
        collapsed.pop()

    text = "".join(character for character, _ in collapsed)
    length = sum(1 for character in text if character in ALPHANUMERIC)
    if length < MIN_ALPHANUMERIC or length > MAX_ALPHANUMERIC:
        return "", ()
    return text, tuple(score for _, score in collapsed) if scored else ()
