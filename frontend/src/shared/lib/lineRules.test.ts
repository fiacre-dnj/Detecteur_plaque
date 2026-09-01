/**
 * Les règles d'une ligne, et surtout **les replis qui ne doivent pas se tromper**.
 *
 * Un repli inversé ici ne plante pas : il met tout le trafic en infraction, ou plus
 * personne. Les deux se lisent comme une panne du comptage, et aucun des deux ne
 * lève quoi que ce soit.
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine, DetectableClass } from "@/shared/api/contracts";

import { lineRules } from "./lineRules";

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

describe("lineRules", () => {
  it("ne déclare aucune règle sur une ligne ordinaire", () => {
    const rule = lineRules([line()], CATALOGUE).get("l1");

    expect(rule?.restricted).toBe(false);
    expect(rule?.forbiddenSigns).toEqual([]);
    expect(rule?.allowedClasses).toBeNull();
  });

  it("relève le sens interdit d'une ligne à sens unique", () => {
    const rule = lineRules([line({ negativeRole: "forbidden" })], CATALOGUE).get("l1");

    expect(rule?.restricted).toBe(true);
    expect(rule?.forbiddenSigns).toEqual(["negative"]);
    expect(rule?.kind).toBe("oneway");
  });

  it("relève les deux sens d'une ligne infranchissable", () => {
    const rule = lineRules(
      [line({ positiveRole: "forbidden", negativeRole: "forbidden" })],
      CATALOGUE,
    ).get("l1");

    expect(rule?.forbiddenSigns).toEqual(["positive", "negative"]);
    expect(rule?.kind).toBe("closed");
  });

  it("traduit les identifiants COCO en noms, la clé des `byClass`", () => {
    // L'identifiant n'est la clé de rien dans un résultat : comparer `2` à `"car"`
    // ne lèverait pas, ne trouverait jamais rien, et mettrait **tout** le trafic en
    // infraction sur une voie réservée.
    const rule = lineRules([line({ allowedClassIds: [5] })], CATALOGUE).get("l1");

    expect(rule?.allowedClasses).toEqual(new Set(["bus"]));
    expect(rule?.restricted).toBe(true);
  });

  it("rend `null` et jamais un ensemble vide quand aucune classe n'est reconnue", () => {
    // Catalogue changé entre l'enregistrement d'un preset et sa relecture : un
    // ensemble vide dirait « personne ne passe », donc tout franchissement en
    // infraction. Mieux vaut ne rien signaler que tout signaler.
    const rule = lineRules([line({ allowedClassIds: [999] })], CATALOGUE).get("l1");

    expect(rule?.allowedClasses).toBeNull();
    expect(rule?.restricted).toBe(false);
  });

  it("rend `null` tant que le catalogue du serveur n'a pas répondu", () => {
    const rule = lineRules([line({ allowedClassIds: [5] })], []).get("l1");

    expect(rule?.allowedClasses).toBeNull();
  });
});
