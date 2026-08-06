/**
 * Tri du tableau de benchmark, et barres relatives.
 *
 * **La règle qui compte : les lignes en échec vont toujours en bas.** Leur
 * `medianMs` vaut 0, donc un tri croissant les placerait en tête — et le modèle
 * affiché comme « le plus rapide » serait systématiquement celui qui n'a pas pu être
 * mesuré. C'est le même piège que côté serveur, où `fastest()` les exclut déjà.
 */

import type { BenchmarkEntry } from "@/shared/api/contracts";

/** Colonnes triables. */
export type SortColumn = "label" | "tier" | "loadMs" | "medianMs" | "p95Ms" | "detections";

export type SortDirection = "asc" | "desc";

export interface SortState {
  column: SortColumn;
  direction: SortDirection;
}

/** Tri par défaut : du plus rapide au plus lent, la question qu'on se pose. */
export const DEFAULT_SORT: SortState = { column: "medianMs", direction: "asc" };

/**
 * Trie les lignes, **échecs en dernier quel que soit le sens**.
 *
 * Le tri est stable : à valeur égale, l'ordre du catalogue est conservé, ce qui
 * évite que deux modèles de même médiane permutent d'un rafraîchissement à l'autre.
 */
export function sortEntries(
  entries: readonly BenchmarkEntry[],
  sort: SortState,
): BenchmarkEntry[] {
  const factor = sort.direction === "asc" ? 1 : -1;

  return [...entries].sort((left, right) => {
    // Les échecs sortent du tri : ils n'ont pas de mesure à comparer.
    const leftFailed = left.error !== null;
    const rightFailed = right.error !== null;
    if (leftFailed !== rightFailed) return leftFailed ? 1 : -1;

    return compare(left, right, sort.column) * factor;
  });
}

function compare(left: BenchmarkEntry, right: BenchmarkEntry, column: SortColumn): number {
  switch (column) {
    case "label":
      // `localeCompare` en français : sans lui, « É » se classe après « Z ».
      return left.label.localeCompare(right.label, "fr");
    case "tier":
      return TIER_RANK.indexOf(left.tier) - TIER_RANK.indexOf(right.tier);
    default:
      return left[column] - right[column];
  }
}

/** Ordre des paliers, du plus léger au plus lourd. */
const TIER_RANK: readonly string[] = ["nano", "small", "medium", "large", "xlarge"];

/**
 * Sens du tri au clic sur une colonne.
 *
 * Cliquer une **autre** colonne repart du sens le plus utile pour elle : croissant
 * pour une durée (le plus rapide d'abord), alphabétique pour un nom. Repartir
 * toujours en croissant obligerait à deux clics pour la question la plus fréquente.
 */
export function nextSort(current: SortState, column: SortColumn): SortState {
  if (current.column === column) {
    return { column, direction: current.direction === "asc" ? "desc" : "asc" };
  }
  return { column, direction: "asc" };
}

/**
 * Largeur relative d'une barre, en pourcentage du maximum.
 *
 * Sur le **maximum de la colonne** et non sur une échelle absolue : c'est ce qui
 * rend la comparaison lisible d'un coup d'œil, quel que soit le matériel. Sur un GPU
 * toutes les barres seraient minuscules avec une échelle fixe.
 *
 * Rend 0 pour une ligne en échec — pas une barre pleine, qui suggérerait la mesure
 * la plus lente alors qu'il n'y a pas de mesure du tout.
 */
export function relativeWidth(value: number, max: number): number {
  if (max <= 0 || value <= 0) return 0;
  return Math.round((value / max) * 100);
}

/** Maximum d'une colonne, échecs exclus. */
export function maxOf(entries: readonly BenchmarkEntry[], column: "medianMs" | "loadMs"): number {
  const values = entries.filter((entry) => entry.error === null).map((entry) => entry[column]);
  return values.length === 0 ? 0 : Math.max(...values);
}

/** Formate une durée en millisecondes pour le tableau. */
export function formatMs(ms: number): string {
  if (ms <= 0) return "—";
  if (ms < 1_000) return `${ms.toFixed(1)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}
