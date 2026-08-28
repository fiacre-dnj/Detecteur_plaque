/**
 * Un franchissement confronté aux règles de sa ligne.
 *
 * **Dans `shared/` avec `lineRules.ts`, et pour la même raison** : les alertes le
 * signalent, le tableau de bord le compte, le registre l'affiche en colonne. Un
 * seul prédicat, sinon une infraction change d'écran en écran.
 *
 * **Une infraction ne retire aucun passage.** Le franchissement reste compté dans
 * `crossings` et dans `byLine` — l'invariant 3 en dépend — et ce module ne fait que
 * le *qualifier*. C'est la même doctrine que les rôles de sens : le serveur compte,
 * l'interface interprète, et corriger l'interprétation ne demande jamais de
 * relancer l'analyse.
 *
 * **Une seule infraction par franchissement, et l'ordre de priorité compte.** Un
 * bus qui remonte une voie réservée à contresens enfreint deux règles ; le compter
 * deux fois ferait diverger la liste des alertes du KPI, qui somme des passages
 * (`violationTally.ts` applique la **même** priorité). Le sens interdit passe
 * devant : il porte sur le trajet, la voie réservée sur le véhicule, et c'est le
 * trajet qui est le fait le plus grave.
 */

import type { CrossingEvent } from "@/shared/api/contracts";

import { signOf } from "./directions";
import type { LineRule } from "./lineRules";

/**
 * Ce qui est enfreint.
 *
 * `closed-line` est distingué de `wrong-way` parce que les deux appellent des mots
 * différents à l'écran : « à contresens » suppose un sens autorisé en face, ce
 * qu'une ligne infranchissable n'a pas.
 */
export type ViolationKind = "wrong-way" | "closed-line" | "reserved-lane";

/** Un franchissement et la règle qu'il enfreint. */
export interface Violation {
  kind: ViolationKind;
  crossing: CrossingEvent;
  rule: LineRule;
}

/**
 * La règle qu'enfreint ce franchissement, ou `null`.
 *
 * `null` dans les trois cas où il n'y a rien à dire, et aucun n'est une anomalie :
 * la ligne a été retirée du tracé, elle ne déclare aucune règle, ou le
 * franchissement la respecte.
 */
export function violationOf(
  crossing: CrossingEvent,
  rules: ReadonlyMap<string, LineRule>,
): Violation | null {
  const rule = rules.get(crossing.lineId);
  if (rule === undefined || !rule.restricted) return null;

  if (rule.forbiddenSigns.includes(signOf(crossing.direction))) {
    return { kind: rule.kind === "closed" ? "closed-line" : "wrong-way", crossing, rule };
  }

  // La classe est celle **votée** sur la vie du véhicule (invariant 4), portée par
  // `label` : c'est la même clé que les `byClass` du serveur, donc le KPI et cette
  // liste comptent exactement la même population.
  if (rule.allowedClasses !== null && !rule.allowedClasses.has(crossing.label)) {
    return { kind: "reserved-lane", crossing, rule };
  }

  return null;
}

/**
 * Toutes les infractions d'un journal de franchissements, dans son ordre.
 *
 * L'ordre d'entrée est conservé — c'est l'appelant qui décide s'il lit du plus
 * récent au plus ancien. Depuis ADR 0038, l'ordre d'émission d'un franchissement
 * n'est plus celui de sa date : reclasser ici masquerait cette propriété à celui
 * qui trie ensuite.
 */
export function violations(
  crossings: readonly CrossingEvent[],
  rules: ReadonlyMap<string, LineRule>,
): Violation[] {
  const found: Violation[] = [];
  for (const crossing of crossings) {
    const violation = violationOf(crossing, rules);
    if (violation !== null) found.push(violation);
  }
  return found;
}

/** Au moins une ligne du tracé déclare-t-elle une règle ? */
export function hasAnyRule(rules: ReadonlyMap<string, LineRule>): boolean {
  for (const rule of rules.values()) {
    if (rule.restricted) return true;
  }
  return false;
}
