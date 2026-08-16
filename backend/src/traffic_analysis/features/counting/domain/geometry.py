"""Géométrie du comptage — fonctions pures, en pixels de la vidéo source.

Ce module définit **la convention de sens** partagée avec le frontend, qui s'en
sert pour dessiner les flèches du registre. Changer le signe ici ferait mentir
l'interface sans qu'aucun test d'interface ne s'en aperçoive.

Aucune dépendance : ni FastAPI, ni ultralytics, ni SQLAlchemy, ni horloge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    """Un point en pixels de la vidéo source.

    `frozen` parce qu'un point partagé entre une ligne et son état de suivi ne
    doit jamais être modifié par un tiers ; `slots` parce qu'une timeline de
    54 000 frames en instancie des centaines de milliers.
    """

    x: float
    y: float


def side_of_line(a: Point, b: Point, p: Point) -> int:
    """Côté signé de `p` par rapport à la ligne orientée `a`→`b` : -1, 0 ou +1.

    C'est le produit vectoriel des vecteurs `ab` et `ap`. Son signe est **la
    convention de sens du projet** : la direction d'un franchissement est le
    signe du côté d'**arrivée**, exposé tel quel dans l'API et libellé « A→B » /
    « B→A » dans l'interface.

    `0` signifie « pile sur la droite », et le compteur doit alors **attendre la
    frame suivante** plutôt que de trancher : choisir arbitrairement un côté
    produirait un faux franchissement chaque fois qu'un centroïde effleure la
    ligne.

    Attention : le côté est défini par rapport à la **droite infinie**. Un point
    situé au-delà des extrémités du segment a donc un côté bien défini — c'est
    exactement pourquoi `segments_intersect` est indispensable en plus.
    """
    cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
    if cross > 0:
        return 1
    if cross < 0:
        return -1
    return 0


def segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Les segments `[p1,p2]` et `[p3,p4]` se croisent-ils réellement ?

    **Pourquoi cette fonction existe.** Le seul changement de signe de
    `side_of_line` bascule sur la ligne *infinie*. Un véhicule qui passe bien
    au-delà des extrémités tracées par l'utilisateur change donc de côté sans
    jamais couper le segment dessiné — et serait compté (piège 7 de prompt/13).

    Test des quatre orientations : les segments se croisent si chacun sépare les
    extrémités de l'autre. Le contact par une extrémité **compte** comme une
    intersection : le franchissement a réellement lieu, et le refuser perdrait le
    véhicule dont le centroïde atterrit pile sur la ligne à une frame.

    Deux segments **colinéaires ne se croisent pas** : un véhicule qui longe
    exactement la ligne ne la franchit pas. Compter ce cas ferait exploser les
    compteurs d'une ligne mal placée, parallèle à la voie.
    """
    d1 = side_of_line(p3, p4, p1)
    d2 = side_of_line(p3, p4, p2)
    d3 = side_of_line(p1, p2, p3)
    d4 = side_of_line(p1, p2, p4)

    # Cas général : chaque segment sépare strictement les extrémités de l'autre.
    if d1 != d2 and d3 != d4:
        # Un segment de longueur nulle (première frame d'une piste, où
        # `previous_centroid` est absent) donne d3 == d4 == 0 et n'entre donc
        # jamais ici, sauf s'il touche la droite support — ce que le garde
        # ci-dessous écarte.
        return not (d1 == d2 == 0 or d3 == d4 == 0)
    return False


def point_in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    """Le point est-il à l'intérieur du polygone ? (lancer de rayon)

    Gère les polygones **concaves** : une voie ou une zone tracée à la main l'est
    presque toujours, et un test par boîte englobante dirait « dedans » pour le
    creux d'un U.

    Moins de trois sommets n'est pas une surface : une zone en cours de tracé
    rendrait sinon le masque « ignorer hors zone » clignotant à chaque clic.

    Le comportement sur une arête est **asymétrique** (l'arête basse est incluse,
    la haute exclue, par la comparaison `y1 > y != y2 > y`). L'important n'est pas
    la convention retenue mais sa **stabilité** : une piste immobile sur un bord
    ne doit pas basculer dedans/dehors d'une frame à l'autre, car chaque front
    produirait une entrée de zone.
    """
    if len(polygon) < 3:
        return False

    inside = False
    x, y = point.x, point.y
    previous = polygon[-1]
    for current in polygon:
        # Le rayon part vers les x négatifs. On ne compte que les arêtes que la
        # ligne horizontale y = point.y traverse effectivement.
        if (current.y > y) != (previous.y > y):
            # Abscisse de l'intersection de l'arête avec cette horizontale.
            crossing_x = (previous.x - current.x) * (y - current.y) / (
                previous.y - current.y
            ) + current.x
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def distance(a: Point, b: Point) -> float:
    """Distance euclidienne, en pixels source."""
    return math.hypot(b.x - a.x, b.y - a.y)


def signed_line_offset(a: Point, b: Point, p: Point) -> float:
    """Distance **signée** de `p` à la droite `a`→`b`, en pixels.

    `side_of_line` en est le signe, et rien d'autre : les deux fonctions décrivent
    la même quantité, l'une en n'en gardant que l'orientation. Le côté seul suffit
    à décider d'un franchissement, mais pas à décider qu'un franchissement est
    **crédible** — pour cela il faut savoir de combien, et c'est ce que rend cette
    fonction.

    Une ligne dégénérée rend `0.0` : sans direction, il n'y a pas de côté.
    """
    dx = b.x - a.x
    dy = b.y - a.y
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return 0.0
    return (dx * (p.y - a.y) - dy * (p.x - a.x)) / length


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    """Distance de `p` au **segment** `[a,b]`, et non à la droite infinie.

    La distinction est celle qui sépare `side_of_line` de `segments_intersect`, et
    elle compte autant ici : un véhicule qui s'arrête à trois mètres au-delà de
    l'extrémité d'une ligne est **loin du segment** tout en étant à quelques pixels
    de sa droite support. Mesurer contre la droite le dirait « à portée » et
    fabriquerait un quasi-franchissement là où il n'y a que du hors-champ.

    Un segment de longueur nulle — deux clics au même endroit, refusé plus haut
    mais pas impossible dans une configuration ancienne — rend la distance au
    point `a` plutôt que de diviser par zéro.
    """
    dx = b.x - a.x
    dy = b.y - a.y
    length_squared = dx * dx + dy * dy
    if length_squared <= 0.0:
        return distance(p, a)

    # Projection de `ap` sur `ab`, bornée à [0, 1] : c'est le bornage qui fait la
    # différence entre le segment et sa droite.
    t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / length_squared
    t = max(0.0, min(1.0, t))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
