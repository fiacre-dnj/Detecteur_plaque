/**
 * La correspondance de plaque : ce qui alerte, ce qui alerte **avec réserve**, et
 * ce qui n'alerte pas.
 *
 * La correspondance partielle n'est pas du confort : ADR 0029 documente que l'OCR
 * perd régulièrement le premier caractère d'une plaque (`AR606L` lu `R606L`).
 * L'exact seul raterait le cas le plus fréquent, en silence, sur précisément la
 * fonctionnalité qu'on a demandée.
 */

import { describe, expect, it } from "bun:test";

import { matchPlate, plateHits, type PlateBearer } from "./plateWatch";

function bearer(overrides: Partial<PlateBearer> = {}): PlateBearer {
  return { globalId: 7, label: "car", plateText: "AB-123-CD", plateTextScore: 0.9, ...overrides };
}

describe("matchPlate", () => {
  it("reconnaît la même plaque écrite autrement", () => {
    // L'utilisateur tape la plaque qu'il a en tête, pas celle que l'OCR a produite.
    expect(matchPlate("AB-123-CD", ["ab 123 cd"])).toEqual({
      watched: "ab 123 cd",
      match: "exact",
    });
  });

  it("signale une lecture tronquée comme probable, jamais comme exacte", () => {
    expect(matchPlate("R606L", ["AR606L"])).toEqual({ watched: "AR606L", match: "partial" });
  });

  it("reconnaît aussi une lecture plus longue que la plaque cherchée", () => {
    // L'OCR ajoute parfois un caractère parasite : la relation de sous-chaîne joue
    // dans les deux sens.
    expect(matchPlate("XAB123CD", ["AB123CD"])?.match).toBe("partial");
  });

  it("préfère une correspondance exacte à une partielle, quel que soit l'ordre", () => {
    // Afficher « probable » alors qu'une entrée correspond exactement ferait douter
    // d'une certitude.
    expect(matchPlate("AB123CD", ["B123C", "AB123CD"])).toEqual({
      watched: "AB123CD",
      match: "exact",
    });
  });

  it("ne correspond à rien sans plaque lue", () => {
    expect(matchPlate(null, ["AB123CD"])).toBeNull();
  });

  it("refuse les lectures trop courtes pour désigner quoi que ce soit", () => {
    // Trois caractères communs entre deux plaques quelconques sont un hasard
    // fréquent : sans ce plancher, la recherche correspondrait à presque tout.
    expect(matchPlate("AB1", ["AB123CD"])).toBeNull();
    expect(matchPlate("AB123CD", ["AB1"])).toBeNull();
  });
});

describe("plateHits", () => {
  it("rend un tableau vide sans liste de surveillance", () => {
    expect(plateHits([bearer()], [])).toEqual([]);
  });

  it("ignore les véhicules sans plaque lue", () => {
    expect(plateHits([bearer({ plateText: null })], ["AB123CD"])).toEqual([]);
  });

  it("porte le texte publié et non sa forme normalisée", () => {
    // La forme normalisée est un outil de comparaison : l'afficher à la place de ce
    // que le serveur a publié montrerait une plaque que personne n'a lue.
    const hits = plateHits([bearer()], ["ab123cd"]);

    expect(hits).toHaveLength(1);
    expect(hits[0]?.plateText).toBe("AB-123-CD");
    expect(hits[0]?.watched).toBe("ab123cd");
    expect(hits[0]?.match).toBe("exact");
  });
});
