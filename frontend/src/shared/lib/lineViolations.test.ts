/**
 * Ce qui est une infraction, et surtout **ce qui n'en est pas**.
 *
 * Le mode de panne à empêcher n'est pas l'absence d'alerte : c'est l'alerte
 * inventée. Un écran qui signale des infractions fausses est abandonné en une
 * séance, et le comptage juste qu'il entoure perd sa crédibilité avec lui.
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine, CrossingEvent, DetectableClass } from "@/shared/api/contracts";

import { lineRules } from "./lineRules";
import { hasAnyRule, violationOf, violations } from "./lineViolations";

const CATALOGUE: DetectableClass[] = [
  { id: 2, cocoName: "car", label: "Voiture", category: "vehicle", defaultSelected: true },
  { id: 5, cocoName: "bus", label: "Bus", category: "vehicle", defaultSelected: true },
];

function line(overrides: Partial<CountingLine> = {}): CountingLine {
  return {
    id: "l1",
    name: "Voie nord",
    color: "#539df5",
    zoneId: null,
    a: { x: 0, y: 600 },
    b: { x: 1920, y: 600 },
    positiveName: "",
    negativeName: "",
    positiveRole: "entry",
    negativeRole: "exit",
    allowedClassIds: null,
    ...overrides,
  };
}

function crossing(overrides: Partial<CrossingEvent> = {}): CrossingEvent {
  return {
    lineId: "l1",
    globalId: 7,
    trackId: 3,
    label: "car",
    category: "vehicle",
    direction: 1,
    timestampMs: 12_000,
    frameIndex: 300,
    plateText: null,
    plateTextScore: null,
    ...overrides,
  };
}

function rulesFor(...lines: CountingLine[]) {
  return lineRules(lines, CATALOGUE);
}

describe("violationOf", () => {
  it("ne signale rien sur une ligne sans règle", () => {
    expect(violationOf(crossing(), rulesFor(line()))).toBeNull();
  });

  it("signale un contresens sur une ligne à sens unique", () => {
    const rules = rulesFor(line({ negativeRole: "forbidden" }));

    expect(violationOf(crossing({ direction: -1 }), rules)?.kind).toBe("wrong-way");
    // Le sens autorisé, lui, ne signale rien : c'est le trajet normal.
    expect(violationOf(crossing({ direction: 1 }), rules)).toBeNull();
  });

  it("distingue une ligne infranchissable d'un contresens", () => {
    // Deux mots différents parce que « à contresens » suppose un sens autorisé en
    // face, ce qu'une ligne infranchissable n'a pas.
    const rules = rulesFor(line({ positiveRole: "forbidden", negativeRole: "forbidden" }));

    expect(violationOf(crossing({ direction: 1 }), rules)?.kind).toBe("closed-line");
    expect(violationOf(crossing({ direction: -1 }), rules)?.kind).toBe("closed-line");
  });

  it("signale une classe non autorisée sur une voie réservée", () => {
    const rules = rulesFor(line({ allowedClassIds: [5] }));

    expect(violationOf(crossing({ label: "car" }), rules)?.kind).toBe("reserved-lane");
    expect(violationOf(crossing({ label: "bus" }), rules)).toBeNull();
  });

  it("ne compte qu'une infraction quand deux règles sont enfreintes à la fois", () => {
    // Un bus qui remonte une voie réservée à contresens enfreint les deux. Le
    // compter deux fois ferait diverger la liste des alertes du KPI, qui somme des
    // passages — et les deux se lisent sur le même écran. Le sens interdit passe
    // devant : il porte sur le trajet, la voie réservée sur le véhicule.
    const rules = rulesFor(line({ negativeRole: "forbidden", allowedClassIds: [5] }));
    const found = violations([crossing({ direction: -1, label: "car" })], rules);

    expect(found).toHaveLength(1);
    expect(found[0]?.kind).toBe("wrong-way");
  });

  it("n'invente aucune infraction sur une ligne retirée du tracé", () => {
    // Son rôle n'existe plus nulle part, et le franchissement, lui, a bien eu lieu.
    // L'inventer serait pire que de n'en signaler aucune.
    const rules = rulesFor(line({ id: "autre", negativeRole: "forbidden" }));

    expect(violationOf(crossing({ lineId: "l1", direction: -1 }), rules)).toBeNull();
  });

  it("laisse passer une classe inconnue du catalogue plutôt que de la punir", () => {
    // Le catalogue ne connaît pas `motorcycle` ici : la restriction ne s'y applique
    // donc pas, faute de savoir ce qu'elle autorise vraiment.
    const rules = rulesFor(line({ allowedClassIds: [999] }));

    expect(violationOf(crossing({ label: "motorcycle" }), rules)).toBeNull();
  });
});

describe("hasAnyRule", () => {
  it("est faux sur un tracé ordinaire, vrai dès qu'une règle existe", () => {
    expect(hasAnyRule(rulesFor(line()))).toBe(false);
    expect(hasAnyRule(rulesFor(line({ negativeRole: "forbidden" })))).toBe(true);
    expect(hasAnyRule(rulesFor(line({ allowedClassIds: [5] })))).toBe(true);
  });
});
