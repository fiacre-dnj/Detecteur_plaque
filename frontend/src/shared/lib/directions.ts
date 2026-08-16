/**
 * Le vocabulaire des sens de ligne : nommer un signe, lire un rôle.
 *
 * **Dans `shared/` et non dans une feature**, parce que quatre features affichent un
 * sens — le tableau de résultats, la chronologie, le journal d'analyse et le registre.
 * Une feature n'importe jamais une autre feature ; sans ce module, chacune
 * réinventerait son libellé et l'écran dirait « A→B » ici, « ↑ » là et « Vers le
 * nord » ailleurs pour le même franchissement.
 *
 * Ce que ce module **ne fait pas** : agréger. Les totaux par sens, le bilan
 * entrées/sorties et la matrice origine-destination vivent dans
 * `features/results-dashboard/model/directions.ts`, qui est leur seul consommateur.
 */

import type {
  CountingLine,
  DirectionRole,
  DirectionSign,
  DirectionTally,
} from "@/shared/api/contracts";

import { defaultDirectionNames } from "./geometry";

/** Les deux sens, dans l'ordre d'affichage : le positif d'abord, comme la flèche. */
export const DIRECTION_SIGNS: readonly DirectionSign[] = ["positive", "negative"];

/**
 * Un sens qui n'a rien compté.
 *
 * Gelé et partagé : ces objets ne sont jamais mutés par les lecteurs, et en allouer
 * un par sens et par rafraîchissement serait du gaspillage sur un tracé à six lignes.
 */
export const EMPTY_DIRECTION_TALLY: DirectionTally = Object.freeze({
  total: 0,
  byClass: Object.freeze({}) as Record<string, number>,
  firstMs: null,
  lastMs: null,
});

/** `+1` / `-1` → le sens, dans le vocabulaire du contrat. */
export function signOf(direction: number): DirectionSign {
  return direction > 0 ? "positive" : "negative";
}

/**
 * Le libellé **effectif** d'un sens : « Entrée », « Sortie », ou un repli pour les
 * lignes tracées avant que le rôle soit obligatoire.
 *
 * À appeler partout où un sens s'affiche. Depuis que le panneau de géométrie
 * n'offre plus qu'un choix entrée/sortie, le rôle **est** le libellé — il n'y a
 * plus de nom libre à préférer. Le repli sur le nom saisi puis sur le défaut
 * géométrique ne joue que pour une ligne dont le rôle est resté `neutral`, ce que
 * l'éditeur ne produit plus mais qu'un preset ou un `configJson` archivé avant ce
 * changement peut encore porter.
 */
export function directionName(line: CountingLine, sign: DirectionSign): string {
  const role = directionRole(line, sign);
  if (role === "entry") return "Entrée";
  if (role === "exit") return "Sortie";
  const given = sign === "positive" ? line.positiveName : line.negativeName;
  if (given !== undefined && given.trim() !== "") return given;
  const defaults = defaultDirectionNames(line.a, line.b);
  return sign === "positive" ? defaults.positive : defaults.negative;
}

/** Le rôle déclaré d'un sens. `neutral` par défaut, y compris sur une ligne ancienne. */
export function directionRole(line: CountingLine, sign: DirectionSign): DirectionRole {
  return (sign === "positive" ? line.positiveRole : line.negativeRole) ?? "neutral";
}

/**
 * Libellé du sens d'un franchissement, à partir de son signe et de sa ligne.
 *
 * Rend `null` quand la ligne est inconnue — un franchissement archivé dont la ligne a
 * été retirée du tracé. L'appelant affiche alors la flèche brute plutôt qu'inventer un
 * nom : une absence se dit.
 */
export function crossingDirectionName(
  lines: readonly CountingLine[],
  lineId: string,
  direction: number,
): string | null {
  const line = lines.find((candidate) => candidate.id === lineId);
  return line === undefined ? null : directionName(line, signOf(direction));
}

/** Nom d'une ligne, ou son identifiant en repli — le même repli partout. */
export function lineName(lines: readonly CountingLine[], lineId: string): string {
  return lines.find((candidate) => candidate.id === lineId)?.name ?? lineId;
}

/** Flèche du sens : **quel** sens dans la convention du canvas, pas ce qu'il signifie. */
export function directionArrow(direction: number): string {
  return direction > 0 ? "↑" : "↓";
}

/** Libellé court du rôle, ou `null` pour `neutral` — rien à afficher. */
export function roleLabel(role: DirectionRole): string | null {
  if (role === "entry") return "entrée";
  if (role === "exit") return "sortie";
  return null;
}
