/**
 * Ce que ce test protège : **l'étiquette de plaque qui sort du canvas**.
 *
 * Une plaque lisible est une plaque proche, donc basse dans l'image. Sans bascule vers
 * le haut, l'étiquette disparaîtrait précisément quand elle porte l'information la plus
 * sûre — et le seul symptôme serait « ça ne s'affiche pas », sans rien à déboguer.
 *
 * `plateLabelBaseline` est extraite pour cette raison : `drawLabelAt` a besoin d'un
 * contexte 2D, ce calcul non — et il n'y a ni jsdom ni testing-library dans ce projet.
 */

import { describe, expect, it } from "bun:test";

import type { Box } from "@/shared/api/contracts";

import { plateLabelBaseline } from "./draw";

/** Hauteur d'étiquette + écart, tels que `drawLabelAt` les peint. */
const LABEL_SPACE = 18;

function plateBox(y: number, height = 9): Box {
  return { x: 100, y, width: 32, height };
}

describe("plateLabelBaseline", () => {
  it("pose l'étiquette sous le rectangle quand la place existe", () => {
    const box = plateBox(200);
    expect(plateLabelBaseline(box, 1080)).toBe(200 + 9 + LABEL_SPACE);
  });

  it("bascule au-dessus quand le bas du canvas est atteint", () => {
    // Le cas réel : un véhicule proche, en bas de l'image, dont la plaque est la
    // mieux lue de toute la scène.
    const box = plateBox(1060);
    expect(plateLabelBaseline(box, 1080)).toBe(1060 - 2);
  });

  it("reste en dessous quand il ne manque pas un pixel", () => {
    // La frontière, et non le cas facile : `below === canvasHeight` doit encore
    // passer, sinon la dernière ligne utile de l'image serait perdue.
    const box = plateBox(1080 - 9 - LABEL_SPACE);
    expect(plateLabelBaseline(box, 1080)).toBe(1080);
  });

  it("bascule dès qu'il manque un seul pixel", () => {
    const y = 1080 - 9 - LABEL_SPACE + 1;
    expect(plateLabelBaseline(plateBox(y), 1080)).toBe(y - 2);
  });

  it("tient compte de la hauteur du rectangle, pas seulement de son sommet", () => {
    // Une plaque vue de près est plus haute : son étiquette descend d'autant.
    const petite = plateLabelBaseline(plateBox(500, 9), 1080);
    const grande = plateLabelBaseline(plateBox(500, 40), 1080);
    expect(grande - petite).toBe(31);
  });
});
