/**
 * Les comparatifs entre lignes — ce qu'aucun total pris seul ne dit.
 *
 * Un total par ligne répond à « combien ». Ces fonctions répondent à
 * « laquelle » : la plus fréquentée, celle où le carrefour se remplit le plus,
 * celle où il se vide le plus. Toutes **dérivées** de `directionRows`, jamais
 * accumulées à part (invariant 3) — et toutes honnêtes sur l'absence de tracé :
 * `null` plutôt qu'une ligne inventée, comme `flowBalance.declared` et
 * `crossingRate` le pratiquent déjà ailleurs dans ce module.
 *
 * En cas d'égalité stricte, la **première ligne dans l'ordre du tracé** l'emporte
 * (`Array.prototype.reduce` ne remplace le meilleur que sur un score strictement
 * supérieur) — un choix arbitraire mais stable, plutôt qu'un ordre qui changerait
 * d'un rendu à l'autre.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";

import { lineFlows, type LineFlow } from "./lineFlows";

/** Une ligne mise en avant, avec la valeur qui justifie sa sélection. */
export interface LineHighlight {
  lineId: string;
  lineName: string;
  color: string;
  value: number;
}

/**
 * Le bilan par ligne vient de `lineFlows` et n'est plus calculé ici : trois
 * écrans posent la même question, et deux copies de la règle finiraient par
 * diverger. Un sens `neutral` n'y compte ni dans `net`, ni dans `entries`, ni
 * dans `exits`, mais **`total` inclut bien tous les passages** — c'est la
 * fréquentation brute de la ligne, indépendante des rôles déclarés.
 *
 * `entries`/`exits` valent `null` quand aucun sens ne porte le rôle ; les scores
 * ci-dessous les ramènent à `0`, parce qu'un comparatif doit bien classer une
 * ligne sans rôle déclaré quelque part — et c'est exactement ce que faisait
 * l'ancienne version, qui les initialisait à zéro.
 */
function best(flows: readonly LineFlow[], score: (flow: LineFlow) => number): LineHighlight | null {
  if (flows.length === 0) return null;
  const winner = flows.reduce((top, flow) => (score(flow) > score(top) ? flow : top));
  return { lineId: winner.lineId, lineName: winner.lineName, color: winner.color, value: score(winner) };
}

/**
 * Le pendant de `best` pour un **minimum**, et il ne s'écrit pas
 * `best(flows, (f) => -f.total)` : le `value` rendu serait négatif, alors que
 * c'est la fréquentation elle-même qu'affiche l'écran. L'égalité se tranche de
 * la même façon — comparaison **stricte**, donc la première ligne du tracé
 * l'emporte, comme pour `best`.
 */
function least(flows: readonly LineFlow[], score: (flow: LineFlow) => number): LineHighlight | null {
  if (flows.length === 0) return null;
  const winner = flows.reduce((low, flow) => (score(flow) < score(low) ? flow : low));
  return { lineId: winner.lineId, lineName: winner.lineName, color: winner.color, value: score(winner) };
}

/** La ligne la plus fréquentée — la plus grande somme de passages, tous sens confondus. */
export function busiestLine(stats: AnalysisStats, lines: readonly CountingLine[]): LineHighlight | null {
  return best(lineFlows(stats, lines), (flow) => flow.total);
}

/**
 * La ligne la **moins** fréquentée, pendant exact de `busiestLine` : la plus
 * petite somme de passages, tous sens confondus.
 *
 * Une ligne à `0` est un résultat, pas une absence de résultat — `lineFlows`
 * rend toute ligne tracée, même déserte, et c'est justement celle-là qu'il faut
 * pouvoir nommer : elle sépare « la voie est calme » de « le trait est mal
 * posé » (voir « Cette voiture est passée et elle n'est pas comptée »).
 */
export function quietestLine(stats: AnalysisStats, lines: readonly CountingLine[]): LineHighlight | null {
  return least(lineFlows(stats, lines), (flow) => flow.total);
}

/** La ligne dont le bilan entrées − sorties est le plus positif : le carrefour s'y remplit le plus. */
export function strongestInflowLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(lineFlows(stats, lines), (flow) => flow.net);
}

/** La ligne dont le bilan entrées − sorties est le plus négatif : le carrefour s'y vide le plus. */
export function strongestOutflowLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(lineFlows(stats, lines), (flow) => -flow.net);
}

/**
 * La ligne la plus empruntée **en entrée**, en compte brut — distincte de
 * `strongestInflowLine`, qui parle du solde net (entrées − sorties). Une ligne
 * peut recevoir le plus d'entrées tout en ayant un solde faible si elle laisse
 * ressortir tout autant : les deux questions ne se répondent pas l'une par
 * l'autre.
 */
export function mostEnteredLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(lineFlows(stats, lines), (flow) => flow.entries ?? 0);
}

/** La ligne la plus empruntée **en sortie**, en compte brut — pendant de `mostEnteredLine`. */
export function mostExitedLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(lineFlows(stats, lines), (flow) => flow.exits ?? 0);
}

/**
 * La ligne la plus **empruntée à contresens**.
 *
 * Le seul comparatif qui désigne un endroit plutôt qu'un flux : il répond à « où
 * faut-il aller voir », pas à « comment le carrefour se remplit ». Une ligne à sens
 * unique que dix véhicules remontent chaque heure est un problème de terrain — un
 * panneau invisible, un marquage effacé — et c'est la ligne, pas le total, qui le
 * dit.
 *
 * Compte les seuls sens **interdits** (`LineFlow.forbidden`), donc jamais une voie
 * réservée franchie par la mauvaise classe : les deux sont des infractions, mais la
 * question « quelle ligne remonte-t-on » n'a de sens que pour la première.
 */
export function mostForbiddenLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(lineFlows(stats, lines), (flow) => flow.forbidden ?? 0);
}

/**
 * Écart de part entre la ligne la plus et la moins fréquentée, en points de
 * pourcentage du total des passages.
 *
 * `null` sans ligne **et** sans aucun passage — diviser par un total nul
 * produirait `NaN`, et un écart de zéro passage n'est pas un écart de 0 %, c'est
 * une absence de mesure.
 */
export function busiestVsQuietestShareGap(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): number | null {
  if (lines.length === 0 || stats.crossings === 0) return null;
  const totals = lineFlows(stats, lines).map((flow) => flow.total);
  const max = Math.max(...totals);
  const min = Math.min(...totals);
  return (max - min) / stats.crossings;
}
