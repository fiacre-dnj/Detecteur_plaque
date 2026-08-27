/**
 * Combien de passages enfreignent une règle — **dérivé de `stats`, jamais compté**.
 *
 * C'est la moitié « compteur » des alertes, et elle est séparée de la moitié
 * « journal » pour une raison qui a déjà coûté un bug dans ce dépôt : le journal des
 * alertes est **borné** à 200 entrées, ces totaux ne le sont pas. Afficher
 * `alerts.length` comme un total le ferait plafonner en silence sous un tableau de
 * bord qui, lui, continue de monter — exactement ce que l'ancienne chronologie
 * faisait avant qu'on annonce sa borne (invariant 3).
 *
 * Tout sort de `stats.byLine[*].byDirection[*]`, que le serveur publie déjà :
 * `total` par sens pour les sens interdits, `byClass` par sens pour les voies
 * réservées. Rien n'est accumulé en parallèle.
 *
 * **La même priorité que `violationOf`, et c'est ce qui rend les deux comparables.**
 * Un bus qui remonte une voie réservée à contresens enfreint deux règles ; il compte
 * **une** fois, du côté du sens interdit. Compter les deux ferait diverger ce total
 * de la liste des alertes, sur un écran où les deux se lisent ensemble.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";
import { DIRECTION_SIGNS } from "@/shared/lib/directions";
import type { LineRule } from "@/shared/lib/lineRules";

/** Le bilan des infractions, prêt à afficher. */
export interface ViolationCounts {
  /** Passages sur un sens marqué « Interdit ». */
  forbidden: number;
  /** Passages d'une classe non autorisée, sur un sens qui, lui, était permis. */
  reservedLane: number;
  /** `forbidden + reservedLane`. Des passages, jamais des véhicules. */
  total: number;
  /**
   * Une règle est-elle déclarée quelque part ?
   *
   * Sans elle, `total` vaut `0` et un zéro se lit « aucune infraction » alors que la
   * vérité est « personne n'a posé de règle ». Même honnêteté que
   * `flowBalance.declared` et que le `null` de `LineFlow.entries` : les écrans
   * n'affichent le KPI que si cette valeur est vraie.
   */
  declared: boolean;
  /** Le total par ligne, pour la carte et la rangée de cette ligne-là. */
  byLine: Readonly<Record<string, number>>;
}

/** Le bilan des infractions du tracé courant. */
export function violationCounts(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
  rules: ReadonlyMap<string, LineRule>,
): ViolationCounts {
  let forbidden = 0;
  let reservedLane = 0;
  let declared = false;
  const byLine: Record<string, number> = {};

  for (const line of lines) {
    const rule = rules.get(line.id);
    if (rule === undefined || !rule.restricted) continue;
    declared = true;

    let lineTotal = 0;
    for (const sign of DIRECTION_SIGNS) {
      const tally = stats.byLine[line.id]?.byDirection[sign];
      if (tally === undefined) continue;

      if (rule.forbiddenSigns.includes(sign)) {
        forbidden += tally.total;
        lineTotal += tally.total;
        continue;
      }
      if (rule.allowedClasses === null) continue;
      for (const [cocoName, count] of Object.entries(tally.byClass)) {
        if (rule.allowedClasses.has(cocoName)) continue;
        reservedLane += count;
        lineTotal += count;
      }
    }
    byLine[line.id] = lineTotal;
  }

  return { forbidden, reservedLane, total: forbidden + reservedLane, declared, byLine };
}
