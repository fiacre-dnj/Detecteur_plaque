/**
 * Ce que ce test protège : **une recherche qui échoue sur la ponctuation**.
 *
 * L'OCR écrit « AB-123-CD », l'utilisateur tape « ab123cd », et une comparaison brute ne
 * trouve rien — sur la seule fonctionnalité dont on attend précisément qu'elle trouve.
 *
 * `test_rend_le_tableau_tel_quel_pour_une_requete_vide` compare avec `toBe` et non
 * `toEqual` : la stabilité **référentielle** est ce qui évite de recalculer la fenêtre
 * virtualisée à chaque frappe, y compris sur un champ qu'on vient de vider.
 */

import { describe, expect, it } from "bun:test";

import type { VehicleRecord } from "@/shared/api/contracts";

import { filterByPlate } from "./filterPlate";

function vehicle(globalId: number, plateText: string | null): VehicleRecord {
  return {
    globalId,
    label: "car",
    firstSeenMs: 0,
    lastSeenMs: 1000,
    crossedLines: [],
    zonesVisited: [],
    reidCount: 0,
    avgSpeedPxS: null,
    avgSpeedKmh: null,
    bestPlateScore: plateText === null ? null : 0.71,
    plateText,
    plateTextScore: plateText === null ? null : 0.88,
    // Un véhicule sans plaque publiée porte toujours une raison : c'est ce qui
    // remplace la case vide que l'utilisateur lisait comme une panne.
    plateUnreadReason: plateText === null ? "no_consensus" : null,
    plateBestWidthPx: plateText === null ? null : 96,
  };
}

const REGISTRY: readonly VehicleRecord[] = [
  vehicle(1, "AB-123-CD"),
  vehicle(2, null),
  vehicle(3, "2418TBE"),
];

describe("filterByPlate", () => {
  it("trouve une plaque tapée sans tiret ni majuscule", () => {
    expect(filterByPlate(REGISTRY, "ab123cd").map((item) => item.globalId)).toEqual([1]);
  });

  it("trouve sur une sous-chaîne : quatre chiffres relevés au passage suffisent", () => {
    expect(filterByPlate(REGISTRY, "2418").map((item) => item.globalId)).toEqual([3]);
  });

  it("trouve aussi par la fin d'une plaque", () => {
    // Un opérateur se souvient souvent des derniers caractères, pas des premiers.
    expect(filterByPlate(REGISTRY, "CD").map((item) => item.globalId)).toEqual([1]);
  });

  it("écarte les véhicules sans plaque lue", () => {
    // `null` ne doit jamais satisfaire une recherche : le véhicule 2 n'apparaît nulle
    // part, quelle que soit la requête non vide.
    expect(filterByPlate(REGISTRY, "A").some((item) => item.globalId === 2)).toBe(false);
  });

  it("rend le tableau tel quel pour une requête vide", () => {
    expect(filterByPlate(REGISTRY, "")).toBe(REGISTRY);
  });

  it("rend le tableau tel quel pour une requête de ponctuation seule", () => {
    // Sinon taper « - » retiendrait toutes les plaques françaises, ce qui ressemble à
    // un filtre qui ne fonctionne pas.
    expect(filterByPlate(REGISTRY, " - ")).toBe(REGISTRY);
  });

  it("ne rend rien plutôt que tout quand aucune plaque ne correspond", () => {
    // L'erreur classique d'un filtre mal court-circuité : rendre la liste entière
    // quand la recherche échoue.
    expect(filterByPlate(REGISTRY, "ZZ999")).toEqual([]);
  });

  it("préserve l'ordre du registre", () => {
    const found = filterByPlate([vehicle(9, "AB1"), vehicle(4, "AB2")], "ab");
    expect(found.map((item) => item.globalId)).toEqual([9, 4]);
  });
});
