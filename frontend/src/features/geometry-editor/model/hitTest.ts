/**
 * Test de sélection : que vise le curseur ?
 *
 * Fonctions pures, donc testables sans canvas — et elles en ont besoin, parce que
 * les règles de priorité sont exactement le genre de chose qui « marche presque »
 * et rend l'édition frustrante sans qu'on sache dire pourquoi.
 *
 * **Le rayon de sélection est exprimé en pixels écran, puis converti en pixels
 * source.** C'est la subtilité qui compte : si le rayon était en pixels source, la
 * précision de clic dépendrait de la taille d'affichage — confortable sur une
 * vidéo 640×360 affichée en grand, impossible sur une 4K affichée en petit, alors
 * que le geste de l'utilisateur est le même dans les deux cas.
 */

import type { CountingLine, Point, Zone } from "@/shared/api/contracts";
import { distance, distanceToSegment, pointInPolygon } from "@/shared/lib/geometry";

/** Rayon de préhension d'une poignée, en pixels **écran**. */
export const HANDLE_RADIUS_SCREEN = 11;

/** Tolérance pour saisir le corps d'une ligne, en pixels **écran**. */
export const LINE_RADIUS_SCREEN = 8;

/** Ce que le curseur a attrapé. */
export type Hit =
  | { kind: "lineHandle"; id: string; end: "a" | "b" }
  | { kind: "lineBody"; id: string }
  | { kind: "zoneVertex"; id: string; index: number }
  | { kind: "zoneBody"; id: string }
  | { kind: "none" };

export const NO_HIT: Hit = { kind: "none" };

/**
 * Trouve ce que désigne `point`, en pixels source.
 *
 * `scale` est le rapport pixels source / pixel écran : il convertit les rayons de
 * préhension, exprimés à l'écran, dans le repère où se font les calculs.
 *
 * **Ordre de priorité**, et chaque niveau a sa raison :
 *
 * 1. les **poignées** avant les corps — elles sont dessinées par-dessus, et une
 *    poignée qu'on ne peut pas saisir parce que le corps la capte est un bug
 *    visible immédiatement ;
 * 2. les **lignes** avant les zones — les lignes sont dessinées au-dessus des
 *    zones, donc c'est ce que l'utilisateur voit et croit viser ;
 * 3. à égalité de type, **la plus récemment ajoutée gagne** — elle est dessinée
 *    en dernier, donc au-dessus. On parcourt les listes à l'envers.
 */
export function hitTest(
  point: Point,
  lines: readonly CountingLine[],
  zones: readonly Zone[],
  scale: number,
): Hit {
  const handleRadius = HANDLE_RADIUS_SCREEN * scale;
  const lineRadius = LINE_RADIUS_SCREEN * scale;

  // 1a. Poignées de ligne — la cible la plus fine, donc la plus prioritaire.
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index];
    if (line === undefined) continue;
    if (distance(point, line.a) <= handleRadius) {
      return { kind: "lineHandle", id: line.id, end: "a" };
    }
    if (distance(point, line.b) <= handleRadius) {
      return { kind: "lineHandle", id: line.id, end: "b" };
    }
  }

  // 1b. Sommets de zone.
  for (let index = zones.length - 1; index >= 0; index -= 1) {
    const zone = zones[index];
    if (zone === undefined) continue;
    for (let vertex = 0; vertex < zone.points.length; vertex += 1) {
      const candidate = zone.points[vertex];
      if (candidate === undefined) continue;
      if (distance(point, candidate) <= handleRadius) {
        return { kind: "zoneVertex", id: zone.id, index: vertex };
      }
    }
  }

  // 2. Corps des lignes, qui gagnent sur les zones parce qu'ils sont dessus.
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index];
    if (line === undefined) continue;
    if (distanceToSegment(point, line.a, line.b) <= lineRadius) {
      return { kind: "lineBody", id: line.id };
    }
  }

  // 3. Intérieur des zones, en dernier.
  for (let index = zones.length - 1; index >= 0; index -= 1) {
    const zone = zones[index];
    if (zone === undefined) continue;
    if (pointInPolygon(point, zone.points)) {
      return { kind: "zoneBody", id: zone.id };
    }
  }

  return NO_HIT;
}

/** La sélection correspondant à un `Hit`, pour le panneau latéral. */
export function selectionOf(hit: Hit): { kind: "line" | "zone"; id: string } | null {
  switch (hit.kind) {
    case "lineHandle":
    case "lineBody":
      return { kind: "line", id: hit.id };
    case "zoneVertex":
    case "zoneBody":
      return { kind: "zone", id: hit.id };
    case "none":
      return null;
  }
}

/**
 * Le clic ferme-t-il le polygone en cours ?
 *
 * Deux gestes ferment une zone, et **les deux doivent exister** : le double-clic
 * et le clic sur le premier sommet. Les gens attendent l'un ou l'autre selon les
 * outils qu'ils ont pratiqués, et n'en proposer qu'un laisse la moitié des
 * utilisateurs bloqués sur un polygone qu'ils n'arrivent pas à terminer.
 *
 * Trois sommets minimum : en dessous, il n'y a pas de surface à fermer.
 */
export function closesPolygon(point: Point, draft: readonly Point[], scale: number): boolean {
  if (draft.length < 3) return false;
  const first = draft[0];
  if (first === undefined) return false;
  return distance(point, first) <= HANDLE_RADIUS_SCREEN * scale;
}

/**
 * Le clic retombe-t-il sur le **dernier** sommet posé ?
 *
 * Ce cas doit être ignoré, et c'est subtil : un double-clic émet deux
 * `pointerdown` avant le `dblclick`. Le second `pointerdown` ajouterait un sommet
 * au même endroit que le premier, et la zone fermée porterait une **arête de
 * longueur nulle** — invisible à l'écran, mais qui rend le polygone dégénéré.
 */
export function repeatsLastVertex(point: Point, draft: readonly Point[], scale: number): boolean {
  const last = draft[draft.length - 1];
  if (last === undefined) return false;
  return distance(point, last) <= HANDLE_RADIUS_SCREEN * scale;
}
