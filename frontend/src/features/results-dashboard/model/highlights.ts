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

import { directionRows, isEntryRow } from "./directions";

/** Une ligne mise en avant, avec la valeur qui justifie sa sélection. */
export interface LineHighlight {
  lineId: string;
  lineName: string;
  color: string;
  value: number;
}

interface LineFlow {
  lineId: string;
  lineName: string;
  color: string;
  total: number;
  net: number;
  entries: number;
  exits: number;
}

/**
 * Le solde entrées/sorties de chaque ligne, calculé **une seule fois** et
 * partagé par toutes les fonctions de ce module — c'est ce qui évite à
 * `strongestInflowLine` et `strongestOutflowLine` de recalculer chacune le même
 * solde par un chemin légèrement différent.
 *
 * Un sens `neutral` ne compte ni dans `net`/`entries`/`exits`, mais **`total`
 * inclut bien tous les passages** (y compris neutres) : c'est le même total
 * que `LineTally.total`, la fréquentation brute de la ligne, indépendante des
 * rôles déclarés.
 */
function flowByLine(stats: AnalysisStats, lines: readonly CountingLine[]): LineFlow[] {
  const byLine = new Map<string, LineFlow>();
  for (const line of lines) {
    byLine.set(line.id, {
      lineId: line.id,
      lineName: line.name,
      color: line.color,
      total: 0,
      net: 0,
      entries: 0,
      exits: 0,
    });
  }
  for (const row of directionRows(stats, lines)) {
    const entry = byLine.get(row.lineId);
    if (entry === undefined) continue;
    entry.total += row.tally.total;
    if (isEntryRow(row)) {
      entry.net += row.tally.total;
      entry.entries += row.tally.total;
    } else if (row.role === "exit") {
      entry.net -= row.tally.total;
      entry.exits += row.tally.total;
    }
  }
  return [...byLine.values()];
}

function best(flows: readonly LineFlow[], score: (flow: LineFlow) => number): LineHighlight | null {
  if (flows.length === 0) return null;
  const winner = flows.reduce((top, flow) => (score(flow) > score(top) ? flow : top));
  return { lineId: winner.lineId, lineName: winner.lineName, color: winner.color, value: score(winner) };
}

/** La ligne la plus fréquentée — la plus grande somme de passages, tous sens confondus. */
export function busiestLine(stats: AnalysisStats, lines: readonly CountingLine[]): LineHighlight | null {
  return best(flowByLine(stats, lines), (flow) => flow.total);
}

/** La ligne dont le bilan entrées − sorties est le plus positif : le carrefour s'y remplit le plus. */
export function strongestInflowLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(flowByLine(stats, lines), (flow) => flow.net);
}

/** La ligne dont le bilan entrées − sorties est le plus négatif : le carrefour s'y vide le plus. */
export function strongestOutflowLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(flowByLine(stats, lines), (flow) => -flow.net);
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
  return best(flowByLine(stats, lines), (flow) => flow.entries);
}

/** La ligne la plus empruntée **en sortie**, en compte brut — pendant de `mostEnteredLine`. */
export function mostExitedLine(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): LineHighlight | null {
  return best(flowByLine(stats, lines), (flow) => flow.exits);
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
  const totals = flowByLine(stats, lines).map((flow) => flow.total);
  const max = Math.max(...totals);
  const min = Math.min(...totals);
  return (max - min) / stats.crossings;
}
