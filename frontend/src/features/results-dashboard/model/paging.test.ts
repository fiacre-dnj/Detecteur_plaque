/**
 * `pageWindow` — et surtout le cas où la liste rétrécit sous la page courante.
 *
 * C'est le seul mode de panne qui compte ici : les lignes se retirent du tracé
 * pendant qu'on lit une page, et une fenêtre laissée hors bornes rendrait une
 * liste vide sous une pagination qui annonce des éléments.
 */

import { describe, expect, it } from "bun:test";

import { pageWindow } from "./paging";

describe("pageWindow", () => {
  it("ne pagine pas tant que tout tient sur une page", () => {
    const w = pageWindow(6, 6, 0);
    expect(w).toEqual({ page: 0, pageCount: 1, start: 0, end: 6, paginated: false });
  });

  it("découpe la dernière page sur ce qui reste", () => {
    const w = pageWindow(14, 6, 2);
    expect(w.start).toBe(12);
    expect(w.end).toBe(14);
    expect(w.pageCount).toBe(3);
    expect(w.paginated).toBe(true);
  });

  it("ramène une page au-delà de la fin sur la dernière", () => {
    // Trois lignes retirées du tracé pendant qu'on lisait la page 3.
    const w = pageWindow(7, 6, 5);
    expect(w.page).toBe(1);
    expect(w.start).toBe(6);
    expect(w.end).toBe(7);
  });

  it("ramène une page négative sur la première", () => {
    expect(pageWindow(10, 6, -3).page).toBe(0);
  });

  it("rend une page unique et vide pour une liste vide", () => {
    const w = pageWindow(0, 6, 4);
    expect(w).toEqual({ page: 0, pageCount: 1, start: 0, end: 0, paginated: false });
  });

  it("supporte une taille de page absurde", () => {
    expect(pageWindow(5, 0, 0).pageCount).toBe(5);
  });

  it("couvre exactement la liste, page après page", () => {
    const total = 13;
    const seen: number[] = [];
    for (let page = 0; page < pageWindow(total, 4, 0).pageCount; page += 1) {
      const w = pageWindow(total, 4, page);
      for (let i = w.start; i < w.end; i += 1) seen.push(i);
    }
    expect(seen).toEqual(Array.from({ length: total }, (_, i) => i));
  });
});
