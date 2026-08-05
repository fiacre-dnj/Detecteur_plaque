/**
 * La fenêtre de virtualisation.
 *
 * Testée sans DOM, ce qui est tout l'intérêt d'avoir extrait le calcul : les cas
 * limites — défilement négatif du rebond élastique, tableau vide, viewport plus
 * grand que le contenu — sont exactement ceux qui produisent des indices hors
 * tableau et un écran blanc en production.
 */

import { describe, expect, it } from "bun:test";

import {
  INITIAL_ROWS,
  OVERSCAN,
  ROW_HEIGHT,
  VIRTUALISE_THRESHOLD,
  shouldVirtualise,
  visibleWindow,
} from "./virtualise";

/** 1 000 lignes de 36 px dans un viewport de 360 px : 10 lignes visibles. */
const COUNT = 1_000;
const VIEWPORT = 360;

describe("visibleWindow", () => {
  it("rend les premières lignes en haut du tableau", () => {
    const window = visibleWindow(COUNT, 0, VIEWPORT);

    expect(window.start).toBe(0);
    // 10 visibles + la marge de sur-rendu.
    expect(window.end).toBe(10 + OVERSCAN);
    expect(window.offsetTop).toBe(0);
  });

  it("décale la fenêtre au fil du défilement", () => {
    // 20 lignes défilées : la fenêtre commence à 20 moins la marge.
    const window = visibleWindow(COUNT, 20 * ROW_HEIGHT, VIEWPORT);

    expect(window.start).toBe(20 - OVERSCAN);
    expect(window.offsetTop).toBe((20 - OVERSCAN) * ROW_HEIGHT);
  });

  it("garde une marge de sur-rendu pour éviter le scintillement", () => {
    // Sans marge, un défilement rapide laisse du vide le temps du rendu suivant.
    const window = visibleWindow(COUNT, 40 * ROW_HEIGHT, VIEWPORT);

    expect(window.start).toBeLessThan(40);
    expect(window.end).toBeGreaterThan(40 + 10);
  });

  it("donne la hauteur totale, pour que la barre de défilement soit juste", () => {
    // Une hauteur fausse rendrait la barre incohérente avec le contenu : on
    // atteindrait le bas de la barre au milieu du tableau.
    expect(visibleWindow(COUNT, 0, VIEWPORT).totalHeight).toBe(COUNT * ROW_HEIGHT);
  });

  it("ne dépasse jamais la fin du tableau", () => {
    // Le cas qui produit un écran blanc : des indices au-delà du tableau rendent
    // des lignes `undefined`.
    const window = visibleWindow(COUNT, 10_000 * ROW_HEIGHT, VIEWPORT);

    expect(window.end).toBe(COUNT);
    expect(window.start).toBeLessThan(COUNT);
  });

  it("**supporte un défilement négatif**, que produit le rebond élastique", () => {
    // macOS et iOS rendent un `scrollTop` négatif pendant le rebond. Sans la
    // borne, `start` serait négatif et le tableau afficherait du vide.
    const window = visibleWindow(COUNT, -250, VIEWPORT);

    expect(window.start).toBe(0);
    expect(window.offsetTop).toBe(0);
  });

  it("gère un tableau vide sans produire d'indices", () => {
    const window = visibleWindow(0, 0, VIEWPORT);

    expect(window).toEqual({ start: 0, end: 0, totalHeight: 0, offsetTop: 0 });
  });

  it("gère un viewport de hauteur nulle, avant la mesure du conteneur", () => {
    // Au premier rendu, `clientHeight` vaut 0 : rendre toutes les lignes à ce
    // moment annulerait le bénéfice de la virtualisation.
    expect(visibleWindow(COUNT, 0, 0).end).toBe(0);
  });

  it("rend tout le contenu quand il tient dans le viewport", () => {
    const window = visibleWindow(5, 0, VIEWPORT);

    expect(window.start).toBe(0);
    expect(window.end).toBe(5);
  });

  it("couvre toujours la zone visible, quelle que soit la position", () => {
    // Propriété générale : la fenêtre doit contenir la première et la dernière
    // ligne réellement visibles, sinon des trous apparaissent à l'écran.
    for (const scrollTop of [0, 37, 500, 3_600, 12_345, 35_000]) {
      const window = visibleWindow(COUNT, scrollTop, VIEWPORT);
      const firstVisible = Math.floor(
        Math.max(0, Math.min(scrollTop, COUNT * ROW_HEIGHT - VIEWPORT)) / ROW_HEIGHT,
      );
      const lastVisible = Math.min(
        COUNT - 1,
        firstVisible + Math.ceil(VIEWPORT / ROW_HEIGHT) - 1,
      );

      expect(window.start, `scroll=${scrollTop}`).toBeLessThanOrEqual(firstVisible);
      expect(window.end, `scroll=${scrollTop}`).toBeGreaterThan(lastVisible);
    }
  });
});

describe("seuil de virtualisation", () => {
  it("ne virtualise pas en dessous de 200 lignes", () => {
    // En dessous, virtualiser coûte plus qu'il ne rapporte : on ajoute des
    // conteneurs et un calcul pour économiser des nœuds que le navigateur gère
    // très bien.
    expect(shouldVirtualise(12)).toBe(false);
    expect(shouldVirtualise(VIRTUALISE_THRESHOLD)).toBe(false);
  });

  it("virtualise au-delà", () => {
    expect(shouldVirtualise(VIRTUALISE_THRESHOLD + 1)).toBe(true);
    expect(shouldVirtualise(10_000)).toBe(true);
  });

  it("garde les valeurs de la spécification", () => {
    expect(VIRTUALISE_THRESHOLD).toBe(200);
    expect(INITIAL_ROWS).toBe(12);
  });
});
