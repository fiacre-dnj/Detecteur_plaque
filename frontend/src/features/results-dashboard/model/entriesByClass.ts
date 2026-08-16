/**
 * Les entrées au carrefour, ventilées par classe — la contrepartie par-type de
 * `flowBalance`.
 *
 * **Même filtre, même source, un seul calcul.** `isEntryRow` est importée de
 * `directions.ts` plutôt que réécrite ici : c'est ce qui garantit que la somme
 * de ce module, toutes classes confondues, égale exactement
 * `flowBalance(stats, lines).entries` — le dépôt a déjà payé le prix d'un
 * chiffre calculé deux fois qui finit par diverger (le « taux de
 * franchissement » à 200 %, voir `labels.ts`), et ce test-ci est écrit pour ne
 * pas repayer cette facture.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";

import { directionRows, isEntryRow } from "./directions";

/**
 * Entrées au carrefour, par classe COCO (`car`, `truck`, `person`…).
 *
 * Une classe absente du résultat n'a pas de clé — l'appelant retombe sur `0`
 * (`?? 0`), comme partout ailleurs dans ce tableau de bord.
 */
export function entriesByClass(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const row of directionRows(stats, lines)) {
    if (!isEntryRow(row)) continue;
    for (const [klass, count] of Object.entries(row.tally.byClass)) {
      totals[klass] = (totals[klass] ?? 0) + count;
    }
  }
  return totals;
}
