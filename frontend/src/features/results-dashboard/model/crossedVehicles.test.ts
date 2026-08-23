/**
 * Les deux prédicats qui séparent un véhicule du trafic d'un objet suivi.
 *
 * Le cas qui a motivé le module : 106 objets suivis affichés sous 28 entrées,
 * sur la même analyse. Les tests ci-dessous tiennent les trois propriétés qui
 * rendent les deux chiffres comparables — le stationnement ne compte pas, une
 * sortie seule n'est pas une entrée, et un véhicule qui entre deux fois reste
 * **un** véhicule.
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine, VehicleRecord } from "@/shared/api/contracts";

import {
  crossingVehicles,
  enteringVehicleCount,
  hasCrossedAnyLine,
  hasEnteredCrossroad,
} from "./crossedVehicles";

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

function vehicle(
  globalId: number,
  crossedLines: VehicleRecord["crossedLines"] = [],
): VehicleRecord {
  return {
    globalId,
    label: "car",
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

/** Un franchissement descendant (`+1`) — le sens « entrée » des lignes ci-dessus. */
const ENTERS = { lineId: "nord", direction: 1, timestampMs: 500 };
/** Un franchissement montant (`-1`) — le sens « sortie ». */
const EXITS = { lineId: "nord", direction: -1, timestampMs: 800 };

const LINES = [line("nord"), line("est")];

describe("hasCrossedAnyLine", () => {
  it("écarte un véhicule qui n'a franchi aucune ligne", () => {
    // Le stationnement, l'attente, et la piste que le détecteur a tenue sans
    // qu'elle aille nulle part : c'est ce que le registre ne doit plus publier.
    expect(hasCrossedAnyLine(vehicle(1))).toBe(false);
  });

  it("garde un véhicule quel que soit le sens franchi", () => {
    expect(hasCrossedAnyLine(vehicle(2, [EXITS]))).toBe(true);
    expect(hasCrossedAnyLine(vehicle(3, [ENTERS]))).toBe(true);
  });
});

describe("hasEnteredCrossroad", () => {
  it("ne compte pas un véhicule qui n'a été vu que sortir", () => {
    // Il est entré hors champ. Le compter doublerait le trafic d'un carrefour
    // dont toutes les branches sont instrumentées.
    expect(hasEnteredCrossroad(vehicle(1, [EXITS]), LINES)).toBe(false);
  });

  it("compte un véhicule passé dans le sens entrée", () => {
    expect(hasEnteredCrossroad(vehicle(2, [ENTERS]), LINES)).toBe(true);
  });

  it("suit le rôle courant, pas celui de l'analyse", () => {
    // **La propriété qui rend la bascule de sens instantanée.** Le même
    // franchissement, la même donnée archivée : seul le rôle déclaré change, et
    // le verdict bascule sans relancer la moindre analyse.
    const inverse = [line("nord", { positiveRole: "exit", negativeRole: "entry" })];
    expect(hasEnteredCrossroad(vehicle(3, [ENTERS]), inverse)).toBe(false);
    expect(hasEnteredCrossroad(vehicle(4, [EXITS]), inverse)).toBe(true);
  });

  it("ignore un franchissement dont la ligne a été retirée du tracé", () => {
    // On ne peut plus lire son rôle ; supposer « entrée » inventerait un chiffre.
    expect(hasEnteredCrossroad(vehicle(5, [{ ...ENTERS, lineId: "disparue" }]), LINES)).toBe(
      false,
    );
  });

  it("ne compte pas une ligne restée neutre", () => {
    const neutre = [line("nord", { positiveRole: "neutral", negativeRole: "neutral" })];
    expect(hasEnteredCrossroad(vehicle(6, [ENTERS]), neutre)).toBe(false);
  });
});

describe("enteringVehicleCount", () => {
  it("compte des véhicules distincts, jamais des passages", () => {
    // **L'invariant 3 rendu visible.** Ce véhicule entre deux fois — deux lignes
    // d'entrée franchies. « Passages en entrée » en compterait 2 ; ici, c'est
    // un seul véhicule, et les deux chiffres ne se divisent jamais l'un par
    // l'autre.
    const deuxFois = vehicle(1, [ENTERS, { lineId: "est", direction: 1, timestampMs: 900 }]);
    expect(enteringVehicleCount([deuxFois], LINES)).toBe(1);
  });

  it("ignore le stationnement et les sorties seules", () => {
    const vehicles = [
      vehicle(1), // stationné
      vehicle(2, [EXITS]), // sorti seulement
      vehicle(3, [ENTERS]), // entré
      vehicle(4, [ENTERS, EXITS]), // entré puis ressorti
    ];
    expect(enteringVehicleCount(vehicles, LINES)).toBe(2);
    expect(crossingVehicles(vehicles)).toHaveLength(3);
  });
});
