/**
 * Les agrégations par sens : rangées, bilan entrées/sorties, matrice O-D.
 *
 * Deux comportements sont testés pour ce qu'ils **refusent** de faire, et ce sont les
 * plus importants :
 *
 * - `flowBalance` rend `declared: false` quand aucun rôle n'est posé. Sans ce drapeau,
 *   « 0 entrée, 0 sortie » se lirait comme « aucun véhicule n'entre ni ne sort » alors
 *   que la vérité est « personne ne l'a encore dit » ;
 * - `movements` ignore un véhicule qui n'a franchi qu'une ligne. Il compte bien dans
 *   les totaux, il n'a simplement pas de trajet observable.
 */

import { describe, expect, it } from "bun:test";

import type {
  AnalysisStats,
  CountingLine,
  DirectionTally,
  VehicleRecord,
} from "@/shared/api/contracts";

import { directionRows, flowBalance, movements } from "./directions";

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
  overrides: Partial<AnalysisStats> = {},
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
      lowDetections: 0,
      maskedOut: 0,
      containedOut: 0,
      confirmedTracks: 0,
      tentativeTracks: 0,
      rescuedByLowScore: 0,
    },
    ...overrides,
  };
}

describe("directionRows", () => {
  it("rend deux rangées par ligne, dans l'ordre de la géométrie", () => {
    const rows = directionRows(
      stats({ l1: { positive: side(3), negative: side(1) } }),
      [line("l1"), line("l2")],
    );

    expect(rows.map((row) => `${row.lineId}:${row.sign}`)).toEqual([
      "l1:positive",
      "l1:negative",
      "l2:positive",
      "l2:negative",
    ]);
  });

  it("rend un sens jamais emprunté à zéro plutôt que de l'omettre", () => {
    // Une rangée absente se lirait « pas d'information » alors qu'un sens vide est
    // une information : la voie est à sens unique, ou la ligne est mal posée.
    const rows = directionRows(
      stats({ l1: { positive: side(3), negative: side(0) } }),
      [line("l1")],
    );

    const negative = rows.find((row) => row.sign === "negative");
    expect(negative?.tally.total).toBe(0);
    expect(negative?.tally.firstMs).toBeNull();
  });

  it("rend une ligne absente des stats à zéro", () => {
    // Une ligne ajoutée après l'analyse, ou une analyse relue sur une géométrie
    // modifiée. Elle ne doit pas faire planter la lecture.
    const rows = directionRows(stats({}), [line("l1")]);

    expect(rows).toHaveLength(2);
    expect(rows.every((row) => row.tally.total === 0)).toBe(true);
    expect(rows.every((row) => row.shareOfLine === null)).toBe(true);
  });

  it("calcule les parts dans la ligne et dans le total", () => {
    const rows = directionRows(
      stats({
        l1: { positive: side(3), negative: side(1) },
        l2: { positive: side(4), negative: side(0) },
      }),
      [line("l1"), line("l2")],
    );

    const first = rows[0];
    expect(first?.shareOfLine).toBeCloseTo(3 / 4);
    expect(first?.shareOfTotal).toBeCloseTo(3 / 8);
  });

  it("rend le débit null sous le seuil de trois secondes", () => {
    // Extrapoler un débit depuis une seconde d'observation produit des chiffres
    // absurdes, et l'utilisateur les prendrait au sérieux.
    const rows = directionRows(
      stats({ l1: { positive: side(2), negative: side(0) } }, { analysedSceneMs: 1_000 }),
      [line("l1")],
    );

    expect(rows[0]?.perMinute).toBeNull();
  });

  it("calcule le débit par sens au-delà du seuil", () => {
    const rows = directionRows(
      stats({ l1: { positive: side(6), negative: side(0) } }, { analysedSceneMs: 60_000 }),
      [line("l1")],
    );

    expect(rows[0]?.perMinute).toBe(6);
  });

  it("porte le nom effectif du sens, défaut compris", () => {
    const rows = directionRows(
      stats({ l1: { positive: side(1), negative: side(0) } }),
      [line("l1", { positiveName: "Entrée rue Foch" })],
    );

    expect(rows[0]?.name).toBe("Entrée rue Foch");
    expect(rows[1]?.name).toBe("Vers le haut");
  });
});

describe("flowBalance", () => {
  it("dit `declared: false` quand aucun rôle n'est posé", () => {
    // **Le test qui empêche un mensonge par omission.** Sans ce drapeau, l'écran
    // afficherait « 0 entrée · 0 sortie » sur un carrefour bien compté.
    const balance = flowBalance(
      stats({ l1: { positive: side(7), negative: side(5) } }),
      [line("l1")],
    );

    expect(balance.declared).toBe(false);
    expect(balance.entries).toBe(0);
    expect(balance.exits).toBe(0);
    expect(balance.neutral).toBe(12);
  });

  it("agrège les passages par rôle", () => {
    const balance = flowBalance(
      stats({ l1: { positive: side(7), negative: side(5) } }),
      [line("l1", { positiveRole: "entry", negativeRole: "exit" })],
    );

    expect(balance).toEqual({
      entries: 7,
      exits: 5,
      net: 2,
      neutral: 0,
      declared: true,
    });
  });

  it("agrège plusieurs lignes sous le même rôle", () => {
    // Le cas d'un vrai carrefour : deux rues instrumentées, chacune avec son entrée.
    const balance = flowBalance(
      stats({
        l1: { positive: side(7), negative: side(2) },
        l2: { positive: side(3), negative: side(4) },
      }),
      [
        line("l1", { positiveRole: "entry", negativeRole: "exit" }),
        line("l2", { positiveRole: "entry", negativeRole: "exit" }),
      ],
    );

    expect(balance.entries).toBe(10);
    expect(balance.exits).toBe(6);
    expect(balance.net).toBe(4);
  });

  it("rend un solde négatif quand la zone se vide", () => {
    // Le signe porte l'information : « −4 » dit que la rue se vide, ce qu'un « 4 »
    // absolu ne dirait pas.
    const balance = flowBalance(
      stats({ l1: { positive: side(2), negative: side(6) } }),
      [line("l1", { positiveRole: "entry", negativeRole: "exit" })],
    );

    expect(balance.net).toBe(-4);
  });

  it("compte à part les sens neutres d'une ligne partiellement déclarée", () => {
    // Une seule des deux directions marquée : le reste est du transit, et le dire
    // évite de croire que la somme entrées + sorties fait le total.
    const balance = flowBalance(
      stats({ l1: { positive: side(7), negative: side(5) } }),
      [line("l1", { positiveRole: "entry" })],
    );

    expect(balance).toMatchObject({ entries: 7, exits: 0, neutral: 5, declared: true });
  });
});

function vehicle(globalId: number, crossings: [string, number][]): VehicleRecord {
  return {
    globalId,
    label: "car",
    firstSeenMs: 0,
    lastSeenMs: 1_000,
    crossedLines: crossings.map(([lineId, direction], index) => ({
      lineId,
      direction,
      timestampMs: index * 100,
    })),
    zonesVisited: [],
    avgSpeedPxS: null,
    avgSpeedKmh: null,
    bestPlateScore: null,
    plateText: null,
    plateTextScore: null,
    plateUnreadReason: null,
    plateBestWidthPx: null,
    plateBestGuess: null,
    plateBestGuessScore: null,
  };
}

describe("movements — la matrice origine-destination", () => {
  const lines = [
    line("nord", { positiveName: "Entrée nord", negativeName: "Sortie nord" }),
    line("est", { positiveName: "Entrée est", negativeName: "Sortie est" }),
  ];

  it("décrit un trajet comme une paire de franchissements consécutifs", () => {
    const rows = movements([vehicle(1, [["nord", 1], ["est", -1]])], lines);

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      from: { lineId: "nord", sign: "positive", name: "Entrée nord" },
      to: { lineId: "est", sign: "negative", name: "Sortie est" },
      count: 1,
      share: 1,
    });
  });

  it("regroupe les véhicules qui font le même trajet", () => {
    const rows = movements(
      [
        vehicle(1, [["nord", 1], ["est", -1]]),
        vehicle(2, [["nord", 1], ["est", -1]]),
        vehicle(3, [["est", 1], ["nord", -1]]),
      ],
      lines,
    );

    expect(rows).toHaveLength(2);
    // Le mouvement dominant en tête : c'est ce qu'on cherche en ouvrant l'onglet.
    expect(rows[0]?.count).toBe(2);
    expect(rows[0]?.share).toBeCloseTo(2 / 3);
    expect(rows[1]?.count).toBe(1);
  });

  it("ignore un véhicule qui n'a franchi qu'une ligne", () => {
    // Il compte dans les totaux, il n'a simplement pas de trajet observable. Le
    // compter ici inventerait une destination.
    expect(movements([vehicle(1, [["nord", 1]])], lines)).toEqual([]);
  });

  it("produit deux mouvements pour trois franchissements", () => {
    // La limite énoncée à l'écran : la somme décrit des trajets, pas des véhicules.
    const rows = movements(
      [vehicle(1, [["nord", 1], ["est", 1], ["nord", -1]])],
      lines,
    );

    expect(rows.reduce((sum, row) => sum + row.count, 0)).toBe(2);
  });

  it("distingue deux sens sur la même paire de lignes", () => {
    // « Entré par le nord, sorti par l'est » et « entré par le nord, *entré* par
    // l'est » sont deux mouvements différents. Les fusionner effacerait les
    // mouvements tournants, qui sont l'intérêt de la matrice.
    const rows = movements(
      [vehicle(1, [["nord", 1], ["est", -1]]), vehicle(2, [["nord", 1], ["est", 1]])],
      lines,
    );

    expect(rows).toHaveLength(2);
  });

  it("ignore un mouvement dont une ligne a été retirée du tracé", () => {
    // On ne peut plus le nommer, et lui donner un identifiant brut mélangerait deux
    // vocabulaires dans le tableau.
    const rows = movements([vehicle(1, [["nord", 1], ["disparue", -1]])], lines);

    expect(rows).toEqual([]);
  });

  it("rend une liste vide sans véhicule", () => {
    expect(movements([], lines)).toEqual([]);
  });
});
