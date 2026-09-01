/**
 * Le bilan par ligne, partagé par les comparatifs, la rangée de « Statistique »
 * et les cartes de la colonne de résultats.
 *
 * Le cas qui compte : `null` et `0` ne veulent pas dire la même chose. Un sens
 * sans rôle déclaré ne doit **jamais** rendre « 0 sorties », qui se lirait comme
 * un comptage alors que personne n'a déclaré de sens de sortie.
 */

import { describe, expect, it } from "bun:test";

import type { AnalysisStats, CountingLine, DirectionTally } from "@/shared/api/contracts";

import { lineFlows } from "./lineFlows";

function line(id: string, overrides: Partial<CountingLine> = {}): CountingLine {
  return {
    id,
    name: `Ligne ${id}`,
    color: "#539df5",
    zoneId: null,
    a: { x: 0, y: 500 },
    b: { x: 1920, y: 500 },
    positiveName: "",
    negativeName: "",
    positiveRole: "neutral",
    negativeRole: "neutral",
    ...overrides,
  };
}

function side(total: number): DirectionTally {
  return {
    total,
    byClass: total > 0 ? { car: total } : {},
    firstMs: total > 0 ? 1_000 : null,
    lastMs: total > 0 ? 9_000 : null,
  };
}

function stats(
  byLine: Record<string, { positive: DirectionTally; negative: DirectionTally }>,
): AnalysisStats {
  const entries = Object.entries(byLine).map(([id, directions]) => [
    id,
    {
      total: directions.positive.total + directions.negative.total,
      byClass: {},
      byDirection: directions,
    },
  ]);
  const crossings = entries.reduce(
    (sum, [, tally]) => sum + (tally as { total: number }).total,
    0,
  );
  return {
    trackedVehicles: 10,
    trackedByClass: { car: 10 },
    crossings,
    crossedUnique: 8,
    byClass: {},
    byCategory: {},
    byLine: Object.fromEntries(entries) as AnalysisStats["byLine"],
    byZone: {},
    vehiclesPerMinute: 0,
    activeTracks: 0,
    elapsedMs: 60_000,
    analysedSceneMs: 60_000,
    diagnostics: {
      highDetections: 0,
      maskedOut: 0,
      containedOut: 0,
      confirmedTracks: 0,
      tentativeTracks: 0,
      rescuedByLowScore: 0,
    },
  };
}

describe("lineFlows", () => {
  it("sépare entrées et sorties, et rend le solde et la part", () => {
    const theStats = stats({
      nord: { positive: side(8), negative: side(2) },
      est: { positive: side(1), negative: side(9) },
    });
    const lines = [
      line("nord", { positiveRole: "entry", negativeRole: "exit" }),
      line("est", { positiveRole: "entry", negativeRole: "exit" }),
    ];

    expect(lineFlows(theStats, lines)).toEqual([
      {
        lineId: "nord",
        lineName: "Ligne nord",
        color: "#539df5",
        total: 10,
        entries: 8,
        exits: 2,
        forbidden: null,
        transit: null,
        net: 6,
        shareOfTotal: 0.5,
      },
      {
        lineId: "est",
        lineName: "Ligne est",
        color: "#539df5",
        total: 10,
        entries: 1,
        exits: 9,
        forbidden: null,
        transit: null,
        net: -8,
        shareOfTotal: 0.5,
      },
    ]);
  });

  it("cumule les deux sens quand ils portent le même rôle, et laisse l'autre à `null`", () => {
    // Deux sens marqués « entrée » : 12 entrées, et **aucune** sortie déclarée.
    // `exits` doit rester `null` — « 0 sorties » se lirait comme un comptage.
    const theStats = stats({ nord: { positive: side(5), negative: side(7) } });
    const lines = [line("nord", { positiveRole: "entry", negativeRole: "entry" })];

    expect(lineFlows(theStats, lines)[0]).toMatchObject({
      total: 12,
      entries: 12,
      exits: null,
      net: 12,
    });
  });

  it("ignore les sens neutres dans le bilan mais pas dans le total", () => {
    // La fréquentation brute d'une ligne ne dépend pas des rôles déclarés :
    // c'est `LineTally.total`, et il vaut 10 même sans aucun rôle.
    const theStats = stats({ nord: { positive: side(6), negative: side(4) } });

    expect(lineFlows(theStats, [line("nord")])[0]).toMatchObject({
      total: 10,
      entries: null,
      exits: null,
      net: 0,
    });
  });

  it("garde une ligne jamais franchie, avec `shareOfTotal` à `null` quand rien n'a été compté", () => {
    // Une ligne absente de la liste se lirait comme « pas d'information », alors
    // qu'une ligne que personne ne franchit *est* une information.
    const theStats = stats({});
    const lines = [line("nord", { positiveRole: "entry", negativeRole: "exit" })];

    expect(lineFlows(theStats, lines)).toEqual([
      {
        lineId: "nord",
        lineName: "Ligne nord",
        color: "#539df5",
        total: 0,
        entries: 0,
        exits: 0,
        forbidden: null,
        transit: null,
        net: 0,
        shareOfTotal: null,
      },
    ]);
  });

  it("rend une liste vide sans ligne tracée", () => {
    expect(lineFlows(stats({}), [])).toEqual([]);
  });
});
