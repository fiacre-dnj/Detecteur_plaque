/**
 * Les comparatifs entre lignes.
 *
 * Le cas qui compte : `null` plutôt qu'une ligne inventée quand il n'y a rien à
 * comparer — un tracé vide, ou un carrefour qui n'a rien vu passer.
 */

import { describe, expect, it } from "bun:test";

import type { AnalysisStats, CountingLine, DirectionTally } from "@/shared/api/contracts";

import {
  busiestLine,
  busiestVsQuietestShareGap,
  mostEnteredLine,
  mostExitedLine,
  strongestInflowLine,
  strongestOutflowLine,
} from "./highlights";

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
    lengthMeters: null,
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

const TWO_LINES = [
  line("nord", { positiveRole: "entry", negativeRole: "exit" }),
  line("est", { positiveRole: "entry", negativeRole: "exit" }),
];

describe("busiestLine", () => {
  it("rend `null` sans ligne", () => {
    expect(busiestLine(stats({}), [])).toBeNull();
  });

  it("identifie la ligne la plus fréquentée, tous sens confondus", () => {
    const theStats = stats({
      nord: { positive: side(3), negative: side(2) },
      est: { positive: side(8), negative: side(1) },
    });

    expect(busiestLine(theStats, TWO_LINES)).toMatchObject({ lineId: "est", value: 9 });
  });

  it("garde la première ligne du tracé en cas d'égalité", () => {
    const theStats = stats({
      nord: { positive: side(5), negative: side(0) },
      est: { positive: side(5), negative: side(0) },
    });

    expect(busiestLine(theStats, TWO_LINES)?.lineId).toBe("nord");
  });
});

describe("strongestInflowLine et strongestOutflowLine", () => {
  it("distinguent l'afflux et le reflux les plus forts", () => {
    const theStats = stats({
      // nord : 8 entrées, 2 sorties -> solde +6, le plus fort afflux.
      nord: { positive: side(8), negative: side(2) },
      // est : 1 entrée, 7 sorties -> solde -6, le plus fort reflux.
      est: { positive: side(1), negative: side(7) },
    });

    expect(strongestInflowLine(theStats, TWO_LINES)).toMatchObject({ lineId: "nord", value: 6 });
    expect(strongestOutflowLine(theStats, TWO_LINES)).toMatchObject({ lineId: "est", value: 6 });
  });

  it("ignore les sens neutres dans le solde", () => {
    // Aucun rôle déclaré : le solde reste à zéro pour les deux lignes, la
    // première l'emporte.
    const theStats = stats({
      nord: { positive: side(8), negative: side(2) },
      est: { positive: side(1), negative: side(7) },
    });

    const result = strongestInflowLine(theStats, [line("nord"), line("est")]);
    expect(result).toMatchObject({ lineId: "nord", value: 0 });
  });

  it("rendent `null` sans ligne", () => {
    expect(strongestInflowLine(stats({}), [])).toBeNull();
    expect(strongestOutflowLine(stats({}), [])).toBeNull();
  });
});

describe("mostEnteredLine et mostExitedLine", () => {
  it("distinguent la ligne la plus entrée de la ligne la plus sortie, en compte brut", () => {
    const theStats = stats({
      // nord : 8 entrées, 2 sorties -> la plus entrée en brut.
      nord: { positive: side(8), negative: side(2) },
      // est : 1 entrée, 7 sorties -> la plus sortie en brut.
      est: { positive: side(1), negative: side(7) },
    });

    expect(mostEnteredLine(theStats, TWO_LINES)).toMatchObject({ lineId: "nord", value: 8 });
    expect(mostExitedLine(theStats, TWO_LINES)).toMatchObject({ lineId: "est", value: 7 });
  });

  it("ne se confond pas avec le solde net : la ligne la plus entrée peut avoir le plus petit solde", () => {
    // nord : 10 entrées, 9 sorties -> solde +1, mais la plus entrée en brut.
    // est   : 2 entrées, 0 sortie   -> solde +2, le plus fort afflux net.
    const theStats = stats({
      nord: { positive: side(10), negative: side(9) },
      est: { positive: side(2), negative: side(0) },
    });

    expect(mostEnteredLine(theStats, TWO_LINES)).toMatchObject({ lineId: "nord", value: 10 });
    expect(strongestInflowLine(theStats, TWO_LINES)).toMatchObject({ lineId: "est", value: 2 });
  });

  it("rendent `null` sans ligne", () => {
    expect(mostEnteredLine(stats({}), [])).toBeNull();
    expect(mostExitedLine(stats({}), [])).toBeNull();
  });
});

describe("busiestVsQuietestShareGap", () => {
  it("rend `null` sans ligne", () => {
    expect(busiestVsQuietestShareGap(stats({}), [])).toBeNull();
  });

  it("rend `null` quand rien n'a été compté, plutôt que 0 %", () => {
    // Un écart de zéro passage n'est pas un écart nul mesuré : c'est une
    // absence de mesure. Les confondre afficherait « 0 % » comme si le
    // carrefour était parfaitement équilibré.
    const theStats = stats({ nord: { positive: side(0), negative: side(0) } });
    expect(busiestVsQuietestShareGap(theStats, [line("nord")])).toBeNull();
  });

  it("calcule l'écart de part entre la ligne la plus et la moins fréquentée", () => {
    const theStats = stats({
      nord: { positive: side(9), negative: side(0) },
      est: { positive: side(1), negative: side(0) },
    });

    // 9 sur 10 contre 1 sur 10 : écart de 80 points.
    expect(busiestVsQuietestShareGap(theStats, TWO_LINES)).toBeCloseTo(0.8);
  });

  it("rend zéro quand toutes les lignes sont également fréquentées", () => {
    const theStats = stats({
      nord: { positive: side(5), negative: side(0) },
      est: { positive: side(5), negative: side(0) },
    });

    expect(busiestVsQuietestShareGap(theStats, TWO_LINES)).toBe(0);
  });
});
