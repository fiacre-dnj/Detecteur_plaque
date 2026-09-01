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
 *
 * **Dans `shared/` avec `lineRules.ts` et `lineViolations.ts`.** Il vivait dans
 * `results-dashboard`, seul consommateur tant que le KPI était son seul lecteur ; le
 * centre de notifications en a désormais besoin pour son résumé, et une feature
 * n'importe jamais une autre feature. C'est le même déménagement, pour la même
 * raison, que celui des deux modules à côté desquels il arrive : un seul juge, sinon
 * la même infraction se compte différemment selon l'écran qui la montre.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";
import { DIRECTION_SIGNS } from "@/shared/lib/directions";
import type { LineRule } from "@/shared/lib/lineRules";
import type { ViolationKind } from "@/shared/lib/lineViolations";

/** Un compte par nature d'infraction — les trois du `ViolationKind`. */
export type ViolationsByKind = Readonly<Record<ViolationKind, number>>;

/** Zéro partout : le point de départ d'une accumulation, et le repli d'une lecture. */
export const NO_VIOLATIONS: ViolationsByKind = Object.freeze({
  "wrong-way": 0,
  "closed-line": 0,
  "reserved-lane": 0,
});

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
  /**
   * Le total par **nature**, pour le résumé du centre de notifications.
   *
   * `forbidden` ci-dessus est la somme de `wrong-way` et `closed-line` : les deux
   * portent sur le trajet, et le KPI ne les sépare pas. Le résumé, lui, les
   * distingue — « à contresens » suppose un sens autorisé en face, ce qu'une ligne
   * infranchissable n'a pas, et les deux appellent des gestes différents.
   */
  byKind: ViolationsByKind;
  /**
   * Le total par **classe COCO** puis par nature — « quels types enfreignent quoi ».
   *
   * La clé est le nom COCO (`car`, `truck`…), celle des `byClass` du serveur et de
   * `CrossingEvent.label` : c'est la classe **votée** sur la vie du véhicule
   * (invariant 4), donc la même population que la liste d'alertes filtrée par type.
   * Une classe sans aucune infraction n'y a pas d'entrée — jamais une rangée à zéro,
   * qui ferait lire « ce type a été surveillé et n'a rien fait » là où il n'a
   * simplement jamais franchi de ligne réglée.
   */
  byClass: Readonly<Record<string, ViolationsByKind>>;
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
  const byKind: Record<ViolationKind, number> = { ...NO_VIOLATIONS };
  const byClass: Record<string, Record<ViolationKind, number>> = {};

  /** Range un compte sous sa nature **et** sous sa classe, en un seul geste. */
  const record = (kind: ViolationKind, cocoName: string, count: number): void => {
    if (count === 0) return;
    byKind[kind] += count;
    (byClass[cocoName] ??= { ...NO_VIOLATIONS })[kind] += count;
  };

  for (const line of lines) {
    const rule = rules.get(line.id);
    if (rule === undefined || !rule.restricted) continue;
    declared = true;

    // Le même mot que `violationOf` pour la même ligne : « à contresens » n'a de
    // sens que s'il existe un sens autorisé en face. Les deux modules le décident
    // sur `rule.kind`, jamais sur le nombre de sens interdits comptés ici.
    const forbiddenKind: ViolationKind = rule.kind === "closed" ? "closed-line" : "wrong-way";

    let lineTotal = 0;
    for (const sign of DIRECTION_SIGNS) {
      const tally = stats.byLine[line.id]?.byDirection[sign];
      if (tally === undefined) continue;

      if (rule.forbiddenSigns.includes(sign)) {
        forbidden += tally.total;
        lineTotal += tally.total;
        // La ventilation par classe vient de `byClass` et non de `total` : sur un
        // sens interdit, **tout** passe en infraction, donc les deux sommes sont
        // égales — mais seul `byClass` sait de quels types il s'agit.
        for (const [cocoName, count] of Object.entries(tally.byClass)) {
          record(forbiddenKind, cocoName, count);
        }
        continue;
      }
      if (rule.allowedClasses === null) continue;
      for (const [cocoName, count] of Object.entries(tally.byClass)) {
        if (rule.allowedClasses.has(cocoName)) continue;
        reservedLane += count;
        lineTotal += count;
        record("reserved-lane", cocoName, count);
      }
    }
    byLine[line.id] = lineTotal;
  }

  return {
    forbidden,
    reservedLane,
    total: forbidden + reservedLane,
    declared,
    byLine,
    byKind,
    byClass,
  };
}
