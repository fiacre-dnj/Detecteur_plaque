/**
 * Ce qu'une ligne **interdit**, prêt à confronter à un franchissement.
 *
 * Deux règles cohabitent sur une même ligne, et elles sont orthogonales :
 *
 * - un **sens interdit** — la ligne est à sens unique, ou infranchissable ;
 * - une **voie réservée** — seules certaines classes ont le droit d'y passer.
 *
 * Une voie de bus à sens unique porte les deux. Les fondre en un seul « type de
 * ligne » rendrait ce cas inexprimable, d'où deux champs distincts ici comme dans
 * le panneau de géométrie.
 *
 * **Dans `shared/` et non dans une feature** : trois features posent la question —
 * les alertes la signalent, le tableau de bord la compte, le registre l'affiche en
 * colonne. Une feature n'importe jamais une autre feature, et trois copies de « ce
 * franchissement est-il en infraction » finiraient par diverger, donc par ranger le
 * même passage différemment selon l'écran qui le montre. C'est exactement la raison
 * qui a fait naître `shared/lib/directions.ts`.
 *
 * **La traduction des identifiants COCO en noms se fait ici, une seule fois.**
 * `allowedClassIds` est stocké en identifiants — la monnaie du catalogue et de
 * `AnalysisRequest.classIds` — alors que `CrossingEvent.label` porte un *nom* COCO,
 * qui est la clé des `byClass`. Confondre les deux ne lèverait rien : aucune
 * correspondance ne serait jamais trouvée, donc **tout** franchissement passerait
 * pour une infraction.
 */

import type {
  CountingLine,
  DetectableClass,
  DirectionSign,
} from "@/shared/api/contracts";
import { DIRECTION_SIGNS, directionRole, isForbiddenRole, lineKind, type LineKind } from "./directions";

/** Les règles d'une ligne, telles que le tracé courant les déclare. */
export interface LineRule {
  lineId: string;
  lineName: string;
  color: string;
  kind: LineKind;
  /** Les sens dont le rôle est « Interdit ». Vide sur une ligne ordinaire. */
  forbiddenSigns: readonly DirectionSign[];
  /**
   * Noms COCO autorisés à franchir, ou `null` — aucune restriction.
   *
   * `null` et jamais un ensemble vide : un ensemble vide dirait « aucune classe
   * n'a le droit de passer », donc tout franchissement en infraction. C'est le
   * même repli, pour la même raison, que dans le reducer et le dépôt de presets.
   */
  allowedClasses: ReadonlySet<string> | null;
  /** Cette ligne déclare-t-elle la moindre règle ? */
  restricted: boolean;
}

/**
 * Les règles de chaque ligne du tracé **courant**, indexées par identifiant.
 *
 * Lues sur la géométrie et non sur le résultat archivé : le serveur ne connaît pas
 * ces règles et ne les lit jamais. C'est ce qui rend instantané le fait de déclarer
 * un sens interdit après coup, sur une analyse déjà terminée — exactement comme
 * basculer un sens entrée ↔ sortie.
 *
 * Une ligne **absente** de cette table est une ligne retirée du tracé depuis
 * l'analyse : ses franchissements ne produisent alors aucune infraction, jamais une
 * infraction supposée. Inventer une règle disparue serait pire que de n'en signaler
 * aucune.
 */
export function lineRules(
  lines: readonly CountingLine[],
  catalogue: readonly DetectableClass[],
): ReadonlyMap<string, LineRule> {
  const nameById = new Map(catalogue.map((entry) => [entry.id, entry.cocoName]));
  const rules = new Map<string, LineRule>();

  for (const line of lines) {
    const forbiddenSigns = DIRECTION_SIGNS.filter((sign) =>
      isForbiddenRole(directionRole(line, sign)),
    );
    const allowedClasses = resolveAllowedClasses(line.allowedClassIds ?? null, nameById);
    rules.set(line.id, {
      lineId: line.id,
      lineName: line.name,
      color: line.color,
      kind: lineKind(line),
      forbiddenSigns,
      allowedClasses,
      restricted: forbiddenSigns.length > 0 || allowedClasses !== null,
    });
  }

  return rules;
}

/**
 * Les noms COCO d'une liste d'identifiants, ou `null`.
 *
 * **Un identifiant que le catalogue ne connaît pas est ignoré, jamais deviné.** Le
 * catalogue peut avoir changé entre l'enregistrement d'un preset et sa relecture ;
 * fabriquer un nom à partir d'un numéro produirait une classe qui n'existe nulle
 * part, donc une voie réservée que personne ne peut emprunter.
 *
 * Si **aucun** identifiant n'est reconnu, la restriction disparaît (`null`) au lieu
 * de devenir un ensemble vide : mieux vaut ne rien signaler que tout signaler.
 */
function resolveAllowedClasses(
  ids: readonly number[] | null,
  nameById: ReadonlyMap<number, string>,
): ReadonlySet<string> | null {
  if (ids === null || ids.length === 0) return null;
  const names = new Set<string>();
  for (const id of ids) {
    const name = nameById.get(id);
    if (name !== undefined) names.add(name);
  }
  return names.size === 0 ? null : names;
}
