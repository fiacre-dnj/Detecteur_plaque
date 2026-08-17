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

import { arrowRotationDeg, defaultDirectionNames, positiveNormal } from "./geometry";

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

/**
 * Angle, en degrés, d'une flèche qui pointe dans le sens du franchissement.
 *
 * **Le seul endroit qui décide de cet angle**, et c'est tout l'intérêt : la même
 * valeur sert au panneau de géométrie, à la chronologie des franchissements et aux
 * puces du registre. Trois écrans, une flèche — sinon le même passage pointerait à
 * trois angles différents selon l'endroit où on le regarde.
 *
 * Un franchissement traverse la ligne **perpendiculairement** au trait, vers le côté
 * d'arrivée : le sens positif suit `positiveNormal`, le négatif son opposé. L'angle
 * est donc celui du trait tourné d'un quart de tour — une ligne horizontale se
 * franchit verticalement, exactement ce que montre le canvas.
 *
 * `null` sur un segment de longueur nulle : aucune orientation n'existe, et
 * `arrowRotationDeg` y rendrait `0`, soit une flèche vers le haut affirmée sans
 * mesure. L'appelant n'affiche alors pas de flèche pivotée.
 *
 * La négation du sens négatif vit **ici et nulle part ailleurs**. Elle était écrite en
 * clair dans `GeometryPanel`, et `geometry.ts` documente précisément ce mode de
 * panne : un signe inversé fait pointer les flèches à l'envers sous des rôles et des
 * totaux par ailleurs justes, sans que rien ne plante.
 */
export function directionHeadingDeg(line: CountingLine, sign: DirectionSign): number | null {
  const normal = positiveNormal(line.a, line.b);
  if (normal.x === 0 && normal.y === 0) return null;
  return arrowRotationDeg(sign === "positive" ? normal : { x: -normal.x, y: -normal.y });
}

/**
 * Angle de la flèche d'un franchissement, à partir de son signe et de sa ligne.
 *
 * Même forme et même repli que `crossingDirectionName`, volontairement : `null` quand
 * la ligne est inconnue — un franchissement archivé dont la ligne a été retirée du
 * tracé. L'appelant montre alors la flèche brute de la convention serveur
 * (`directionArrow`), qui ne prétend décrire aucune géométrie, plutôt qu'une icône
 * non pivotée qui affirmerait « vers le haut ».
 */
export function crossingHeadingDeg(
  lines: readonly CountingLine[],
  lineId: string,
  direction: number,
): number | null {
  const line = lines.find((candidate) => candidate.id === lineId);
  return line === undefined ? null : directionHeadingDeg(line, signOf(direction));
}

/**
 * Flèche du sens : **quel** sens dans la convention du canvas, pas ce qu'il signifie.
 *
 * Un glyphe unicode ne pivote qu'à 45° près : il ne sert donc que de **repli**, quand
 * la géométrie ne permet aucun angle mesuré (`crossingHeadingDeg` rend `null`). Partout
 * où la ligne est connue, c'est une icône pivotée à l'angle réel du trait qui
 * s'affiche.
 */
export function directionArrow(direction: number): string {
  return direction > 0 ? "↑" : "↓";
}

/** Libellé court du rôle, ou `null` pour `neutral` — rien à afficher. */
export function roleLabel(role: DirectionRole): string | null {
  if (role === "entry") return "entrée";
  if (role === "exit") return "sortie";
  return null;
}
