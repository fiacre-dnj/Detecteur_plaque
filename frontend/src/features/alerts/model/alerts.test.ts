/**
 * Le journal d'alertes : sa clé de dédoublonnage, son ordre, sa borne.
 *
 * Trois propriétés qui ont chacune un mode de panne visible à l'écran : une clé
 * trop large fait disparaître un aller-retour interdit, une clé trop étroite remplit
 * la pile du même véhicule cinq fois par seconde, et un tri absent fait remonter en
 * tête une alerte sans qu'il se soit rien passé.
 */

import { describe, expect, it } from "bun:test";

import type { CrossingEvent } from "@/shared/api/contracts";
import type { LineRule } from "@/shared/lib/lineRules";
import type { Violation } from "@/shared/lib/lineViolations";

import {
  alertFromPlateHit,
  alertFromViolation,
  crossingsBefore,
  mergeAlerts,
  sortAlerts,
} from "./alerts";
import type { PlateHit } from "./plateWatch";

const RULE: LineRule = {
  lineId: "l1",
  lineName: "Voie nord",
  color: "#539df5",
  kind: "oneway",
  forbiddenSigns: ["negative"],
  allowedClasses: null,
  restricted: true,
};

function crossing(overrides: Partial<CrossingEvent> = {}): CrossingEvent {
  return {
    lineId: "l1",
    globalId: 7,
    trackId: 3,
    label: "car",
    category: "vehicle",
    direction: -1,
    timestampMs: 12_000,
    frameIndex: 300,
    plateText: null,
    plateTextScore: null,
    ...overrides,
  };
}

function violation(overrides: Partial<CrossingEvent> = {}): Violation {
  return { kind: "wrong-way", crossing: crossing(overrides), rule: RULE };
}

const HIT: PlateHit = {
  globalId: 7,
  label: "car",
  plateText: "AB-123-CD",
  plateTextScore: 0.9,
  watched: "ab123cd",
  match: "exact",
};

describe("clés de dédoublonnage", () => {
  it("un aller-retour interdit produit deux alertes", () => {
    // Invariant 6 : deux passages sont deux faits. Une clé qui les fondrait ferait
    // disparaître la moitié de ce qu'on demande de signaler.
    const merged = mergeAlerts(
      [],
      [violation({ timestampMs: 12_000 }), violation({ timestampMs: 18_000 })].map(
        alertFromViolation,
      ),
    );

    expect(merged).toHaveLength(2);
  });

  it("le même franchissement republié n'en ajoute pas un second", () => {
    const first = mergeAlerts([], [alertFromViolation(violation())]);
    const again = mergeAlerts(first, [alertFromViolation(violation())]);

    expect(again).toHaveLength(1);
    // Rendu **par référence** : un aperçu qui n'apporte rien ne doit pas faire
    // rerendre la pile cinq fois par seconde.
    expect(again).toBe(first);
  });

  it("une plaque republiée à chaque image garde sa date d'origine", () => {
    // Sans cela, l'alerte remonterait en tête de liste à chaque aperçu, sans qu'il
    // se soit rien passé.
    const first = mergeAlerts([], [alertFromPlateHit(HIT, 4_000)]);
    const again = mergeAlerts(first, [alertFromPlateHit(HIT, 9_000)]);

    expect(again).toHaveLength(1);
    expect(again[0]?.timestampMs).toBe(4_000);
  });

  it("la même plaque sur deux véhicules produit deux alertes", () => {
    const merged = mergeAlerts(
      [],
      [alertFromPlateHit(HIT, 4_000), alertFromPlateHit({ ...HIT, globalId: 9 }, 5_000)],
    );

    expect(merged).toHaveLength(2);
  });
});

describe("ordre et borne", () => {
  it("insère à sa date, plus récent en tête, même arrivé en désordre", () => {
    // Depuis ADR 0038 un franchissement porte la date de son intersection avec le
    // trait : deux passages peuvent arriver dans deux trames SSE différentes en
    // ordre inverse de leurs dates.
    const merged = mergeAlerts(
      [alertFromViolation(violation({ timestampMs: 20_000 }))],
      [alertFromViolation(violation({ timestampMs: 5_000, globalId: 8 }))],
    );

    expect(merged.map((alert) => alert.timestampMs)).toEqual([20_000, 5_000]);
  });

  it("garde les plus récentes quand la borne est atteinte", () => {
    const many = Array.from({ length: 5 }, (_, index) =>
      alertFromViolation(violation({ timestampMs: index * 1_000, globalId: index })),
    );

    expect(mergeAlerts([], many, 2).map((alert) => alert.timestampMs)).toEqual([4_000, 3_000]);
    expect(sortAlerts(many, 2).map((alert) => alert.timestampMs)).toEqual([4_000, 3_000]);
  });
});

describe("gravité", () => {
  it("une correspondance probable avertit, une exacte alerte", () => {
    expect(alertFromPlateHit(HIT, 0).severity).toBe("critical");
    expect(alertFromPlateHit({ ...HIT, match: "partial" }, 0).severity).toBe("warning");
  });
});

describe("crossingsBefore", () => {
  it("s'arrête à la tête de lecture, borne incluse", () => {
    const all = [crossing({ timestampMs: 1_000 }), crossing({ timestampMs: 3_000 })];

    expect(crossingsBefore(all, 1_000)).toHaveLength(1);
    expect(crossingsBefore(all, 3_000)).toHaveLength(2);
  });
});
