/**
 * Géométrie du client — **copie minimale** du domaine backend.
 *
 * Ce module sert à **dessiner** et à **tester la sélection à la souris**. Il ne
 * compte rien : aucun franchissement, aucune statistique, aucune identité ne se
 * décide ici. Le comptage vit côté serveur, dans
 * `counting/domain/geometry.py`, et n'a pas de jumeau côté client (ADR 0003).
 *
 * Alors pourquoi dupliquer quoi que ce soit ? Parce que le canvas doit savoir de
 * quel côté d'une ligne se trouve un point pour **orienter la flèche de sens**
 * qu'il affiche, et savoir si le curseur est sur une forme pour la sélectionner.
 * Ces deux besoins sont locaux à l'affichage.
 *
 * **Le piège que cette duplication crée**, et la raison du test qui l'accompagne :
 * si `sideOfLine` rendait ici le signe opposé à celui du backend, les flèches
 * « A→B » et « B→A » de l'interface seraient inversées par rapport aux chiffres
 * du serveur. Rien ne planterait, aucun test backend ne le verrait, et
 * l'utilisateur lirait des sens faux avec des totaux justes. `geometry.test.ts`
 * fixe donc le signe sur des cas calculés à la main, identiques à ceux du test
 * Python.
 *
 * Toutes les coordonnées sont en **pixels de la vidéo source** (invariant 2).
 */

import type { Point } from "@/shared/api/contracts";

/**
 * Côté signé de `p` par rapport à la droite orientée `a`→`b` : -1, 0 ou +1.
 *
 * Produit vectoriel de `ab` et `ap`, **exactement la formule du backend** —
 * `(b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)`. Ne pas « simplifier »
 * en inversant l'ordre des termes : le signe est le contrat.
 *
 * `0` veut dire « pile sur la droite ». Le backend attend alors la frame suivante
 * plutôt que de trancher ; ici, cela signifie seulement qu'aucune flèche n'est
 * plus pertinente qu'une autre.
 *
 * Le côté est défini par rapport à la droite **infinie**, pas au segment tracé.
 */
export function sideOfLine(a: Point, b: Point, p: Point): -1 | 0 | 1 {
  const cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
  if (cross > 0) return 1;
  if (cross < 0) return -1;
  return 0;
}

/**
 * Le point est-il dans le polygone ? (lancer de rayon)
 *
 * Gère les polygones **concaves** : une zone tracée à la main l'est presque
 * toujours, et un test par boîte englobante dirait « dedans » pour le creux d'un U.
 *
 * Moins de trois sommets n'est pas une surface — un polygone en cours de tracé
 * ne doit pas être sélectionnable comme s'il était fermé.
 */
export function pointInPolygon(point: Point, polygon: readonly Point[]): boolean {
  if (polygon.length < 3) return false;

  let inside = false;
  let previous = polygon[polygon.length - 1];
  if (previous === undefined) return false;

  for (const current of polygon) {
    if (current.y > point.y !== previous.y > point.y) {
      const crossingX =
        ((previous.x - current.x) * (point.y - current.y)) / (previous.y - current.y) + current.x;
      if (point.x < crossingX) inside = !inside;
    }
    previous = current;
  }
  return inside;
}

/**
 * Distance du point au **segment** `[a,b]` — pas à la droite qui le porte.
 *
 * La distinction est ce qui rend la sélection correcte : avec la distance à la
 * droite infinie, cliquer très loin dans le prolongement d'une ligne la
 * sélectionnerait, ce qui est incompréhensible pour l'utilisateur.
 *
 * La projection est bornée à `[0,1]`, donc le point le plus proche est soit sur
 * le segment, soit l'une de ses extrémités.
 */
export function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;

  // Segment de longueur nulle : la distance au point unique. Ce cas arrive
  // réellement — une ligne qu'on vient de commencer à tracer.
  if (lengthSquared === 0) return Math.hypot(p.x - a.x, p.y - a.y);

  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lengthSquared));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

/** Distance euclidienne, en pixels source. */
export function distance(a: Point, b: Point): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/** Milieu d'un segment — où se pose l'étiquette d'une ligne. */
export function midpoint(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * Vecteur normal unitaire de `a`→`b`, orienté vers le côté **positif**.
 *
 * C'est ce qui fait pointer la flèche de sens du bon côté : le côté positif de la
 * convention est celui où `sideOfLine` rend `+1`, et un point déplacé le long de
 * ce normal depuis le milieu doit donc y tomber. Un test le vérifie, parce que
 * c'est précisément le genre de signe qu'on inverse sans le remarquer.
 *
 * Rend `{x: 0, y: 0}` pour un segment de longueur nulle : aucune direction n'a
 * de sens, et normaliser diviserait par zéro.
 */
export function positiveNormal(a: Point, b: Point): Point {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy);
  if (length === 0) return { x: 0, y: 0 };
  // Rotation de +90° dans un repère où y descend (celui du canvas et de la
  // vidéo) : (dx, dy) → (-dy, dx). Le signe est validé par un test.
  return { x: -dy / length, y: dx / length };
}

/**
 * Les huit flèches cardinales, dans l'ordre des secteurs de 45° à partir de l'est
 * et **dans le sens horaire de l'écran** (`y` croît vers le bas).
 */
const COMPASS_ARROWS = ["→", "↘", "↓", "↙", "←", "↖", "↑", "↗"] as const;

/**
 * La flèche unicode la plus proche d'un vecteur, arrondie au huitième de tour.
 *
 * C'est ce qui fait pointer une flèche de sens dans la **vraie** direction du
 * tracé plutôt qu'un « → »/« ↑ » figé : deux glyphes fixes suffisaient tant que
 * les lignes étaient horizontales ou verticales, mais une ligne tracée en
 * diagonale les rendait faux — pas inversés, juste à côté, ce qui se remarque
 * moins qu'une inversion et se corrige donc moins vite.
 *
 * Huit directions plutôt qu'un angle continu : au-delà, un glyphe unicode
 * n'existe plus, et un texte pivoté par CSS ne s'applique pas à un caractère
 * peint sur un `<canvas>`.
 *
 * `Math.round` plutôt que `Math.floor` : un vecteur à 40° doit tomber sur « ↘ »
 * (45°), pas rester sur « → » (0°) jusqu'à 45° pile.
 */
export function compassArrow(vector: Point): string {
  if (vector.x === 0 && vector.y === 0) return "•";
  const angle = Math.atan2(vector.y, vector.x);
  const normalised = angle < 0 ? angle + Math.PI * 2 : angle;
  const sector = Math.round(normalised / (Math.PI / 4)) % COMPASS_ARROWS.length;
  return COMPASS_ARROWS[sector] ?? "→";
}

/**
 * Libellés de sens **par défaut**, déduits de l'orientation du tracé.
 *
 * Ce sont des `placeholder`, pas des valeurs : le contrat garde `''` tant que
 * l'utilisateur n'a rien tapé, et cette fonction est appelée à l'affichage. C'est
 * ce qui permet aux libellés de suivre la ligne quand on la fait pivoter — écrire
 * un défaut dans le champ le figerait à l'orientation du moment.
 *
 * Le vocabulaire est celui de l'**image**, pas celui d'une boussole : « vers le
 * haut » est vérifiable à l'écran, « vers le nord » demanderait de connaître
 * l'orientation de la caméra, que rien ne nous dit. L'utilisateur qui veut du
 * cardinal l'écrit lui-même, et c'est précisément à quoi servent les champs.
 *
 * Le sens positif est celui de `positiveNormal`, dont le signe est verrouillé par un
 * test contre `sideOfLine` : une inversion ici ferait lire des sens faux sous des
 * totaux justes, le pire mode de défaillance parce qu'il est silencieux.
 */
export function defaultDirectionNames(a: Point, b: Point): { positive: string; negative: string } {
  const normal = positiveNormal(a, b);
  // Segment dégénéré : aucune orientation n'a de sens. On rend les libellés
  // neutres de la convention serveur plutôt qu'un axe choisi au hasard.
  if (normal.x === 0 && normal.y === 0) return { positive: "Sens A→B", negative: "Sens B→A" };

  // L'axe dominant du **normal**, donc du déplacement qui traverse la ligne : une
  // ligne horizontale se franchit verticalement, et inversement.
  if (Math.abs(normal.x) >= Math.abs(normal.y)) {
    return normal.x > 0
      ? { positive: "Vers la droite", negative: "Vers la gauche" }
      : { positive: "Vers la gauche", negative: "Vers la droite" };
  }
  // `y` croît **vers le bas** dans le repère du canvas et de la vidéo.
  return normal.y > 0
    ? { positive: "Vers le bas", negative: "Vers le haut" }
    : { positive: "Vers le haut", negative: "Vers le bas" };
}

/** Borne un point au rectangle de la vidéo source. */
export function clampToSource(p: Point, width: number, height: number): Point {
  return {
    x: Math.max(0, Math.min(width, p.x)),
    y: Math.max(0, Math.min(height, p.y)),
  };
}

/** Centre d'une boîte — le point que le comptage suit côté serveur. */
export function boxCentroid(box: {
  x: number;
  y: number;
  width: number;
  height: number;
}): Point {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}
