/**
 * Le filtre par ligne du registre.
 *
 * L'identité référentielle est testée au même titre que le filtrage : sans elle, la
 * fenêtre virtualisée se recalcule à chaque frappe dans le champ de recherche
 * voisin, et un tableau de 10 000 lignes se met à saccader sur une touche.
 */

import { describe, expect, it } from "bun:test";

import type { VehicleRecord } from "@/shared/api/contracts";

import { filterByLine } from "./filterLine";

function vehicle(globalId: number, lineIds: readonly string[]): VehicleRecord {
  return {
    globalId,
    label: "car",
    firstSeenMs: 0,
    lastSeenMs: 1_000,
    crossedLines: lineIds.map((lineId, index) => ({
      lineId,
      direction: index % 2 === 0 ? 1 : -1,
      timestampMs: 500 + index,
    })),
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

const VEHICLES = [vehicle(1, ["nord"]), vehicle(2, ["est", "nord"]), vehicle(3, ["est"])];

describe("filterByLine", () => {
  it("rend le tableau tel quel, par référence, sans ligne choisie", () => {
    expect(filterByLine(VEHICLES, null)).toBe(VEHICLES);
  });

  it("garde les véhicules passés par la ligne, dans n'importe quel sens", () => {
    // Les deux sens et non un seul : la question posée est « qui est passé par
    // là », pas « qui est entré ». Le sens se lit dans les colonnes voisines.
    expect(filterByLine(VEHICLES, "nord").map((entry) => entry.globalId)).toEqual([1, 2]);
  });

  it("rend une liste vide sur une ligne que personne n'a franchie", () => {
    // Vide et non « tout » : c'est une information — la voie est déserte, ou le
    // trait est mal posé.
    expect(filterByLine(VEHICLES, "sud")).toEqual([]);
  });
});
