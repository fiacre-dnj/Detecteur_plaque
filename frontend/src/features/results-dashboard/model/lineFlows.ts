/**
 * Le bilan **d'une ligne** : sa fréquentation brute, ses entrées, ses sorties.
 *
 * Extrait de `highlights.ts`, où il vivait en fonction privée, parce que trois
 * écrans posent désormais la même question — les comparatifs entre lignes, la
 * rangée compacte de « Statistique » et les cartes par ligne de la colonne de
 * résultats. Deux copies d'une règle finissent par diverger, et ici ce serait un
 * passage qui change de colonne selon l'écran qui le montre : le dépôt documente
 * cette famille de bug plus que toute autre.
 *
 * Tout est **dérivé** de `directionRows`, jamais accumulé en parallèle
 * (invariant 3), et le seul prédicat qui décide ce qu'est une entrée reste
 * `isEntryRow` — jamais réécrit ici.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";

import { directionRows, isEntryRow } from "./directions";

/** Une ligne et son bilan, prêt à afficher. */
export interface LineFlow {
  lineId: string;
  lineName: string;
  color: string;
  /**
   * Tous les passages de la ligne, **sens neutres compris** — c'est exactement
   * `LineTally.total`, la fréquentation brute, indépendante des rôles déclarés.
   */
  total: number;
  /**
   * Passages sur les sens marqués « entrée », ou `null` si **aucun** sens de
   * cette ligne ne porte ce rôle.
   *
   * `null` et non `0`, et la distinction n'est pas cosmétique : un « 0 entrées »
   * se lit comme un comptage — « personne n'est entré » — alors que la vérité est
   * « personne n'a déclaré de sens d'entrée ici ». Même honnêteté que
   * `flowBalance.declared`.
   */
  entries: number | null;
  /** Pendant de `entries` pour les sens marqués « sortie ». */
  exits: number | null;
  /** `entries - exits`. Positif = la zone se remplit, négatif = elle se vide. */
  net: number;
  /** Part de cette ligne dans tous les passages, `null` s'il n'y en a aucun. */
  shareOfTotal: number | null;
}

/**
 * Le bilan de chaque ligne, dans l'ordre du tracé.
 *
 * Une ligne sans aucun passage est **présente** avec ses compteurs à zéro : une
 * ligne absente de la liste se lirait comme « pas d'information », alors qu'une
 * ligne que personne ne franchit est une information — la voie est déserte, ou le
 * trait est mal posé.
 */
export function lineFlows(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineFlow[] {
  const byLine = new Map<string, LineFlow>();
  for (const line of lines) {
    byLine.set(line.id, {
      lineId: line.id,
      lineName: line.name,
      color: line.color,
      total: 0,
      entries: null,
      exits: null,
      net: 0,
      shareOfTotal: null,
    });
  }

  for (const row of directionRows(stats, lines)) {
    const flow = byLine.get(row.lineId);
    if (flow === undefined) continue;
    flow.total += row.tally.total;
    if (isEntryRow(row)) {
      flow.entries = (flow.entries ?? 0) + row.tally.total;
      flow.net += row.tally.total;
    } else if (row.role === "exit") {
      flow.exits = (flow.exits ?? 0) + row.tally.total;
      flow.net -= row.tally.total;
    }
  }

  for (const flow of byLine.values()) {
    flow.shareOfTotal = stats.crossings === 0 ? null : flow.total / stats.crossings;
  }

  return [...byLine.values()];
}
