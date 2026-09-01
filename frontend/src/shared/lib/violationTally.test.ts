/**
 * Les totaux d'infraction, **dérivés de `stats`** et jamais de la longueur du
 * journal d'alertes.
 *
 * Le journal est borné à 200 entrées ; ces totaux ne le sont pas. Les confondre
 * ferait plafonner un compteur en silence sous un tableau de bord qui continue de
 * monter — invariant 3, un défaut que ce dépôt a déjà payé une fois.
 */

import { describe, expect, it } from "bun:test";

import type { AnalysisStats, CountingLine, DetectableClass } from "@/shared/api/contracts";
import { lineRules } from "@/shared/lib/lineRules";

import { violationCounts } from "./violationTally";

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

function side(total: number, byClass: Record<string, number> = { car: total }) {
  return { total, byClass, firstMs: 0, lastMs: 1_000 };
}

function stats(positive: ReturnType<typeof side>, negative: ReturnType<typeof side>): AnalysisStats {
  return {
    trackedVehicles: 0,
    trackedByClass: {},
    crossings: positive.total + negative.total,
    crossedUnique: 0,
    byClass: {},
    byCategory: {},
    byLine: {
      l1: {
        total: positive.total + negative.total,
        byClass: {},
        byDirection: { positive, negative },
      },
    },
    byZone: {},
    vehiclesPerMinute: 0,
    activeTracks: 0,
    elapsedMs: 10_000,
    analysedSceneMs: 10_000,
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

describe("violationCounts", () => {
  it("ne déclare rien sur un tracé sans règle", () => {
    // `declared` faux **masque le KPI** : un « 0 » sous une règle que personne n'a
    // posée se lit « aucune infraction », l'inverse de la vérité.
    const lines = [line()];
    const counts = violationCounts(stats(side(7), side(5)), lines, lineRules(lines, CATALOGUE));

    expect(counts.declared).toBe(false);
    expect(counts.total).toBe(0);
  });

  it("compte les passages du sens interdit, et eux seuls", () => {
    const lines = [line({ negativeRole: "forbidden" })];
    const counts = violationCounts(stats(side(7), side(5)), lines, lineRules(lines, CATALOGUE));

    expect(counts.declared).toBe(true);
    expect(counts.forbidden).toBe(5);
    expect(counts.reservedLane).toBe(0);
    expect(counts.total).toBe(5);
    expect(counts.byLine.l1).toBe(5);
  });

  it("déclare la règle même quand personne ne l'a enfreinte", () => {
    // C'est ce qui distingue « rien à signaler ici » de « on ne surveille rien
    // ici » : le KPI s'affiche à zéro, ce qui est une information.
    const lines = [line({ negativeRole: "forbidden" })];
    const counts = violationCounts(stats(side(7), side(0)), lines, lineRules(lines, CATALOGUE));

    expect(counts.declared).toBe(true);
    expect(counts.total).toBe(0);
  });

  it("compte les classes non autorisées d'une voie réservée", () => {
    const lines = [line({ allowedClassIds: [5] })];
    const counts = violationCounts(
      stats(side(7, { car: 4, bus: 3 }), side(2, { bus: 2 })),
      lines,
      lineRules(lines, CATALOGUE),
    );

    expect(counts.reservedLane).toBe(4);
    expect(counts.forbidden).toBe(0);
  });

  it("ne compte qu'une fois un passage qui enfreint les deux règles", () => {
    // Même priorité que `violationOf` : le sens interdit passe devant. Sans elle,
    // ce total et la liste des alertes diraient deux chiffres différents sur le
    // même écran.
    const lines = [line({ negativeRole: "forbidden", allowedClassIds: [5] })];
    const counts = violationCounts(
      stats(side(0), side(3, { car: 3 })),
      lines,
      lineRules(lines, CATALOGUE),
    );

    expect(counts.forbidden).toBe(3);
    expect(counts.reservedLane).toBe(0);
    expect(counts.total).toBe(3);
  });
});

describe("la ventilation du résumé — par nature et par type de véhicule", () => {
  it("sépare le contresens de la ligne infranchissable", () => {
    // Le KPI les additionne sous « Franchissements interdits » ; le résumé les
    // distingue, parce que « à contresens » suppose un sens autorisé en face et
    // qu'une ligne infranchissable n'en a pas. Deux faits, deux gestes.
    const oneway = [line({ negativeRole: "forbidden" })];
    const wrongWay = violationCounts(stats(side(0), side(4)), oneway, lineRules(oneway, CATALOGUE));

    expect(wrongWay.byKind["wrong-way"]).toBe(4);
    expect(wrongWay.byKind["closed-line"]).toBe(0);

    const shut = [line({ positiveRole: "forbidden", negativeRole: "forbidden" })];
    const closed = violationCounts(stats(side(2), side(1)), shut, lineRules(shut, CATALOGUE));

    expect(closed.byKind["closed-line"]).toBe(3);
    expect(closed.byKind["wrong-way"]).toBe(0);
  });

  it("répond à « quels types enfreignent quoi »", () => {
    const lines = [line({ allowedClassIds: [5] })];
    const counts = violationCounts(
      stats(side(7, { car: 4, bus: 3 }), side(2, { bus: 2 })),
      lines,
      lineRules(lines, CATALOGUE),
    );

    expect(counts.byClass.car?.["reserved-lane"]).toBe(4);
    // Le bus est autorisé : il n'a pas de rangée du tout. Une rangée à zéro se
    // lirait « surveillé, rien à signaler », alors qu'il n'y avait rien à signaler
    // *sur lui* par construction.
    expect(counts.byClass.bus).toBeUndefined();
  });

  it("somme exactement au total, sur les deux axes", () => {
    // C'est la propriété qui rend le résumé lisible à côté du KPI : trois chiffres
    // qui ne sommeraient pas au quatrième feraient douter des quatre.
    const lines = [line({ negativeRole: "forbidden", allowedClassIds: [5] })];
    const counts = violationCounts(
      stats(side(6, { car: 4, bus: 2 }), side(3, { car: 3 })),
      lines,
      lineRules(lines, CATALOGUE),
    );

    const byKind = Object.values(counts.byKind).reduce((sum, n) => sum + n, 0);
    const byClass = Object.values(counts.byClass)
      .flatMap((kinds) => Object.values(kinds))
      .reduce((sum, n) => sum + n, 0);

    expect(byKind).toBe(counts.total);
    expect(byClass).toBe(counts.total);
  });

  it("range un passage doublement fautif sous la seule nature retenue", () => {
    // La même priorité qu'au total, appliquée aussi à la ventilation : sinon le
    // résumé compterait 6 là où le KPI juste au-dessus affiche 3.
    const lines = [line({ negativeRole: "forbidden", allowedClassIds: [5] })];
    const counts = violationCounts(
      stats(side(0), side(3, { car: 3 })),
      lines,
      lineRules(lines, CATALOGUE),
    );

    expect(counts.byKind["wrong-way"]).toBe(3);
    expect(counts.byKind["reserved-lane"]).toBe(0);
    expect(counts.byClass.car).toEqual({
      "wrong-way": 3,
      "closed-line": 0,
      "reserved-lane": 0,
    });
  });
});
