/**
 * Regroupement et navigation clavier du sélecteur de modèles.
 *
 * Le test central : **les flèches parcourent la liste à plat**. Un utilisateur au
 * clavier qui doit « sortir » d'un groupe pour entrer dans le suivant se retrouve
 * bloqué sans comprendre pourquoi, et c'est le défaut classique des listes groupées.
 */

import { describe, expect, it } from "bun:test";

import type { ModelTier, VehicleModel } from "@/shared/api/contracts";

import {
  TIER_ORDER,
  flatOrder,
  groupByTier,
  modelSizeLabel,
  modelStateLabel,
  nextIndex,
} from "./grouping";

function model(id: string, tier: ModelTier, overrides: Partial<VehicleModel> = {}): VehicleModel {
  return {
    id,
    label: id.toUpperCase(),
    family: "yolo11",
    tier,
    tierLabel: `Palier ${tier}`,
    note: "",
    sizeMb: 6,
    sizeBytes: null,
    downloaded: false,
    loaded: false,
    isDefault: false,
    ...overrides,
  };
}

const CATALOGUE = [
  model("a-nano", "nano"),
  model("b-large", "large"),
  model("c-nano", "nano"),
  model("d-medium", "medium"),
];

describe("groupByTier", () => {
  it("ordonne les groupes du plus léger au plus lourd", () => {
    const groups = groupByTier(CATALOGUE);

    expect(groups.map((group) => group.tier)).toEqual(["nano", "medium", "large"]);
  });

  it("omet les paliers vides", () => {
    // Un entête « xlarge » suivi de rien serait un cul-de-sac visuel.
    const groups = groupByTier(CATALOGUE);

    expect(groups.map((group) => group.tier)).not.toContain("xlarge");
  });

  it("préserve l'ordre du catalogue à l'intérieur d'un palier", () => {
    const nano = groupByTier(CATALOGUE).find((group) => group.tier === "nano");

    expect(nano?.models.map((entry) => entry.id)).toEqual(["a-nano", "c-nano"]);
  });

  it("prend le libellé de palier du serveur, pas une constante locale", () => {
    // Ajouter un palier au catalogue ne doit demander qu'une ligne côté Python.
    const groups = groupByTier([model("x", "nano", { tierLabel: "Ultra léger" })]);

    expect(groups[0]?.label).toBe("Ultra léger");
  });

  it("**ne fait pas disparaître** un modèle de palier inconnu", () => {
    // Il serait invisible dans l'interface tout en restant analysable par l'API :
    // le pire des deux mondes.
    const exotic = { ...model("z", "nano"), tier: "gigantic" as ModelTier };
    const groups = groupByTier([...CATALOGUE, exotic]);

    expect(flatOrder(groups).map((entry) => entry.id)).toContain("z");
    expect(groups[groups.length - 1]?.label).toBe("Autres");
  });

  it("gère un catalogue vide", () => {
    expect(groupByTier([])).toEqual([]);
  });
});

describe("flatOrder — l'ordre que suit le clavier", () => {
  it("aplatit les groupes dans l'ordre visuel", () => {
    // La navigation clavier et l'œil doivent être d'accord : `flatOrder` dérive de
    // `groupByTier`, jamais du tableau d'origine.
    expect(flatOrder(groupByTier(CATALOGUE)).map((entry) => entry.id)).toEqual([
      "a-nano",
      "c-nano",
      "d-medium",
      "b-large",
    ]);
  });

  it("contient exactement les modèles du catalogue", () => {
    expect(flatOrder(groupByTier(CATALOGUE))).toHaveLength(CATALOGUE.length);
  });
});

describe("nextIndex — navigation à plat", () => {
  const COUNT = 4;

  it("descend d'un cran, **y compris à travers une frontière de groupe**", () => {
    // Le test central du module. L'index 1 est le dernier « nano », l'index 2 le
    // premier « medium » : la flèche doit franchir la frontière sans rien de spécial.
    expect(nextIndex("ArrowDown", 1, COUNT)).toBe(2);
  });

  it("remonte d'un cran", () => {
    expect(nextIndex("ArrowUp", 2, COUNT)).toBe(1);
  });

  it("**ne boucle pas** en bas de liste", () => {
    // Le bouclage désoriente : on croit avoir tout parcouru alors qu'on est revenu
    // au début sans le voir passer.
    expect(nextIndex("ArrowDown", COUNT - 1, COUNT)).toBe(COUNT - 1);
  });

  it("ne boucle pas en haut de liste", () => {
    expect(nextIndex("ArrowUp", 0, COUNT)).toBe(0);
  });

  it("va au début et à la fin avec Home et End", () => {
    expect(nextIndex("Home", 2, COUNT)).toBe(0);
    expect(nextIndex("End", 0, COUNT)).toBe(COUNT - 1);
  });

  it("saute de cinq avec PageUp et PageDown, en restant borné", () => {
    expect(nextIndex("PageDown", 0, COUNT)).toBe(COUNT - 1);
    expect(nextIndex("PageUp", COUNT - 1, COUNT)).toBe(0);
  });

  it("rend null pour une touche qui ne navigue pas", () => {
    // L'appelant n'a pas à décider s'il consomme l'événement.
    expect(nextIndex("a", 0, COUNT)).toBeNull();
    expect(nextIndex("Enter", 0, COUNT)).toBeNull();
  });

  it("rend null sur une liste vide plutôt qu'un index invalide", () => {
    expect(nextIndex("ArrowDown", 0, 0)).toBeNull();
  });
});

describe("les trois états d'un modèle", () => {
  it("annonce le téléchargement d'un modèle absent, avec sa taille", () => {
    // C'est la distinction qui supprime le « pourquoi ma première analyse a mis
    // 90 secondes ».
    const label = modelStateLabel(model("x", "xlarge", { sizeMb: 137 }));

    expect(label).toContain("premier usage");
    expect(label).toContain("137 Mo");
  });

  it("distingue téléchargé de résident", () => {
    expect(modelStateLabel(model("x", "nano", { downloaded: true }))).toBe("téléchargé");
    expect(modelStateLabel(model("x", "nano", { downloaded: true, loaded: true }))).toBe(
      "résident en mémoire",
    );
  });
});

describe("taille affichée", () => {
  it("préfère la taille réelle sur disque quand elle est connue", () => {
    // `sizeMb` du catalogue est une estimation ; la vérité vient du disque.
    expect(modelSizeLabel(model("x", "nano", { sizeBytes: 6_291_456 }))).toBe("6.0 Mo");
  });

  it("marque l'estimation d'un tilde quand le poids est absent", () => {
    expect(modelSizeLabel(model("x", "nano", { sizeMb: 6 }))).toBe("~6 Mo");
  });
});

describe("ordre des paliers", () => {
  it("suit la progression de taille du catalogue", () => {
    expect([...TIER_ORDER]).toEqual(["nano", "small", "medium", "large", "xlarge"]);
  });
});
