/**
 * Ce que ce test protège : **la distinction entre « pas de plaque » et « plaque
 * illisible »**.
 *
 * Les deux s'affichent presque pareil et ne veulent pas dire la même chose — dans le
 * second, un rectangle jaune est visible à l'écran, et une case vide en face contredit
 * ce que l'utilisateur voit. C'est le bug d'affichage le plus probable de cette
 * fonctionnalité, et le plus long à expliquer quand il se produit.
 *
 * `plateLabel` rend `null` là où `plateCell` rend un mot, et ce n'est pas une
 * incohérence : sur le canvas, l'absence d'information est l'absence d'étiquette —
 * un « — » par véhicule serait du bruit posé sur l'image.
 */

import { describe, expect, it } from "bun:test";

import type { PlateDetection } from "@/shared/api/contracts";

import {
  bestReadPlate,
  normalisePlate,
  plateCell,
  plateLabel,
  plateTitle,
} from "./plate";

function plate(text: string | null, textScore: number | null, score = 0.71): PlateDetection {
  return { box: { x: 0, y: 0, width: 32, height: 9 }, score, text, textScore };
}

describe("plateLabel", () => {
  it("rend le texte et la confiance de lecture", () => {
    expect(plateLabel("AB-123-CD", 0.88)).toBe("AB-123-CD · 88 %");
  });

  it("rend null sans texte, jamais un tiret", () => {
    // Une étiquette « — » posée sur le capot serait du bruit sur l'image, et il y en
    // aurait une par véhicule.
    expect(plateLabel(null, null)).toBeNull();
  });

  it("rend null pour un texte fait d'espaces", () => {
    expect(plateLabel("   ", 0.9)).toBeNull();
  });

  it("affiche le texte seul quand la confiance manque", () => {
    expect(plateLabel("AB-123-CD", null)).toBe("AB-123-CD");
  });

  it("tronque une lecture aberrante plutôt que de déborder de l'image", () => {
    const label = plateLabel("AB123CD-GARAGE-DUPONT-SARL", 0.5);
    expect(label).toBe("AB123CD-GARA… · 50 %");
  });
});

describe("plateCell", () => {
  it("dit « illisible » quand la plaque est vue mais pas lue", () => {
    // LE cas qui compte : le score de détection prouve qu'une plaque est là.
    expect(plateCell(null, 0.71)).toBe("illisible");
  });

  it("dit « — » quand aucune plaque n'a été vue", () => {
    expect(plateCell(null, null)).toBe("—");
  });

  it("préfère le texte au score dès qu'il en existe un", () => {
    expect(plateCell("AB-123-CD", 0.71)).toBe("AB-123-CD");
    expect(plateCell("AB-123-CD", null)).toBe("AB-123-CD");
  });

  it("tronque comme l'étiquette, pour ne pas pousser la colonne voisine", () => {
    expect(plateCell("AB123CD-GARAGE-DUPONT", 0.71)).toBe("AB123CD-GARA…");
  });
});

describe("plateTitle", () => {
  it("donne les deux confiances, celle de la détection et celle de la lecture", () => {
    expect(plateTitle("AB-123-CD", 0.88, 0.71)).toBe(
      "Plaque lue à 88 % de confiance (détectée à 71 %) : AB-123-CD",
    );
  });

  it("se passe de la confiance de lecture quand elle n'existe pas", () => {
    // C'est le cas du journal des franchissements, qui ne porte pas de score de
    // détection : inventer une valeur serait pire que l'omettre.
    expect(plateTitle("AB-123-CD", 0.88, null)).toBe(
      "Plaque lue à 88 % de confiance : AB-123-CD",
    );
  });

  it("explique l'absence de lecture au lieu de se taire", () => {
    expect(plateTitle(null, null, 0.71)).toBe(
      "Plaque détectée à 71 %, mais aucune lecture ne fait consensus.",
    );
  });

  it("rend undefined quand il n'y a rien à dire", () => {
    // Et non `""` : un `title` vide produit une infobulle fantôme sur certains
    // navigateurs.
    expect(plateTitle(null, null, null)).toBeUndefined();
  });
});

describe("normalisePlate", () => {
  it("fait correspondre « 2418tbe » à « 2418 TBE »", () => {
    expect(normalisePlate("2418tbe")).toBe(normalisePlate("2418 TBE"));
  });

  it("ignore tirets, espaces et casse dans les deux sens", () => {
    expect(normalisePlate("ab-123-cd")).toBe("AB123CD");
    expect(normalisePlate("AB 123 CD")).toBe("AB123CD");
    expect(normalisePlate("AB123CD")).toBe("AB123CD");
  });

  it("rend une chaîne vide pour une requête de ponctuation seule", () => {
    // Sinon un filtre sur « - » retiendrait toutes les plaques françaises.
    expect(normalisePlate("- ")).toBe("");
  });
});

describe("bestReadPlate", () => {
  it("choisit la mieux lue et non la première listée", () => {
    // Un poids lourd porte deux plaques : ancrer l'étiquette sur la première venue
    // reviendrait à suivre l'ordre du détecteur, qui n'a aucun sens pour l'utilisateur.
    const chosen = bestReadPlate([plate("AB111AA", 0.4), plate("AB222BB", 0.95)]);
    expect(chosen?.text).toBe("AB222BB");
  });

  it("ignore les plaques repérées sans texte", () => {
    const chosen = bestReadPlate([plate(null, null), plate("AB222BB", 0.6)]);
    expect(chosen?.text).toBe("AB222BB");
  });

  it("rend null quand aucune n'est lue", () => {
    expect(bestReadPlate([plate(null, null), plate("  ", 0.9)])).toBeNull();
  });

  it("rend null sur une liste vide", () => {
    expect(bestReadPlate([])).toBeNull();
  });

  it("traite une confiance absente comme la plus faible", () => {
    const chosen = bestReadPlate([plate("AB111AA", null), plate("AB222BB", 0.1)]);
    expect(chosen?.text).toBe("AB222BB");
  });
});
