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
  const named = ROLE_NAMES[role];
  if (named !== null) return named;
  const given = sign === "positive" ? line.positiveName : line.negativeName;
  if (given !== undefined && given.trim() !== "") return given;
  const defaults = defaultDirectionNames(line.a, line.b);
  return sign === "positive" ? defaults.positive : defaults.negative;
}

/**
 * Le libellé de chaque rôle, ou `null` quand il n'y en a pas à afficher.
 *
 * Une table et non une cascade de `if` : c'est ce qui fait échouer la compilation
 * le jour où un rôle s'ajoute au contrat sans que ce module le nomme. Un rôle
 * silencieusement retombé sur le nom géométrique — « Vers le haut » là où on
 * attendait « Interdit » — ne planterait jamais, et se lirait comme un bug de
 * tracé.
 */
const ROLE_NAMES: Readonly<Record<DirectionRole, string | null>> = {
  entry: "Entrée",
  exit: "Sortie",
  forbidden: "Interdit",
  // « Passage » et non « Neutre » : le mot doit décrire ce que fait le véhicule,
  // pas la catégorie interne du rôle. Sur une route qui n'est pas un carrefour,
  // « il passe » est exactement ce que la ligne mesure.
  transit: "Passage",
  neutral: null,
};

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
  const named = ROLE_NAMES[role];
  return named === null ? null : named.toLocaleLowerCase("fr");
}

/**
 * Un sens interdit — **le seul prédicat qui en décide**.
 *
 * Exporté plutôt que laissé en comparaison inline, pour la même raison
 * qu'`isEntryRow` du tableau de bord : quatre écrans posent la question, et quatre
 * comparaisons finiraient par diverger le jour où un second rôle interdit
 * apparaîtrait. Une infraction changerait alors d'écran en écran.
 */
export function isForbiddenRole(role: DirectionRole): boolean {
  return role === "forbidden";
}

/* ═══════════════════════════════════════════════════════════════════════════
   Le type d'une ligne — **dérivé** de sa paire de rôles, jamais stocké.
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Ce qu'une ligne déclare, lu depuis ses deux rôles.
 *
 * **Aucun champ `lineKind` dans le contrat, et c'est la décision principale de ce
 * bloc.** Un type stocké *à côté* des rôles serait une seconde source pour la même
 * vérité : changer un rôle sans toucher au type — ou l'inverse — donnerait une
 * ligne qui s'affiche « sens unique » tout en comptant deux sens, sans que rien ne
 * plante. C'est la famille de bug que ce dépôt documente le plus.
 *
 * `undeclared` n'est pas un type qu'on choisit : c'est ce que rend une ligne
 * héritée dont un sens est resté `neutral`, ou une paire que l'éditeur ne produit
 * pas — « entrée des deux côtés », venue d'un `configJson` bricolé. Le panneau
 * affiche alors « à préciser », et le premier choix la range.
 */
export type LineKind =
  | "bidirectional"
  | "oneway"
  | "closed"
  | "transit"
  | "undeclared";

/**
 * Le type de cette ligne, lu sur ses deux rôles.
 *
 * **`oneway` recouvre les deux anciens « sens unique ».** Ils ne différaient que
 * par le rôle du côté autorisé — `entry` ou `exit` — pour une seule et même
 * règle : un sens passe, l'autre est signalé. Deux types pour une règle
 * obligeaient à choisir un bilan de carrefour au moment où l'on décrivait une
 * interdiction, et le chiffre de tête ne s'appuie plus sur ce bilan.
 *
 * Une paire héritée `{exit, forbidden}` — preset ou `configJson` enregistré avant
 * la fusion — se relit donc sous « Autorisé · interdit » plutôt que de tomber en
 * « à préciser » : un type retiré du vocabulaire ne doit pas transformer une ligne
 * réglée en ligne à régler. `rolesForKind` la normalise en `{entry, forbidden}` au
 * premier re-choix, et jamais avant — relire un preset ne réécrit rien.
 */
export function lineKind(line: CountingLine): LineKind {
  const positive = directionRole(line, "positive");
  const negative = directionRole(line, "negative");

  if (isForbiddenRole(positive) && isForbiddenRole(negative)) return "closed";
  if (isForbiddenRole(positive) || isForbiddenRole(negative)) {
    const allowed = isForbiddenRole(positive) ? negative : positive;
    if (allowed === "entry" || allowed === "exit") return "oneway";
    return "undeclared";
  }
  if (positive === "transit" && negative === "transit") return "transit";
  if (
    (positive === "entry" && negative === "exit") ||
    (positive === "exit" && negative === "entry")
  ) {
    return "bidirectional";
  }
  return "undeclared";
}

/**
 * La paire de rôles qu'impose un type, **positif d'abord**.
 *
 * L'inverse exact de `lineKind` pour les cinq types choisissables, ce qu'un test
 * vérifie en aller-retour. `undeclared` n'est pas choisissable : il n'a pas de
 * paire à imposer, seulement une paire à quitter — d'où le repli sur le défaut
 * d'une ligne fraîchement tracée plutôt que sur `neutral`, qui laisserait
 * l'utilisateur dans l'état qu'il cherchait justement à quitter.
 */
export function rolesForKind(kind: LineKind): {
  positive: DirectionRole;
  negative: DirectionRole;
} {
  switch (kind) {
    // `entry` et non `transit` pour le côté autorisé : c'est ce qui garde ces
    // lignes dans les colonnes « Entrée par » du registre et dans les comparatifs
    // de Statistique. Un rôle neutre les en aurait sorties sans que rien ne le dise.
    case "oneway":
      return { positive: "entry", negative: "forbidden" };
    case "closed":
      return { positive: "forbidden", negative: "forbidden" };
    case "transit":
      return { positive: "transit", negative: "transit" };
    case "bidirectional":
    case "undeclared":
      return { positive: "entry", negative: "exit" };
  }
}

/** Un type choisissable, son libellé, et ce qu'il change concrètement. */
export interface LineKindOption {
  kind: LineKind;
  label: string;
  /** Une conséquence, jamais une définition : ce que ce choix fait aux chiffres. */
  hint: string;
}

/**
 * Les quatre types proposés à l'utilisateur, dans l'ordre d'affichage.
 *
 * `undeclared` n'y est pas : on ne le choisit pas, on en sort. L'ordre va du plus
 * courant au plus rare — un carrefour ordinaire d'abord, une ligne infranchissable
 * ensuite.
 */
export const LINE_KINDS: readonly LineKindOption[] = [
  {
    kind: "bidirectional",
    label: "Deux sens",
    hint: "Un sens entre dans le carrefour, l'autre en sort. Le cas ordinaire.",
  },
  {
    kind: "oneway",
    label: "Autorisé · interdit",
    hint: "Un sens passe, l'autre est interdit. Tout passage à contresens est signalé.",
  },
  {
    kind: "closed",
    label: "Infranchissable",
    hint: "Les deux sens sont interdits — ligne continue, accès fermé. Tout passage est signalé.",
  },
  {
    kind: "transit",
    label: "Comptage seul",
    hint: "Compte les passages sans entrer dans le bilan du carrefour, pour une route qui n'en est pas un.",
  },
];

/**
 * Une ligne dont au moins un sens est interdit, ou qui restreint les classes.
 *
 * C'est **la** condition d'affichage de tout ce qui parle d'infraction : le KPI
 * rouge, la colonne du registre, la section des alertes. Un « 0 infraction » sous
 * une règle que personne n'a posée se lit comme « aucune infraction », l'inverse
 * de la vérité — c'est le même raisonnement que le `null` de `LineFlow.entries`.
 */
export function lineHasRule(line: CountingLine): boolean {
  return (
    isForbiddenRole(directionRole(line, "positive")) ||
    isForbiddenRole(directionRole(line, "negative")) ||
    (line.allowedClassIds ?? null) !== null
  );
}
