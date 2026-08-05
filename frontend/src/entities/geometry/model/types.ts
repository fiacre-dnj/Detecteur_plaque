/**
 * L'état d'édition de la géométrie, et sa **signature**.
 *
 * `CountingLine` et `Zone` viennent des contrats : ce sont les mêmes objets que
 * ceux envoyés au serveur, en **pixels de la vidéo source** (invariant 2). Cette
 * entité n'ajoute que ce qui est propre à l'édition — quoi est sélectionné, quoi
 * est en cours de tracé — et la signature qui détecte un résultat périmé.
 */

import type { CountingLine, Point, Zone } from "@/shared/api/contracts";

/** Ce que l'utilisateur a sélectionné dans le canvas ou le panneau. */
export type Selection =
  | { kind: "line"; id: string }
  | { kind: "zone"; id: string }
  | { kind: "none" };

export const NO_SELECTION: Selection = { kind: "none" };

/** L'état complet de la géométrie éditée. */
export interface GeometryState {
  lines: CountingLine[];
  zones: Zone[];
  selection: Selection;
  /**
   * Mode « tracer une zone » actif.
   *
   * Le brouillon de polygone ne vit **pas** ici : il vit dans un `ref` côté
   * canvas. Un double-clic livre deux `pointerdown` **et** le `dblclick` dans un
   * seul rendu React, donc lire le brouillon depuis un state lirait une liste
   * périmée et perdrait le dernier sommet (piège 42 de `prompt/13`). Ce booléen,
   * lui, change assez rarement pour être un state sans conséquence.
   */
  drawingZone: boolean;
}

export const EMPTY_GEOMETRY: GeometryState = {
  lines: [],
  zones: [],
  selection: NO_SELECTION,
  drawingZone: false,
};

/** Une géométrie a-t-elle de quoi produire un compteur ? */
export function hasGeometry(state: GeometryState): boolean {
  return state.lines.length > 0 || state.zones.length > 0;
}

/**
 * Signature d'une géométrie — ce qui détecte un **résultat obsolète**.
 *
 * Le problème qu'elle résout : l'utilisateur lance une analyse, obtient des
 * chiffres, puis déplace une ligne. Les chiffres à l'écran ne correspondent plus
 * à la géométrie affichée, et **rien ne le signale** — c'est le genre d'écart
 * qu'on ne remarque qu'après avoir tiré une conclusion fausse. La signature est
 * relevée au lancement, comparée à celle du moment, et un bandeau ambre apparaît
 * dès qu'elles diffèrent.
 *
 * Ce qu'elle inclut, et pourquoi exactement ceci :
 * - par ligne : `id`, `ax,ay,bx,by` et `zoneId` — la position **et** la portée
 *   changent ce qui est compté ;
 * - par zone : `id` et tous les sommets.
 *
 * Ce qu'elle exclut **volontairement** : le nom et la couleur. Renommer « Voie
 * nord » en « Nord » ne change aucun chiffre ; faire clignoter un avertissement
 * pour un renommage apprendrait à l'utilisateur à ignorer l'avertissement.
 *
 * Les coordonnées sont arrondies à l'entier : un glisser au pixel près produit
 * des flottants dont les dernières décimales n'ont aucune conséquence sur le
 * comptage, et les comparer déclencherait le bandeau pour un déplacement
 * invisible.
 */
export function geometrySignature(lines: readonly CountingLine[], zones: readonly Zone[]): string {
  const linePart = lines
    .map((line) =>
      [
        line.id,
        Math.round(line.a.x),
        Math.round(line.a.y),
        Math.round(line.b.x),
        Math.round(line.b.y),
        line.zoneId ?? "*",
      ].join(","),
    )
    .join(";");

  const zonePart = zones
    .map((zone) => `${zone.id}:${zone.points.map(roundPoint).join(",")}`)
    .join(";");

  return `L[${linePart}]Z[${zonePart}]`;
}

function roundPoint(point: Point): string {
  return `${Math.round(point.x)}|${Math.round(point.y)}`;
}

/**
 * Met une géométrie à l'échelle d'une autre résolution.
 *
 * Sert au chargement d'un preset enregistré sur une vidéo de dimensions
 * différentes. L'interface **le dit** avant de le faire : une mise à l'échelle
 * silencieuse déplacerait les lignes de l'utilisateur sans qu'il comprenne
 * pourquoi.
 *
 * Le facteur est appliqué séparément en x et en y : une vidéo 4:3 chargée sur un
 * preset 16:9 doit conserver ses proportions relatives à l'image, pas une
 * homothétie qui sortirait du cadre.
 */
export function scaleGeometry(
  lines: readonly CountingLine[],
  zones: readonly Zone[],
  scaleX: number,
  scaleY: number,
): { lines: CountingLine[]; zones: Zone[] } {
  const scalePoint = (point: Point): Point => ({ x: point.x * scaleX, y: point.y * scaleY });

  return {
    lines: lines.map((line) => ({ ...line, a: scalePoint(line.a), b: scalePoint(line.b) })),
    zones: zones.map((zone) => ({ ...zone, points: zone.points.map(scalePoint) })),
  };
}
