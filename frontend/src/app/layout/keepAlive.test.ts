/**
 * L'appariement URL → page, qui a remplacé les routes enfants du routeur.
 *
 * Le cas qui compte : `/` ne doit désigner **que** le studio. Une comparaison par
 * préfixe le laisserait actif sur les trois onglets, et deux pages visibles à la
 * fois est exactement le mode de panne que ce commutateur peut produire.
 */

import { describe, expect, it } from "bun:test";

import { PAGE_IDS, activePageId, normalisePath } from "./keepAlive";

describe("activePageId", () => {
  it("apparie chaque page à son chemin", () => {
    expect(activePageId("/")).toBe("studio");
    expect(activePageId("/historique")).toBe("history");
    expect(activePageId("/benchmark")).toBe("benchmark");
  });

  it("ne laisse pas la racine désigner les autres pages", () => {
    expect(activePageId("/benchmark")).not.toBe("studio");
  });

  it("tolère la barre finale, qui ne change pas de page", () => {
    expect(activePageId("/historique/")).toBe("history");
    expect(activePageId("/")).toBe("studio");
    expect(normalisePath("/")).toBe("/");
  });

  it("rend `null` sur une URL inconnue — c'est la page d'erreur", () => {
    expect(activePageId("/inconnue")).toBeNull();
    expect(activePageId("/historique/42")).toBeNull();
  });

  it("garde le studio en premier : l'ordre de rendu doit être stable", () => {
    // React réconcilie ces conteneurs par leur position ; un ordre qui changerait
    // d'une navigation à l'autre remonterait les pages, ce que tout ce mécanisme
    // existe pour éviter.
    expect(PAGE_IDS).toEqual(["studio", "history", "benchmark"]);
  });
});
