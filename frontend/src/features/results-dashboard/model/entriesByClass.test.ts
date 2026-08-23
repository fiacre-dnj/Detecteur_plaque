/**
 * `entriesByClass` — la ventilation par type du même chiffre que `flowBalance`.
 *
 * Le test qui compte est le dernier : la somme des classes doit égaler
 * `flowBalance(...).entries` **exactement**. Sans cette garantie, la carte
 * « Voitures » de la Répartition et le KPI « Passages en entrée » des
 * Résultats pourraient un jour se contredire — la même famille de bug que le
 * « taux de franchissement » à 200 % que ce dépôt a déjà payée une fois.
 */

import { describe, expect, it } from "bun:test";

import type { AnalysisStats, CountingLine, DirectionTally } from "@/shared/api/contracts";

import { entriesByClass } from "./entriesByClass";
import { flowBalance } from "./directions";

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

function side(total: number, byClass: Record<string, number> = {}): DirectionTally {
  return {
    total,
    byClass: total > 0 && Object.keys(byClass).length === 0 ? { car: total } : byClass,
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

describe("entriesByClass", () => {
  it("ne compte que les sens marqués entrée", () => {
    const totals = entriesByClass(
      stats({ l1: { positive: side(7, { car: 7 }), negative: side(5, { car: 5 }) } }),
      [line("l1", { positiveRole: "entry", negativeRole: "exit" })],
    );

    expect(totals).toEqual({ car: 7 });
  });

  it("ignore un sens neutre, comme flowBalance", () => {
    const totals = entriesByClass(
      stats({ l1: { positive: side(7, { car: 7 }), negative: side(5, { car: 5 }) } }),
      [line("l1")],
    );

    expect(totals).toEqual({});
  });

  it("ventile par classe, pas seulement le total", () => {
    const totals = entriesByClass(
      stats({ l1: { positive: side(9, { car: 6, truck: 3 }), negative: side(0) } }),
      [line("l1", { positiveRole: "entry", negativeRole: "exit" })],
    );

    expect(totals).toEqual({ car: 6, truck: 3 });
  });

  it("cumule plusieurs lignes marquées entrée pour la même classe", () => {
    const totals = entriesByClass(
      stats({
        l1: { positive: side(4, { car: 4 }), negative: side(0) },
        l2: { positive: side(3, { car: 3 }), negative: side(0) },
      }),
      [
        line("l1", { positiveRole: "entry", negativeRole: "exit" }),
        line("l2", { positiveRole: "entry", negativeRole: "exit" }),
      ],
    );

    expect(totals).toEqual({ car: 7 });
  });

  it("**somme exactement à `flowBalance(...).entries`**", () => {
    // Le test qui empêche la Répartition par type et le KPI « Entrées au
    // carrefour » de se contredire un jour.
    const theStats = stats({
      l1: { positive: side(7, { car: 5, truck: 2 }), negative: side(5, { car: 5 }) },
      l2: { positive: side(3, { bus: 3 }), negative: side(4, { car: 4 }) },
    });
    const lines = [
      line("l1", { positiveRole: "entry", negativeRole: "exit" }),
      line("l2", { positiveRole: "exit", negativeRole: "entry" }),
    ];

    const total = Object.values(entriesByClass(theStats, lines)).reduce((a, b) => a + b, 0);
    expect(total).toBe(flowBalance(theStats, lines).entries);
  });

  it("rend un objet vide sans ligne", () => {
    expect(entriesByClass(stats({}), [])).toEqual({});
  });
});
