/**
 * Les franchissements rangés par rôle — la source des colonnes « Entrée » et
 * « Sortie » du registre.
 *
 * Ce qui est verrouillé ici : le rôle est lu sur le **tracé courant**, une ligne
 * disparue n'invente pas d'heure, l'ordre chronologique tient — c'est lui qui fait
 * que la cellule montre le *premier* franchissement — et un aller-retour reste deux
 * franchissements, jamais un (invariant 6).
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine, VehicleRecord } from "@/shared/api/contracts";

import { crossingsWithRole, crossingsWithoutRole } from "./roleCrossings";

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
    positiveRole: "entry",
    negativeRole: "exit",
    ...overrides,
  };
}

function vehicle(crossedLines: VehicleRecord["crossedLines"] = []): VehicleRecord {
  return {
    globalId: 1,
    label: "car",
    firstSeenMs: 0,
    lastSeenMs: 10_000,
    crossedLines,
    zonesVisited: [],
    bestPlateScore: null,
    plateText: null,
    plateTextScore: null,
    plateUnreadReason: null,
    plateBestWidthPx: null,
    plateBestGuess: null,
    plateBestGuessScore: null,
  };
}

const LINES = [line("nord"), line("est")];

describe("crossingsWithRole", () => {
  it("sépare l'entrée de la sortie sur le signe du franchissement", () => {
    const record = vehicle([
      { lineId: "nord", direction: 1, timestampMs: 3_400 },
      { lineId: "est", direction: -1, timestampMs: 7_800 },
    ]);

    expect(crossingsWithRole(record, LINES, "entry").map((c) => c.timestampMs)).toEqual([3_400]);
    expect(crossingsWithRole(record, LINES, "exit").map((c) => c.timestampMs)).toEqual([7_800]);
  });

  it("suit le rôle déclaré par la ligne et non le signe", () => {
    // La bascule d'un sens entrée ↔ sortie doit se répercuter sans réanalyser :
    // le rôle vit dans le tracé, jamais dans le résultat archivé (ADR 0016).
    const inverted = [line("nord", { positiveRole: "exit", negativeRole: "entry" })];
    const record = vehicle([{ lineId: "nord", direction: 1, timestampMs: 3_400 }]);

    expect(crossingsWithRole(record, inverted, "entry")).toHaveLength(0);
    expect(crossingsWithRole(record, inverted, "exit")).toHaveLength(1);
  });

  it("ignore un franchissement dont la ligne a quitté le tracé", () => {
    // Supposer « entrée » afficherait une heure de franchissement fausse. La
    // colonne se tait ; « Lignes franchies » garde la flèche brute.
    const record = vehicle([{ lineId: "supprimee", direction: 1, timestampMs: 3_400 }]);

    expect(crossingsWithRole(record, LINES, "entry")).toHaveLength(0);
    expect(crossingsWithRole(record, LINES, "exit")).toHaveLength(0);
  });

  it("ignore un sens resté neutral, sans le ranger dans un rôle par défaut", () => {
    // Une ligne tracée avant ADR 0021, ou relue d'un preset archivé.
    const old = [line("nord", { positiveRole: "neutral", negativeRole: "neutral" })];
    const record = vehicle([{ lineId: "nord", direction: 1, timestampMs: 3_400 }]);

    expect(crossingsWithRole(record, old, "entry")).toHaveLength(0);
    expect(crossingsWithRole(record, old, "exit")).toHaveLength(0);
  });

  it("garde les deux entrées d'un aller-retour, dans l'ordre chronologique", () => {
    // Invariant 6 : un aller-retour compte 2. La cellule affiche le premier
    // instant et annonce le second — elle ne les fusionne pas.
    const record = vehicle([
      { lineId: "nord", direction: 1, timestampMs: 3_400 },
      { lineId: "nord", direction: -1, timestampMs: 5_100 },
      { lineId: "est", direction: 1, timestampMs: 9_200 },
    ]);

    expect(crossingsWithRole(record, LINES, "entry").map((c) => c.timestampMs)).toEqual([
      3_400, 9_200,
    ]);
  });

  it("rend une liste vide pour un véhicule qui n'a rien franchi", () => {
    expect(crossingsWithRole(vehicle(), LINES, "entry")).toHaveLength(0);
  });
});

describe("crossingsWithoutRole", () => {
  it("ne réclame rien quand les deux sens portent un rôle", () => {
    const record = vehicle([
      { lineId: "nord", direction: 1, timestampMs: 3_400 },
      { lineId: "est", direction: -1, timestampMs: 7_800 },
    ]);

    expect(crossingsWithoutRole(record, LINES)).toEqual([]);
  });

  it("récupère une ligne retirée du tracé et un sens resté neutre", () => {
    const record = vehicle([
      { lineId: "nord", direction: 1, timestampMs: 1_000 },
      // Ligne absente du tracé courant : son rôle n'est plus lisible nulle part.
      { lineId: "disparue", direction: 1, timestampMs: 2_000 },
      // Tracé antérieur à ADR 0021, où le rôle est devenu obligatoire.
      { lineId: "ancienne", direction: -1, timestampMs: 3_000 },
    ]);
    const lines = [
      ...LINES,
      line("ancienne", { positiveRole: "neutral", negativeRole: "neutral" }),
    ];

    expect(crossingsWithoutRole(record, lines).map((crossing) => crossing.lineId)).toEqual([
      "disparue",
      "ancienne",
    ]);
  });

  it("est le complément exact des deux rôles : aucun passage ne se perd", () => {
    // C'est la propriété qui autorise le registre à ranger « Lignes franchies »
    // par rôle : les trois colonnes réunies redonnent `crossedLines`, donc la
    // colonne « Passages », qui les compte toutes, ne peut pas les contredire.
    const record = vehicle([
      { lineId: "nord", direction: 1, timestampMs: 1_000 },
      { lineId: "est", direction: -1, timestampMs: 2_000 },
      { lineId: "disparue", direction: 1, timestampMs: 3_000 },
    ]);

    const parts = [
      ...crossingsWithRole(record, LINES, "entry"),
      ...crossingsWithRole(record, LINES, "exit"),
      ...crossingsWithoutRole(record, LINES),
    ];

    expect(parts).toHaveLength(record.crossedLines.length);
    expect(new Set(parts)).toEqual(new Set(record.crossedLines));
  });
});
