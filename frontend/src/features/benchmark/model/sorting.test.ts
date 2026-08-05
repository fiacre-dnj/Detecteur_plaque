/**
 * Tri du tableau de benchmark.
 *
 * Le test central : **les lignes en échec restent en bas**. Leur `medianMs` vaut 0,
 * donc un tri croissant naïf les placerait en tête, et le modèle affiché comme « le
 * plus rapide » serait systématiquement celui qui n'a pas pu être mesuré.
 */

import { describe, expect, it } from "bun:test";

import type { BenchmarkEntry } from "@/shared/api/contracts";

import {
  DEFAULT_SORT,
  formatMs,
  maxOf,
  nextSort,
  relativeWidth,
  sortEntries,
} from "./sorting";

function entry(
  modelId: string,
  medianMs: number,
  overrides: Partial<BenchmarkEntry> = {},
): BenchmarkEntry {
  return {
    modelId,
    label: modelId.toUpperCase(),
    tier: "nano",
    loadMs: 100,
    medianMs,
    p95Ms: medianMs * 1.2,
    minMs: medianMs * 0.9,
    maxMs: medianMs * 1.4,
    fps: medianMs > 0 ? 1000 / medianMs : 0,
    preprocessMs: 1.5,
    postprocessMs: 0.8,
    detections: 3,
    frames: 5,
    wasLoaded: false,
    released: true,
    error: null,
    ...overrides,
  };
}

describe("sortEntries — les échecs restent en bas", () => {
  const entries = [
    entry("rapide", 10),
    entry("casse", 0, { error: "Poids indisponibles." }),
    entry("lent", 200),
  ];

  it("**place l'échec en dernier en tri croissant**", () => {
    // Sans cette règle, « casse » (médiane 0) serait premier et passerait pour le
    // modèle le plus rapide.
    const sorted = sortEntries(entries, { column: "medianMs", direction: "asc" });

    expect(sorted.map((row) => row.modelId)).toEqual(["rapide", "lent", "casse"]);
  });

  it("place l'échec en dernier **aussi** en tri décroissant", () => {
    // La règle ne dépend pas du sens : un échec n'est ni rapide ni lent, il est
    // hors mesure.
    const sorted = sortEntries(entries, { column: "medianMs", direction: "desc" });

    expect(sorted.map((row) => row.modelId)).toEqual(["lent", "rapide", "casse"]);
  });

  it("garde plusieurs échecs groupés en bas", () => {
    const withTwo = [...entries, entry("casse2", 0, { error: "Mémoire insuffisante." })];
    const sorted = sortEntries(withTwo, DEFAULT_SORT);

    expect(sorted.slice(-2).every((row) => row.error !== null)).toBe(true);
  });
});

describe("sortEntries — colonnes", () => {
  it("trie les durées numériquement", () => {
    const sorted = sortEntries([entry("a", 100), entry("b", 20)], {
      column: "medianMs",
      direction: "asc",
    });

    expect(sorted[0]?.modelId).toBe("b");
  });

  it("trie les libellés selon l'alphabet français", () => {
    // Sans `localeCompare("fr")`, « É » se classe après « Z ».
    const sorted = sortEntries(
      [entry("z", 1, { label: "Zèbre" }), entry("e", 1, { label: "Éléphant" })],
      { column: "label", direction: "asc" },
    );

    expect(sorted[0]?.label).toBe("Éléphant");
  });

  it("trie les paliers par taille, pas alphabétiquement", () => {
    // Alphabétiquement, « large » viendrait avant « nano », ce qui n'a aucun sens
    // pour un palier de modèle.
    const sorted = sortEntries(
      [entry("l", 1, { tier: "large" }), entry("n", 1, { tier: "nano" })],
      { column: "tier", direction: "asc" },
    );

    expect(sorted[0]?.tier).toBe("nano");
  });

  it("est stable à valeur égale", () => {
    // Sinon deux modèles de même médiane permuteraient d'un rafraîchissement à
    // l'autre, ce qui rend le tableau désagréable à lire pendant un run.
    const same = [entry("a", 50), entry("b", 50), entry("c", 50)];
    const sorted = sortEntries(same, DEFAULT_SORT);

    expect(sorted.map((row) => row.modelId)).toEqual(["a", "b", "c"]);
  });

  it("ne modifie pas le tableau d'origine", () => {
    const original = [entry("a", 100), entry("b", 20)];
    sortEntries(original, DEFAULT_SORT);

    expect(original[0]?.modelId).toBe("a");
  });
});

describe("nextSort", () => {
  it("inverse le sens sur la même colonne", () => {
    expect(nextSort({ column: "medianMs", direction: "asc" }, "medianMs")).toEqual({
      column: "medianMs",
      direction: "desc",
    });
  });

  it("repart en croissant sur une autre colonne", () => {
    // Croissant est le sens le plus utile pour une durée : le plus rapide d'abord,
    // ce qui est la question qu'on se pose. Conserver le sens précédent obligerait
    // à deux clics.
    expect(nextSort({ column: "medianMs", direction: "desc" }, "loadMs")).toEqual({
      column: "loadMs",
      direction: "asc",
    });
  });
});

describe("barres relatives", () => {
  it("mesure en pourcentage du maximum de la colonne", () => {
    // Sur le maximum et non une échelle absolue : sur GPU, toutes les barres
    // seraient minuscules avec une échelle fixe.
    expect(relativeWidth(50, 200)).toBe(25);
    expect(relativeWidth(200, 200)).toBe(100);
  });

  it("rend 0 pour une valeur absente plutôt qu'une barre pleine", () => {
    // Une barre pleine suggérerait la mesure la plus lente, alors qu'il n'y a pas
    // de mesure du tout.
    expect(relativeWidth(0, 200)).toBe(0);
  });

  it("ne divise pas par zéro quand tout a échoué", () => {
    expect(relativeWidth(10, 0)).toBe(0);
  });

  it("exclut les échecs du maximum", () => {
    // Un échec à 0 ne change rien au maximum, mais l'inclure dans le calcul serait
    // le signe qu'on le traite comme une mesure.
    const entries = [entry("a", 100), entry("b", 0, { error: "échec" })];

    expect(maxOf(entries, "medianMs")).toBe(100);
  });

  it("rend 0 comme maximum quand aucune ligne n'a abouti", () => {
    expect(maxOf([entry("a", 0, { error: "échec" })], "medianMs")).toBe(0);
  });
});

describe("formatMs", () => {
  it("affiche les millisecondes au dixième", () => {
    expect(formatMs(215.53)).toBe("215.5 ms");
  });

  it("passe en secondes au-delà de mille millisecondes", () => {
    // Un chargement de 28 466 ms se lit mal ; « 28.47 s » se lit d'un coup d'œil.
    expect(formatMs(28_465.79)).toBe("28.47 s");
  });

  it("affiche un tiret pour une mesure absente", () => {
    // `loadMs = 0` veut dire « déjà résident, rien à charger » : afficher
    // « 0.0 ms » suggérerait un chargement instantané.
    expect(formatMs(0)).toBe("—");
  });
});
