/**
 * Les cartes par type **somment au chiffre de tête**, et c'est tout ce qui compte.
 *
 * La propriété est la même qu'au temps d'`entriesByClass` ; seule l'unité a changé.
 * Elle est verrouillée ici plutôt que laissée à la relecture parce que le mode de
 * panne est silencieux : deux chiffres plausibles, posés l'un sous l'autre, qui ne
 * s'additionnent pas. Rien ne plante, et l'écran devient invérifiable.
 */

import { describe, expect, it } from "bun:test";

import type { VehicleRecord } from "@/shared/api/contracts";

import { crossedByClass } from "./crossedByClass";
import { crossingVehicles } from "./crossedVehicles";

function vehicle(
  globalId: number,
  label: string,
  crossedLines: VehicleRecord["crossedLines"] = [],
): VehicleRecord {
  return {
    globalId,
    label,
    firstSeenMs: 0,
    lastSeenMs: 1_000,
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

const NORTH = { lineId: "nord", direction: 1, timestampMs: 500 };
const SOUTH = { lineId: "sud", direction: -1, timestampMs: 900 };

describe("crossedByClass", () => {
  it("compte des véhicules distincts, jamais des passages", () => {
    // Le véhicule #1 franchit deux lignes : il vaut **1** ici, là où « Passages en
    // entrée » en comptait 2. C'est exactement le double comptage que le nouveau
    // chiffre de tête existe pour supprimer.
    const counts = crossedByClass([vehicle(1, "car", [NORTH, SOUTH])]);

    expect(counts.car).toBe(1);
  });

  it("somme exactement au nombre de lignes du registre", () => {
    // La propriété qui rend les cartes lisibles sous le KPI : leur somme **est** le
    // chiffre de tête, et les deux se calculent sur la même population.
    const vehicles = [
      vehicle(1, "car", [NORTH]),
      vehicle(2, "car", [NORTH, SOUTH]),
      vehicle(3, "truck", [SOUTH]),
      vehicle(4, "bus", [NORTH]),
    ];
    const counts = crossedByClass(vehicles);
    const sum = Object.values(counts).reduce((total, n) => total + n, 0);

    expect(counts).toEqual({ car: 2, truck: 1, bus: 1 });
    expect(sum).toBe(crossingVehicles(vehicles).length);
  });

  it("ignore un véhicule qui n'a rien franchi", () => {
    // Une voiture en stationnement est un objet suivi, pas un passage. Elle n'est
    // pas au registre non plus : les deux écrans lisent le même prédicat.
    const counts = crossedByClass([vehicle(1, "car", [NORTH]), vehicle(2, "car")]);

    expect(counts.car).toBe(1);
  });

  it("n'invente aucune classe à zéro", () => {
    // `visibleClasses` réunit les classes cochées et celles qui portent un compte :
    // poser des zéros ici ferait entrer dans cette réunion des types que personne
    // n'a cochés et que personne n'a vus.
    expect(crossedByClass([vehicle(1, "car", [NORTH])])).toEqual({ car: 1 });
  });
});
